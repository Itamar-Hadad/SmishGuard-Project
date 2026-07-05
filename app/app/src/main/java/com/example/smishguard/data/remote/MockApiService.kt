package com.example.smishguard.data.remote

import kotlinx.coroutines.delay

class MockApiService : ApiService {
    override suspend fun analyze(request: AnalysisRequest): retrofit2.Response<AnalysisResponse> {
        delay(300)
        val keywords = listOf("urgent", "click", "verify", "suspended", "http", "free", "win", "bank", "account")
        val isPhishing = keywords.any { request.message.lowercase().contains(it) }
        return retrofit2.Response.success(
            AnalysisResponse(
                isPhishing = isPhishing,
                confidence = if (isPhishing) 0.91f else 0.05f,
                label = if (isPhishing) "smish" else "ham",
                reason = if (isPhishing) "keyword_match_mock" else "no_suspicious_keywords"
            )
        )
    }
}
