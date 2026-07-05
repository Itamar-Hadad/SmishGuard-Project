package com.example.smishguard.data.remote

import okhttp3.OkHttpClient
import okhttp3.logging.HttpLoggingInterceptor
import retrofit2.Retrofit
import retrofit2.converter.gson.GsonConverterFactory
import retrofit2.Response

class RealApiService(
    baseUrl: String = "https://smishguard-1.onrender.com/"
) : ApiService {
    private val api: ApiService by lazy {
        Retrofit.Builder()
            .baseUrl(baseUrl)
            .addConverterFactory(GsonConverterFactory.create())
            .client(
                OkHttpClient.Builder()
                    .addInterceptor(HttpLoggingInterceptor().apply {
                        level = if (com.example.smishguard.BuildConfig.DEBUG)
                            HttpLoggingInterceptor.Level.BODY
                        else
                            HttpLoggingInterceptor.Level.NONE
                    })
                    .build()
            )
            .build()
            .create(ApiService::class.java)
    }

    override suspend fun analyze(request: AnalysisRequest): Response<AnalysisResponse> {
        return api.analyze(request)
    }
}
