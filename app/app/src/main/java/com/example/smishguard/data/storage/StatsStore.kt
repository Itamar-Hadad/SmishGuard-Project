package com.example.smishguard.data.storage

import android.content.Context
import androidx.datastore.core.DataStore
import androidx.datastore.preferences.core.Preferences
import androidx.datastore.preferences.core.edit
import androidx.datastore.preferences.core.intPreferencesKey
import androidx.datastore.preferences.preferencesDataStore
import kotlinx.coroutines.flow.Flow
import kotlinx.coroutines.flow.map

val Context.dataStore: DataStore<Preferences> by preferencesDataStore(name = "stats")

object StatsKeys {
    val TOTAL_SCANNED = intPreferencesKey("total_scanned")
    val TOTAL_PHISHING = intPreferencesKey("total_phishing")
}

class StatsStore(context: Context) {
    private val dataStore = context.dataStore

    val totalScanned: Flow<Int> = dataStore.data.map { it[StatsKeys.TOTAL_SCANNED] ?: 0 }
    val totalPhishing: Flow<Int> = dataStore.data.map { it[StatsKeys.TOTAL_PHISHING] ?: 0 }

    suspend fun incrementScanned() {
        dataStore.edit { preferences ->
            val current = preferences[StatsKeys.TOTAL_SCANNED] ?: 0
            preferences[StatsKeys.TOTAL_SCANNED] = current + 1
        }
    }

    suspend fun incrementPhishing() {
        dataStore.edit { preferences ->
            val current = preferences[StatsKeys.TOTAL_PHISHING] ?: 0
            preferences[StatsKeys.TOTAL_PHISHING] = current + 1
        }
    }
}
