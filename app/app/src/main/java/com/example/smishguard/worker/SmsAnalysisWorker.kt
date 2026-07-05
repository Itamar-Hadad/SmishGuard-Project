package com.example.smishguard.worker

import android.content.Context
import androidx.work.CoroutineWorker
import androidx.work.WorkerParameters
import com.example.smishguard.data.repository.AnalysisResult
import com.example.smishguard.data.repository.SmsAnalysisRepo
import com.example.smishguard.notification.NotificationHelper
import com.example.smishguard.SmishGuardAppContainer

class SmsAnalysisWorker(
    context: Context,
    params: WorkerParameters
) : CoroutineWorker(context, params) {

    private val repo: SmsAnalysisRepo by lazy {
        SmishGuardAppContainer.provideSmsAnalysisRepo()
    }

    override suspend fun doWork(): Result {
        val message = inputData.getString(KEY_MESSAGE) ?: return Result.failure()
        val sender = inputData.getString(KEY_SENDER) ?: "Unknown"

        return try {
            when (val result = repo.analyze(message, sender)) {
                is AnalysisResult.Success -> {
                    if (result.response.isPhishing) {
                        NotificationHelper.sendAlert(applicationContext, message, sender)
                    }
                    Result.success()
                }
                is AnalysisResult.Error -> {
                    if (runAttemptCount < MAX_RETRIES) {
                        Result.retry()
                    } else {
                        Result.failure()
                    }
                }
            }
        } catch (e: Exception) {
            if (runAttemptCount < MAX_RETRIES) {
                Result.retry()
            } else {
                Result.failure()
            }
        }
    }

    companion object {
        private const val KEY_MESSAGE = "message"
        private const val KEY_SENDER = "sender"
        private const val MAX_RETRIES = 3
        private const val WORK_NAME_PREFIX = "sms_analysis_"
        private const val MIN_BACKOFF_MILLIS = 10_000L

        fun enqueue(context: Context, sender: String, message: String) {
            val data = androidx.work.Data.Builder()
                .putString(KEY_MESSAGE, message)
                .putString(KEY_SENDER, sender)
                .build()

            val workRequest = androidx.work.OneTimeWorkRequestBuilder<SmsAnalysisWorker>()
                .setInputData(data)
                .setBackoffCriteria(
                    androidx.work.BackoffPolicy.LINEAR,
                    MIN_BACKOFF_MILLIS,
                    java.util.concurrent.TimeUnit.MILLISECONDS
                )
                .build()

            androidx.work.WorkManager.getInstance(context).enqueue(workRequest)
        }
    }
}
