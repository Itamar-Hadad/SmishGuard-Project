<div align="center">
<img src="../docs/assets/logo.png" alt="SmishGuard logo" width="90" />

# SmishGuard: Backend API

**FastAPI microservice that bridges the Android app to the ML detection pipeline.**

[![FastAPI](https://img.shields.io/badge/FastAPI-0.115-009688?logo=fastapi&logoColor=white)]()
[![Uvicorn](https://img.shields.io/badge/Uvicorn-ASGI-2E7D32)]()
[![Deployed on Render](https://img.shields.io/badge/Deployed%20on-Render-46E3B7?logo=render&logoColor=white)](https://smishguard-1.onrender.com)

</div>

Part of the [SmishGuard](../README.md) project. Loads the model trained in [`../model`](../model/README.md) and exposes it as a single classification endpoint consumed by the [Android app](../app/README.md).

## Contents

- [API Reference](#api-reference)
- [Architecture](#architecture)
- [Local Setup](#local-setup)
- [Deployment](#deployment)

## API Reference

### `GET /`

Basic liveness message.

```json
{ "message": "SmishGuard API is running", "version": "1.0.0" }
```

### `GET /health`

Health check used by the deployment platform.

```json
{ "status": "ok" }
```

### `POST /analyze-sms`

Classifies a single SMS message.

**Request**

```json
{ "message": "URGENT: Your account is suspended. Click here to verify." }
```

**Response: smishing detected**

```json
{
  "is_smishing": true,
  "confidence": 0.94,
  "label": "smish",
  "reason": "ML model classification"
}
```

**Response: legitimate message**

```json
{
  "is_smishing": false,
  "confidence": 0.95,
  "label": "ham",
  "reason": "No smishing pattern detected"
}
```

| Status | When |
|---|---|
| `200` | Message classified successfully |
| `422` | `message` missing or empty (Pydantic validation) |
| `500` | Unhandled error during analysis |

**Try it:**

```bash
curl -X POST https://smishguard-1.onrender.com/analyze-sms \
  -H "Content-Type: application/json" \
  -d '{"message": "URGENT: Your account is suspended. Click here to verify."}'
```

Interactive Swagger docs are available at `/docs` on any running instance.

## Architecture

```
app/
├── main.py                    FastAPI app factory · CORS (allow all) · lifespan hook loads the model once at startup
├── routes/sms.py              POST /analyze-sms: thin route, delegates to the service layer
├── schemas/sms.py              Pydantic request/response models (message validation, response shape)
└── services/sms_analyzer.py    Bridges to the ML pipeline
```

`sms_analyzer.py` does **not** keep its own copy of the model. It resolves the sibling `../model` directory at import time, adds it to `sys.path`, and imports `predict_message` plus the model/encoder/TF-IDF file paths directly from `MLsmish.py`, loading the exact `.pkl` artifacts the training script produced. This means:

- Retraining the model (`python MLsmish.py` in `model/`) and restarting the backend is the entire deploy loop for a new model. There's no separate copy step.
- The backend and the model pipeline must always be deployed together, one directory apart.

The SBERT model, classifier, label encoder, and TF-IDF vectorizer are all loaded once at startup (via FastAPI's `lifespan` context) rather than per-request, so a cold instance takes a few seconds to become ready but every subsequent request is fast.

## Local Setup

```bash
cd backend
pip install -r requirements.txt
uvicorn app.main:app --reload --port 8000
# or: python app/main.py
```

The API is now available at `http://localhost:8000` (docs at `/docs`).

**Connecting the Android app to a local backend:**

| Environment | Base URL |
|---|---|
| Android Emulator → host machine | `http://10.0.2.2:8000/` |
| Physical device on the same Wi-Fi | `http://<your-machine-IP>:8000/` |

## Deployment

Deployed on [Render](https://render.com) using `Procfile`:

```
web: uvicorn app.main:app --host 0.0.0.0 --port $PORT
```

| Setting | Value |
|---|---|
| Root directory | `SmishGuard/backend` |
| Build command | `pip install -r requirements.txt` |
| Start command | `uvicorn app.main:app --host 0.0.0.0 --port $PORT` |

> Render's root directory must point at `SmishGuard/backend` (not the old top-level `backend/`). The ML pipeline it depends on lives one level up, at `SmishGuard/model`, so Render's build must have the full `SmishGuard/` tree checked out.