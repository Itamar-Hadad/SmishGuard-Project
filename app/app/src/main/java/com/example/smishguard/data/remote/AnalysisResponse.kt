package com.example.smishguard.data.remote

import com.google.gson.annotations.SerializedName

data class AnalysisResponse(
    @SerializedName("is_smishing")
    val isPhishing: Boolean,
    val confidence: Float,
    val label: String,
    val reason: String
)

data class ErrorResponse(
    val error: String,
    val message: String,
    @SerializedName("retry_after")
    val retryAfter: Int? = null
)
