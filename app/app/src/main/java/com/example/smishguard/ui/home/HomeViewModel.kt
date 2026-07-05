package com.example.smishguard.ui.home

import androidx.lifecycle.ViewModel
import androidx.lifecycle.viewModelScope
import com.example.smishguard.data.storage.StatsStore
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.flow.SharingStarted
import kotlinx.coroutines.flow.StateFlow
import kotlinx.coroutines.flow.asStateFlow
import kotlinx.coroutines.flow.stateIn
import kotlinx.coroutines.launch
import java.text.SimpleDateFormat
import java.util.Date
import java.util.Locale

class HomeViewModel(
    private val statsStore: StatsStore
) : ViewModel() {

    val totalScanned: StateFlow<Int> = statsStore.totalScanned
        .stateIn(viewModelScope, SharingStarted.WhileSubscribed(5000), 0)

    val phishingCount: StateFlow<Int> = statsStore.totalPhishing
        .stateIn(viewModelScope, SharingStarted.WhileSubscribed(5000), 0)

    private val _protectionActive = MutableStateFlow(true)
    val protectionActive: StateFlow<Boolean> = _protectionActive.asStateFlow()

    private val _firstLaunchDate = MutableStateFlow("")
    val firstLaunchDate: StateFlow<String> = _firstLaunchDate.asStateFlow()

    init {
        viewModelScope.launch {
            _firstLaunchDate.value = formatDate(System.currentTimeMillis())
        }
    }

    private fun formatDate(timestamp: Long): String {
        val sdf = SimpleDateFormat("MMMM dd, yyyy", Locale.getDefault())
        return sdf.format(Date(timestamp))
    }
}
