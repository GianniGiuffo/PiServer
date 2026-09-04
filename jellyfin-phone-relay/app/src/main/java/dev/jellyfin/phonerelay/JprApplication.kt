package dev.jellyfin.phonerelay

import android.app.Application
import dev.jellyfin.phonerelay.data.SettingsRepository
import dev.jellyfin.phonerelay.diagnostics.RelayStateStore

class JprApplication : Application() {
    lateinit var settingsRepository: SettingsRepository
        private set

    val relayState = RelayStateStore()

    override fun onCreate() {
        super.onCreate()
        settingsRepository = SettingsRepository(this)
    }
}
