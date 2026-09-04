package dev.jellyfin.phonerelay.relay

import android.app.Notification
import android.app.NotificationChannel
import android.app.NotificationManager
import android.app.PendingIntent
import android.app.Service
import android.content.Context
import android.content.Intent
import android.content.pm.ServiceInfo
import android.os.Build
import android.os.IBinder
import android.os.PowerManager
import dev.jellyfin.phonerelay.JprApplication
import dev.jellyfin.phonerelay.MainActivity
import dev.jellyfin.phonerelay.R
import dev.jellyfin.phonerelay.data.RelaySettings
import dev.jellyfin.phonerelay.diagnostics.RelayMetrics
import dev.jellyfin.phonerelay.diagnostics.RelayLogger
import dev.jellyfin.phonerelay.diagnostics.RelayPhase
import dev.jellyfin.phonerelay.diagnostics.RelayStateStore
import dev.jellyfin.phonerelay.diagnostics.SafeLogger
import dev.jellyfin.phonerelay.network.JellyfinHealthChecker
import dev.jellyfin.phonerelay.network.WifiNetworkMonitor
import kotlinx.coroutines.CoroutineScope
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.Job
import kotlinx.coroutines.SupervisorJob
import kotlinx.coroutines.cancel
import kotlinx.coroutines.delay
import kotlinx.coroutines.launch
import kotlinx.coroutines.sync.Mutex
import kotlinx.coroutines.sync.withLock
import okhttp3.HttpUrl

class RelayService : Service() {
    private val scope = CoroutineScope(SupervisorJob() + Dispatchers.IO)
    private val lifecycleMutex = Mutex()
    private val metrics = RelayMetrics()

    private lateinit var app: JprApplication
    private lateinit var stateStore: RelayStateStore
    private lateinit var logger: RelayLogger
    private lateinit var wifiMonitor: WifiNetworkMonitor
    private lateinit var wakeLock: PowerManager.WakeLock

    private var server: LocalProxyServer? = null
    private var upstream: HttpUrl? = null
    private var configuredPort = 8097
    private var boundAddress: String? = null
    private var metricsJob: Job? = null
    private var stopping = false

    override fun onCreate() {
        super.onCreate()
        app = application as JprApplication
        stateStore = app.relayState
        logger = SafeLogger(stateStore)
        wifiMonitor = WifiNetworkMonitor(this)
        wakeLock = getSystemService(PowerManager::class.java)
            .newWakeLock(PowerManager.PARTIAL_WAKE_LOCK, "JPR::RelayWakeLock")
            .apply { setReferenceCounted(false) }
        createNotificationChannel()
    }

    override fun onStartCommand(intent: Intent?, flags: Int, startId: Int): Int {
        if (intent?.action == ACTION_STOP) {
            stopRelayAndSelf()
            return START_NOT_STICKY
        }

        startAsForeground(buildNotification("Avvio relay…"))
        val requestedUrl = intent?.getStringExtra(EXTRA_UPSTREAM)
        val requestedPort = intent?.getIntExtra(EXTRA_PORT, 8097)
        scope.launch {
            val stored = app.settingsRepository.load()
            val url = requestedUrl ?: stored.upstreamBaseUrl
            val port = requestedPort ?: stored.localPort
            startRelay(url, port)
        }
        return START_NOT_STICKY
    }

    override fun onBind(intent: Intent?): IBinder? = null

    override fun onDestroy() {
        stopping = true
        wifiMonitor.stop()
        metricsJob?.cancel()
        server?.stop()
        server = null
        releaseWakeLock()
        stateStore.update {
            it.copy(
                phase = RelayPhase.STOPPED,
                relayUrl = "",
                wifiConnected = false,
                activeHttp = 0,
                activeWebSockets = 0,
                upstreamMbps = 0.0,
                downstreamMbps = 0.0,
                message = "Relay fermo",
            )
        }
        scope.cancel()
        super.onDestroy()
    }

