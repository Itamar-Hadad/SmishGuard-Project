package com.example.smishguard

import android.app.Application

class SmishGuardApp : Application() {

    override fun onCreate() {
        super.onCreate()
        SmishGuardAppContainer.init(this)
    }
}

object SmishGuardAppContainer {
    private lateinit var app: Application
    private val apiService by lazy {
        if (BuildConfig.USE_MOCK_API) com.example.smishguard.data.remote.MockApiService()
        else com.example.smishguard.data.remote.RealApiService(BuildConfig.API_BASE_URL)
    }
    private val statsStore by lazy { com.example.smishguard.data.storage.StatsStore(app) }

    fun init(application: Application) {
        app = application
    }

    fun provideStatsStore() = statsStore

    fun provideApiService(): com.example.smishguard.data.remote.ApiService = apiService

    fun provideSmsAnalysisRepo() = com.example.smishguard.data.repository.SmsAnalysisRepo(
        apiService = apiService,
        statsStore = statsStore
    )
}
