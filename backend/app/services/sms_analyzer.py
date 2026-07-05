import sys
import os
from dataclasses import dataclass

_SMISHGUARD_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "../../../"))
_MODEL_DIR = os.path.join(_SMISHGUARD_ROOT, "model")
if _MODEL_DIR not in sys.path:
    sys.path.insert(0, _MODEL_DIR)

import joblib
from sentence_transformers import SentenceTransformer
from MLsmish import predict_message, SBERT_MODEL_NAME, MODEL_PATH, ENCODER_PATH, TFIDF_PATH

_model = None
_encoder = None
_tfidf = None
_sbert = None


def load_models():
    global _model, _encoder, _tfidf, _sbert
    _model   = joblib.load(os.path.join(_MODEL_DIR, MODEL_PATH))
    _encoder = joblib.load(os.path.join(_MODEL_DIR, ENCODER_PATH))
    _tfidf   = joblib.load(os.path.join(_MODEL_DIR, TFIDF_PATH))
    _sbert   = SentenceTransformer(SBERT_MODEL_NAME)


@dataclass
class AnalysisResult:
    is_smishing: bool
    confidence: float
    label: str
    reason: str


def analyze_sms(message: str) -> AnalysisResult:
    label, confidence = predict_message(
        message,
        model=_model,
        encoder=_encoder,
        sbert=_sbert,
        tfidf=_tfidf,
    )
    is_smishing = label == "smish"
    reason = "ML model classification" if is_smishing else "No smishing pattern detected"
    return AnalysisResult(
        is_smishing=is_smishing,
        confidence=confidence,
        label=label,
        reason=reason,
    )