    private suspend fun startRelay(urlText: String, port: Int): Unit = lifecycleMutex.withLock {
        stopping = false
        val parsed = UrlMapper.normalizeBaseUrl(urlText)
        if (parsed == null || port !in 1024..65535) {
            stateStore.update {
                it.copy(phase = RelayPhase.ERROR, message = "Configurazione non valida")
            }
            logger.error("Impossibile avviare: URL o porta non validi")
            stopForeground(STOP_FOREGROUND_REMOVE)
            stopSelf()
            return@withLock
        }

        server?.stop()
        metrics.reset()
        upstream = parsed
        configuredPort = port
        stateStore.update {
            it.copy(
                phase = RelayPhase.STARTING,
                upstream = parsed.toString().trimEnd('/'),
                relayUrl = "",
                upstreamReachable = null,
                message = "Ricerca della rete Wi-Fi…",
                logs = emptyList(),
            )
        }
        acquireWakeLock()
        startMetricsLoop()
        wifiMonitor.stop()
        wifiMonitor.start { address ->
            scope.launch { handleWifiAddress(address) }
        }
        scope.launch { checkUpstream(parsed) }
    }

    private suspend fun handleWifiAddress(address: String?) = lifecycleMutex.withLock {
        if (stopping || upstream == null || address == boundAddress && server != null) return

        val oldAddress = boundAddress
        server?.stop()
        server = null
        boundAddress = address
        if (address == null) {
            stateStore.update {
                it.copy(
                    phase = RelayPhase.ERROR,
                    relayUrl = "",
                    wifiConnected = false,
                    message = "Nessun IPv4 Wi-Fi locale valido. Gli indirizzi Tailscale non vengono usati per il relay LAN.",
                )
            }
            updateNotification("Wi-Fi non connesso")
            logger.warn("Listener sospeso: nessun IPv4 Wi-Fi locale non-VPN")
            return
        }

        val currentUpstream = upstream ?: return
        val origin = "http://$address:$configuredPort"
        try {
            val newServer = LocalProxyServer(
                hostname = address,
                port = configuredPort,
                upstream = currentUpstream,
                relayOrigin = origin,
                metrics = metrics,
                logger = logger,
            )
            newServer.start(0, false)
            server = newServer
            val networkChanged = oldAddress != null && oldAddress != address
            stateStore.update {
                it.copy(
                    phase = RelayPhase.RUNNING,
                    relayUrl = origin,
                    wifiConnected = true,
                    message = if (networkChanged) {
                        "La rete è cambiata. Aggiorna l’indirizzo sulla Fire TV: $origin"
                    } else {
                        "Relay attivo. Inserisci questo indirizzo in Jellyfin Android TV."
                    },
                )
            }
            logger.info("Relay avviato su $address:$configuredPort")
            updateNotification("Fire TV → Jellyfin · $origin")
        } catch (error: Exception) {
            stateStore.update {
                it.copy(
                    phase = RelayPhase.ERROR,
                    relayUrl = "",
                    wifiConnected = true,
                    message = "Impossibile aprire $address:$configuredPort: ${error.message.orEmpty()}",
                )
            }
            logger.error("Binding locale fallito su $address:$configuredPort", error)
            updateNotification("Errore listener sulla porta $configuredPort")
        }
    }

    private suspend fun checkUpstream(target: HttpUrl) {
        val result = JellyfinHealthChecker().check(target)
        stateStore.update { it.copy(upstreamReachable = result.success) }
        if (result.success) {
            logger.info(result.message)
            app.settingsRepository.markWorking(
                RelaySettings(target.toString().trimEnd('/'), configuredPort),
            )
        } else {
            logger.warn(result.message)
        }
    }

