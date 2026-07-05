package com.example.smishguard.data.repository

import com.example.smishguard.data.remote.AnalysisRequest
import com.example.smishguard.data.remote.AnalysisResponse
import com.example.smishguard.data.remote.ApiService
import com.example.smishguard.data.storage.StatsStore

class SmsAnalysisRepo(
    private val apiService: ApiService,
    private val statsStore: StatsStore
) {
    suspend fun analyze(message: String, sender: String = "Unknown"): AnalysisResult {
        val truncatedMessage = if (message.length > 500) message.take(500) else message
        val request = AnalysisRequest(
            message = truncatedMessage,
            sender = sender
        )

        return try {
            val response = apiService.analyze(request)
            if (response.isSuccessful) {
                val body = response.body()
                if (body != null) {
                    statsStore.incrementScanned()
                    if (body.isPhishing) {
                        statsStore.incrementPhishing()
                    }
                    AnalysisResult.Success(body)
                } else {
                    AnalysisResult.Error("Empty response body")
                }
            } else {
                AnalysisResult.Error("API error: ${response.code()}")
            }
        } catch (e: Exception) {
            AnalysisResult.Error(e.message ?: "Unknown error")
        }
    }
}

sealed class AnalysisResult {
    data class Success(val response: AnalysisResponse) : AnalysisResult()
    data class Error(val message: String) : AnalysisResult()
}
