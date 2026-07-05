package com.example.smishguard

import android.Manifest
import android.content.Intent
import android.content.pm.PackageManager
import android.content.res.Resources
import android.net.Uri
import android.os.Bundle
import android.provider.Settings
import android.view.View
import android.view.animation.AnimationUtils
import android.widget.FrameLayout
import androidx.activity.enableEdgeToEdge
import androidx.appcompat.app.AppCompatActivity
import androidx.core.content.ContextCompat
import androidx.core.view.ViewCompat
import androidx.core.view.WindowInsetsCompat
import androidx.lifecycle.Lifecycle
import androidx.lifecycle.lifecycleScope
import androidx.lifecycle.repeatOnLifecycle
import com.example.smishguard.databinding.ActivityMainBinding
import com.example.smishguard.ui.home.HomeViewModel
import com.example.smishguard.ui.permission.PermissionActivity
import kotlinx.coroutines.launch

class MainActivity : AppCompatActivity() {

    private lateinit var binding: ActivityMainBinding
    private val viewModel: HomeViewModel by lazy {
        HomeViewModel(SmishGuardAppContainer.provideStatsStore())
    }

    private companion object {
        private const val PREFS_NAME = "SmishGuardPrefs"
        private const val KEY_HAS_COMPLETED_ONBOARDING = "has_completed_onboarding"
    }

    private fun hasCompletedOnboarding(): Boolean {
        val prefs = getSharedPreferences(PREFS_NAME, MODE_PRIVATE)
        return prefs.getBoolean(KEY_HAS_COMPLETED_ONBOARDING, false)
    }

    private fun markOnboardingComplete() {
        val prefs = getSharedPreferences(PREFS_NAME, MODE_PRIVATE)
        prefs.edit().putBoolean(KEY_HAS_COMPLETED_ONBOARDING, true).apply()
    }

    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        enableEdgeToEdge()
        binding = ActivityMainBinding.inflate(layoutInflater)
        setContentView(binding.root)

        setupWindowInsets()
        setupAnimations()
        observeViewModel()

        checkPermissions()

        // Only redirect to PermissionActivity if this is first launch and no permission
        if (!hasCompletedOnboarding() && !hasPermission()) {
            startActivity(Intent(this, PermissionActivity::class.java))
            finish()
        } else if (hasPermission()) {
            markOnboardingComplete()
        }

        binding.toggleContainer.setOnClickListener {
            openAppSettings()
        }
    }

    private fun setupWindowInsets() {
        ViewCompat.setOnApplyWindowInsetsListener(binding.root) { v, insets ->
            val systemBars = insets.getInsets(WindowInsetsCompat.Type.systemBars())
            v.setPadding(systemBars.left, systemBars.top, systemBars.right, systemBars.bottom)
            insets
        }
    }

    private fun observeViewModel() {
        lifecycleScope.launch {
            repeatOnLifecycle(Lifecycle.State.STARTED) {
                launch {
                    viewModel.totalScanned.collect { count ->
                        binding.tvScanned.text = formatNumber(count)
                    }
                }
                launch {
                    viewModel.phishingCount.collect { count ->
                        binding.tvThreats.text = count.toString()
                        updateAlertVisuals(count)
                        val hasPermission = ContextCompat.checkSelfPermission(
                            this@MainActivity,
                            Manifest.permission.RECEIVE_SMS
                        ) == PackageManager.PERMISSION_GRANTED
                        if (hasPermission) {
                            updateStatusColor(count)
                        }
                    }
                }
                launch {
                    viewModel.firstLaunchDate.collect { date ->
                        binding.tvActiveSince.text = getString(R.string.active_since, date)
                    }
                }
            }
        }
    }

    private fun updateStatusColor(threats: Int) {
        if (threats > 0) {
            binding.tvProtectionStatus.text = "OFF"
            binding.shieldGlow.setBackgroundResource(R.drawable.glow_alert)
        } else {
            binding.tvProtectionStatus.text = "ON"
            binding.shieldGlow.setBackgroundResource(R.drawable.shield_glow_new)
        }
    }

    private fun updateProtectionStatus(hasPermission: Boolean) {
        val margin4dp = (4 * resources.displayMetrics.density).toInt()
        if (hasPermission) {
            binding.tvProtectionStatus.text = "ON"
            binding.toggleContainer.setBackgroundResource(R.drawable.toggle_new_active)
            binding.toggleThumb.setBackgroundResource(R.drawable.toggle_thumb_new)
            (binding.toggleThumb.layoutParams as FrameLayout.LayoutParams).apply {
                gravity = android.view.Gravity.CENTER_VERTICAL or android.view.Gravity.END
                setMargins(0, 0, margin4dp, 0)
            }
            binding.toggleThumb.requestLayout()
            binding.ivShieldIcon.setImageResource(R.drawable.ic_verified_user)
            binding.ivShieldIcon.setColorFilter(0xFF4CAF50.toInt())
            binding.shieldCircle.setBackgroundResource(R.drawable.shield_circle_background_green)
        } else {
            binding.tvProtectionStatus.text = "OFF"
            binding.toggleContainer.setBackgroundResource(R.drawable.toggle_track)
            binding.toggleThumb.setBackgroundResource(R.drawable.toggle_thumb)
            (binding.toggleThumb.layoutParams as FrameLayout.LayoutParams).apply {
                gravity = android.view.Gravity.CENTER_VERTICAL or android.view.Gravity.START
                setMargins(margin4dp, 0, 0, 0)
            }
            binding.toggleThumb.requestLayout()
            binding.ivShieldIcon.setImageResource(R.drawable.ic_shield_off)
            binding.ivShieldIcon.setColorFilter(0xFFF44336.toInt())
            binding.shieldCircle.setBackgroundResource(R.drawable.shield_circle_background_red)
        }
    }

    private fun openAppSettings() {
        val intent = Intent(Settings.ACTION_APPLICATION_DETAILS_SETTINGS).apply {
            data = Uri.parse("package:$packageName")
            addFlags(Intent.FLAG_ACTIVITY_NEW_TASK)
        }
        startActivity(intent)
    }

    private fun hasPermission(): Boolean {
        return ContextCompat.checkSelfPermission(
            this,
            Manifest.permission.RECEIVE_SMS
        ) == PackageManager.PERMISSION_GRANTED
    }

    private fun checkPermissions() {
        updateProtectionStatus(hasPermission())
    }

    private fun setupAnimations() {
        binding.root.post {
            val pulseAnimation = AnimationUtils.loadAnimation(this@MainActivity, R.anim.pulse_animation)
            binding.shieldGlow.startAnimation(pulseAnimation)
        }
    }

    private fun formatNumber(number: Int): String {
        return String.format("%,d", number)
    }

    private fun updateAlertVisuals(threats: Int) {
        if (threats > 0) {
            binding.shieldGlow.setBackgroundResource(R.drawable.glow_alert)
        } else {
            binding.shieldGlow.setBackgroundResource(R.drawable.shield_glow_new)
        }
    }

    override fun onResume() {
        super.onResume()
        checkPermissions()
    }
}