    private fun startMetricsLoop() {
        metricsJob?.cancel()
        metricsJob = scope.launch {
            while (true) {
                delay(1_000)
                acquireWakeLock()
                val sample = metrics.sample()
                stateStore.update {
                    it.copy(
                        activeHttp = sample.activeHttp,
                        activeWebSockets = sample.activeWebSockets,
                        upstreamMbps = sample.rxMbps,
                        downstreamMbps = sample.txMbps,
                        transferredBytes = sample.totalBytes,
                        uptimeMillis = sample.uptimeMillis,
                    )
                }
                if (sample.uptimeMillis % 5_000L < 1_100L) {
                    updateNotification(
                        "${sample.activeHttp} HTTP · ${sample.activeWebSockets} WS · ${"%.1f".format(sample.rxMbps)} Mbps",
                    )
                }
            }
        }
    }

    private fun stopRelayAndSelf() {
        if (stopping) return
        stopping = true
        scope.launch {
            lifecycleMutex.withLock {
                wifiMonitor.stop()
                metricsJob?.cancel()
                server?.stop()
                server = null
                upstream = null
                boundAddress = null
                releaseWakeLock()
            }
            logger.info("Relay arrestato dall’utente")
            stopForeground(STOP_FOREGROUND_REMOVE)
            stopSelf()
        }
    }

    private fun acquireWakeLock() {
        if (!wakeLock.isHeld) wakeLock.acquire(WAKE_LOCK_TIMEOUT_MS)
    }

    private fun releaseWakeLock() {
        if (wakeLock.isHeld) wakeLock.release()
    }

    private fun startAsForeground(notification: Notification) {
        if (Build.VERSION.SDK_INT >= 34) {
            startForeground(NOTIFICATION_ID, notification, ServiceInfo.FOREGROUND_SERVICE_TYPE_SPECIAL_USE)
        } else {
            startForeground(NOTIFICATION_ID, notification)
        }
    }

    private fun updateNotification(text: String) {
        getSystemService(NotificationManager::class.java).notify(NOTIFICATION_ID, buildNotification(text))
    }

    private fun buildNotification(text: String): Notification {
        val openIntent = PendingIntent.getActivity(
            this,
            0,
            Intent(this, MainActivity::class.java),
            PendingIntent.FLAG_UPDATE_CURRENT or PendingIntent.FLAG_IMMUTABLE,
        )
        val stopIntent = PendingIntent.getService(
            this,
            1,
            Intent(this, RelayService::class.java).setAction(ACTION_STOP),
            PendingIntent.FLAG_UPDATE_CURRENT or PendingIntent.FLAG_IMMUTABLE,
        )
        return Notification.Builder(this, CHANNEL_ID)
            .setSmallIcon(R.drawable.ic_relay)
            .setContentTitle("Jellyfin Relay attivo")
            .setContentText(text)
            .setContentIntent(openIntent)
            .setOngoing(true)
            .setOnlyAlertOnce(true)
            .addAction(Notification.Action.Builder(null, "STOP", stopIntent).build())
            .build()
    }

    private fun createNotificationChannel() {
        val channel = NotificationChannel(
            CHANNEL_ID,
            getString(R.string.notification_channel_name),
            NotificationManager.IMPORTANCE_LOW,
        ).apply {
            description = getString(R.string.notification_channel_description)
            setShowBadge(false)
        }
        getSystemService(NotificationManager::class.java).createNotificationChannel(channel)
    }

    companion object {
        const val ACTION_START = "dev.jellyfin.phonerelay.action.START"
        const val ACTION_STOP = "dev.jellyfin.phonerelay.action.STOP"
        const val EXTRA_UPSTREAM = "upstream"
        const val EXTRA_PORT = "port"

        private const val CHANNEL_ID = "jpr_relay"
        private const val NOTIFICATION_ID = 8097
        private const val WAKE_LOCK_TIMEOUT_MS = 6L * 60L * 60L * 1_000L

        fun start(context: Context, upstream: String, port: Int) {
            val intent = Intent(context, RelayService::class.java)
                .setAction(ACTION_START)
                .putExtra(EXTRA_UPSTREAM, upstream)
                .putExtra(EXTRA_PORT, port)
            context.startForegroundService(intent)
        }

        fun stop(context: Context) {
            context.startService(Intent(context, RelayService::class.java).setAction(ACTION_STOP))
        }
    }
}
