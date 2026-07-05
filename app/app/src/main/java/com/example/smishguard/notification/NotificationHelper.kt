package com.example.smishguard.notification

import android.Manifest
import android.app.NotificationChannel
import android.app.NotificationManager
import android.app.PendingIntent
import android.content.Context
import android.content.Intent
import android.content.pm.PackageManager
import android.graphics.Bitmap
import android.graphics.Canvas
import android.os.Build
import android.util.Log
import androidx.core.app.NotificationCompat
import androidx.core.app.NotificationManagerCompat
import androidx.core.content.ContextCompat
import com.example.smishguard.MainActivity

object NotificationHelper {
    private const val CHANNEL_ID = "smishguard_alerts"
    private const val CHANNEL_NAME = "Phishing Alerts"
    private const val CHANNEL_DESCRIPTION = "Alerts when a suspicious SMS is detected"
    private const val TAG = "NotificationHelper"

    fun createChannel(context: Context) {
        if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.O) {
            val channel = NotificationChannel(
                CHANNEL_ID,
                CHANNEL_NAME,
                NotificationManager.IMPORTANCE_HIGH
            ).apply {
                description = CHANNEL_DESCRIPTION
                enableVibration(true)
                setShowBadge(true)
                lockscreenVisibility = android.app.Notification.VISIBILITY_PRIVATE
            }

            val notificationManager = context.getSystemService(Context.NOTIFICATION_SERVICE) as NotificationManager
            notificationManager.createNotificationChannel(channel)
            Log.d(TAG, "Notification channel created")
        }
    }

    fun sendAlert(context: Context, message: String, sender: String) {
        if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.TIRAMISU) {
            if (ContextCompat.checkSelfPermission(
                    context,
                    Manifest.permission.POST_NOTIFICATIONS
                ) != PackageManager.PERMISSION_GRANTED
            ) {
                Log.w(TAG, "POST_NOTIFICATIONS permission not granted, cannot send notification")
                return
            }
        }

        try {
            createChannel(context)

            val maskedSender = maskSender(sender)

            // Use the raw, untouched message string directly
            val fullSmsContent = cleanFullMessage(message)

            val intent = Intent(context, MainActivity::class.java).apply {
                flags = Intent.FLAG_ACTIVITY_NEW_TASK or Intent.FLAG_ACTIVITY_CLEAR_TASK
            }

            val pendingIntent = PendingIntent.getActivity(
                context,
                0,
                intent,
                PendingIntent.FLAG_UPDATE_CURRENT or PendingIntent.FLAG_IMMUTABLE
            )

            val launcherIconBitmap = getLauncherIconAsBitmap(context)

            val notification = NotificationCompat.Builder(context, CHANNEL_ID)
                .setSmallIcon(com.example.smishguard.R.drawable.ic_notification_icon)
                .setLargeIcon(launcherIconBitmap)
                .setContentTitle("⚠ Suspicious SMS Detected")
                .setContentText("A message from $maskedSender may be a phishing attempt.")
                .setStyle(
                    NotificationCompat.BigTextStyle()
                        // This will now show the full SMS text layout cleanly!
                        .bigText("A message from $maskedSender may be a phishing attempt.\n\nContent:\n$fullSmsContent")
                )
                .setPriority(NotificationCompat.PRIORITY_HIGH)
                .setAutoCancel(true)
                .setContentIntent(pendingIntent)
                .setVisibility(NotificationCompat.VISIBILITY_PRIVATE)
                .build()

            val notificationId = System.currentTimeMillis().toInt()
            with(NotificationManagerCompat.from(context)) {
                notify(notificationId, notification)
                Log.d(TAG, "Notification sent: $maskedSender")
            }
        } catch (e: Exception) {
            Log.e(TAG, "Failed to send notification", e)
        }
    }

    // Helper function to safely render Adaptive Icons into flat Bitmaps
    private fun getLauncherIconAsBitmap(context: Context): Bitmap? {
        // Tries to pull the round launcher icon first, drops back to standard launcher icon if not found
        val drawable = ContextCompat.getDrawable(context, com.example.smishguard.R.mipmap.ic_launcher_round)
            ?: ContextCompat.getDrawable(context, com.example.smishguard.R.mipmap.ic_launcher)
            ?: return null

        val bitmap = Bitmap.createBitmap(
            drawable.intrinsicWidth.takeIf { it > 0 } ?: 192,
            drawable.intrinsicHeight.takeIf { it > 0 } ?: 192,
            Bitmap.Config.ARGB_8888
        )
        val canvas = Canvas(bitmap)
        drawable.setBounds(0, 0, canvas.width, canvas.height)
        drawable.draw(canvas)
        return bitmap
    }

    private fun maskSender(sender: String): String {
        if (sender.length <= 4) return "XXXX"
        return sender.take(4) + "XXXX"
    }

    private fun cleanFullMessage(message: String): String {
        // 1. Strip out the dangerous URLs
        val withoutUrls = message.replace(Regex("https?://\\S+"), "")
        val cleaned = withoutUrls.replace(Regex("bit\\.ly/\\S+"), "")

        // 2. Return the whole cleaned string without cutting it off!
        return cleaned.ifBlank { "Suspicious content detected" }
    }
}