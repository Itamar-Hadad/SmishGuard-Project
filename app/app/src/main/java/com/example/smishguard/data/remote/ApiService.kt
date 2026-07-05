package com.example.smishguard.data.remote

import retrofit2.Response
import retrofit2.http.Body
import retrofit2.http.POST

interface ApiService {
    @POST("analyze-sms")
    suspend fun analyze(@Body request: AnalysisRequest): Response<AnalysisResponse>
}
