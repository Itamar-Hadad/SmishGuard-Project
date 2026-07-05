package com.example.smishguard.ui.permission

import android.Manifest
import android.content.Intent
import android.content.pm.PackageManager
import android.net.Uri
import android.os.Build
import android.os.Bundle
import android.provider.Settings
import android.util.Log
import android.view.View
import android.widget.Toast
import androidx.activity.result.contract.ActivityResultContracts
import androidx.activity.viewModels
import androidx.appcompat.app.AppCompatActivity
import androidx.core.content.ContextCompat
import com.example.smishguard.MainActivity
import com.example.smishguard.R
import com.example.smishguard.databinding.ActivityPermissionBinding
import com.google.android.material.button.MaterialButton

class PermissionActivity : AppCompatActivity() {

    private lateinit var binding: ActivityPermissionBinding
    private var step = 0 // 0 = SMS permission, 1 = Notification permission

    private val requestPermissionLauncher = registerForActivityResult(
        ActivityResultContracts.RequestMultiplePermissions()
    ) { permissions ->
        val allGranted = permissions.values.all { it }
        Log.d("PermissionActivity", "SMS permissions result: $permissions, step: $step")
        if (allGranted) {
            step = 1
            checkNotificationPermission()
        } else {
            showSettingsOption()
        }
    }

    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        binding = ActivityPermissionBinding.inflate(layoutInflater)
        setContentView(binding.root)

        if (hasSmsPermission()) {
            step = 1
            checkNotificationPermission()
            return
        }

        setupClickListeners()
    }

    override fun onResume() {
        super.onResume()
        Log.d("PermissionActivity", "onResume, step: $step, sms: ${hasSmsPermission()}")
        if (step == 1 && hasSmsPermission()) {
            checkNotificationPermission()
        }
    }

    private fun setupClickListeners() {
        binding.btnGrantPermission.setOnClickListener {
            if (step == 0) {
                requestSmsPermissions()
            } else if (step == 1 && Build.VERSION.SDK_INT >= Build.VERSION_CODES.TIRAMISU) {
                requestNotificationPermissionLauncher.launch(Manifest.permission.POST_NOTIFICATIONS)
            }
        }

        binding.tvOpenSettings.setOnClickListener {
            openAppSettings()
        }
    }

    private fun requestSmsPermissions() {
        val permissions = arrayOf(
            Manifest.permission.RECEIVE_SMS,
            Manifest.permission.READ_SMS
        )
        Log.d("PermissionActivity", "Requesting SMS permissions: ${permissions.toList()}")
        requestPermissionLauncher.launch(permissions)
    }

    private fun hasSmsPermission(): Boolean {
        return ContextCompat.checkSelfPermission(
            this,
            Manifest.permission.RECEIVE_SMS
        ) == PackageManager.PERMISSION_GRANTED
    }

    private fun checkNotificationPermission() {
        if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.TIRAMISU) {
            val hasPermission = ContextCompat.checkSelfPermission(
                this,
                Manifest.permission.POST_NOTIFICATIONS
            ) == PackageManager.PERMISSION_GRANTED
            Log.d("PermissionActivity", "Notification permission granted: $hasPermission")

            if (!hasPermission) {
                // Update UI for notification permission step
                binding.tvTitle.text = "Notifications Required"
                binding.tvDescription.text = "SmishGuard needs to send you alerts when a phishing attempt is detected."
                binding.tvRequired.text = "Enable notifications so you don't miss any security alerts."
                binding.tvPrivacyIcon.text = "🔔"
                binding.tvPrivacyText.text = "You will receive alerts only when a suspicious message is detected."
                binding.btnGrantPermission.text = "Grant Notification Permission"
                binding.btnGrantPermission.setIconResource(android.R.drawable.ic_dialog_info)
            } else {
                launchMainScreen()
            }
        } else {
            launchMainScreen()
        }
    }

    private val requestNotificationPermissionLauncher = registerForActivityResult(
        ActivityResultContracts.RequestPermission()
    ) { isGranted ->
        Log.d("PermissionActivity", "Notification permission result: $isGranted")
        launchMainScreen()
    }

    private fun launchMainScreen() {
        val intent = Intent(this, MainActivity::class.java)
        startActivity(intent)
        finish()
    }

    private fun showSettingsOption() {
        binding.tvOpenSettings.visibility = View.VISIBLE
        Toast.makeText(
            this,
            "Permission is required. Please enable it in settings.",
            Toast.LENGTH_LONG
        ).show()
    }

    private fun openAppSettings() {
        val intent = Intent(Settings.ACTION_APPLICATION_DETAILS_SETTINGS).apply {
            data = Uri.fromParts("package", packageName, null)
        }
        startActivity(intent)
    }

    override fun onBackPressed() {
    }
}

