package com.example.smishguard.data.remote

data class AnalysisRequest(
    val message: String,
    val sender: String = "Unknown",
    val timestamp: Long = System.currentTimeMillis(),
    val client_version: String = "1.0.0"
)
