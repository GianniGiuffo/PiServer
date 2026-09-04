package dev.jellyfin.phonerelay

import android.annotation.SuppressLint
import android.Manifest
import android.app.Activity
import android.content.ClipData
import android.content.ClipboardManager
import android.content.Intent
import android.content.pm.PackageManager
import android.graphics.Color
import android.graphics.Typeface
import android.graphics.drawable.GradientDrawable
import android.net.Uri
import android.os.Build
import android.os.Bundle
import android.provider.Settings
import android.text.InputType
import android.view.Gravity
import android.view.View
import android.widget.Button
import android.widget.EditText
import android.widget.LinearLayout
import android.widget.ScrollView
import android.widget.TextView
import android.widget.Toast
import dev.jellyfin.phonerelay.data.RelaySettings
import dev.jellyfin.phonerelay.diagnostics.RelayPhase
import dev.jellyfin.phonerelay.diagnostics.RelaySnapshot
import dev.jellyfin.phonerelay.network.JellyfinHealthChecker
import dev.jellyfin.phonerelay.relay.RelayService
import dev.jellyfin.phonerelay.relay.UrlMapper
import kotlinx.coroutines.CoroutineScope
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.SupervisorJob
import kotlinx.coroutines.cancel
import kotlinx.coroutines.launch
import kotlinx.coroutines.withContext
import java.util.Locale

@SuppressLint("SetTextI18n")
class MainActivity : Activity() {
    private val uiScope = CoroutineScope(SupervisorJob() + Dispatchers.Main)
    private lateinit var app: JprApplication

    private lateinit var upstreamInput: EditText
    private lateinit var portInput: EditText
    private lateinit var testButton: Button
    private lateinit var startButton: Button
    private lateinit var copyButton: Button
    private lateinit var stopButton: Button
    private lateinit var statusTitle: TextView
    private lateinit var statusMessage: TextView
    private lateinit var relayUrl: TextView
    private lateinit var connectivityText: TextView
    private lateinit var metricsText: TextView
    private lateinit var healthText: TextView
    private lateinit var logsText: TextView
    private lateinit var activePanel: LinearLayout

    private var pendingStart: RelaySettings? = null
    private val stateListener: (RelaySnapshot) -> Unit = { snapshot ->
        runOnUiThread { render(snapshot) }
    }

    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        app = application as JprApplication
        setContentView(buildContent())
        app.relayState.addListener(stateListener)
        uiScope.launch {
            val saved = withContext(Dispatchers.IO) { app.settingsRepository.load() }
            if (upstreamInput.text.isBlank()) upstreamInput.setText(saved.upstreamBaseUrl)
            if (portInput.text.isBlank()) portInput.setText(saved.localPort.toString())
        }
    }

    override fun onDestroy() {
        app.relayState.removeListener(stateListener)
        uiScope.cancel()
        super.onDestroy()
    }

    override fun onRequestPermissionsResult(requestCode: Int, permissions: Array<out String>, grantResults: IntArray) {
        super.onRequestPermissionsResult(requestCode, permissions, grantResults)
        if (requestCode == REQUEST_LOCAL_NETWORK) {
            if (grantResults.firstOrNull() == PackageManager.PERMISSION_GRANTED) {
                pendingStart?.let(::persistAndStart)
            } else {
                healthText.text = "Permesso rete locale negato. Apri le impostazioni dell’app per abilitarlo."
                healthText.setTextColor(Color.rgb(183, 28, 28))
                openAppSettings()
            }
            pendingStart = null
        }
    }

    private fun buildContent(): View {
        val scroll = ScrollView(this).apply { setBackgroundColor(Color.rgb(247, 247, 252)) }
        val root = LinearLayout(this).apply {
            orientation = LinearLayout.VERTICAL
            setPadding(dp(22), dp(24), dp(22), dp(32))
        }
        scroll.addView(root, LinearLayout.LayoutParams(MATCH, WRAP))

        root.addView(text("Jellyfin Phone Relay", 28f, Typeface.BOLD).apply {
            setTextColor(Color.rgb(48, 38, 91))
        })
        root.addView(text("Versione installata: ${installedVersionName()}", 12f, Typeface.BOLD).apply {
            setTextColor(Color.rgb(108, 85, 217))
            setPadding(0, dp(4), 0, 0)
        })
        root.addView(text("Porta Jellyfin sulla Fire TV, passando dal Tailscale del telefono.", 15f).apply {
            setTextColor(Color.DKGRAY)
            setPadding(0, dp(6), 0, dp(22))
        })

        root.addView(label("Server Jellyfin remoto"))
        upstreamInput = EditText(this).apply {
            hint = "http://100.x.y.z:8096"
            inputType = InputType.TYPE_CLASS_TEXT or InputType.TYPE_TEXT_VARIATION_URI
            isSingleLine = true
        }
        root.addView(upstreamInput, LinearLayout.LayoutParams(MATCH, WRAP))

        root.addView(label("Porta locale").apply { setPadding(0, dp(14), 0, 0) })
        portInput = EditText(this).apply {
            setText("8097")
            inputType = InputType.TYPE_CLASS_NUMBER
            isSingleLine = true
        }
        root.addView(portInput, LinearLayout.LayoutParams(MATCH, WRAP))

        testButton = Button(this).apply {
            text = "TEST SERVER"
            setOnClickListener { testServer() }
        }
        root.addView(testButton, marginParams(top = 18))

        healthText = text("Configura il server e verifica la connessione.", 14f).apply {
            setTextColor(Color.DKGRAY)
            setPadding(dp(2), dp(8), dp(2), dp(12))
        }
        root.addView(healthText)

        startButton = Button(this).apply {
            text = "AVVIA RELAY"
            setTextColor(Color.WHITE)
            background = rounded(Color.rgb(108, 85, 217), 12)
            setOnClickListener { startRelay() }
        }
        root.addView(startButton, marginParams(top = 4, height = 54))

        activePanel = LinearLayout(this).apply {
            orientation = LinearLayout.VERTICAL
            setPadding(dp(18), dp(18), dp(18), dp(18))
            background = rounded(Color.WHITE, 16, Color.rgb(224, 221, 241))
            visibility = View.GONE
        }
        root.addView(activePanel, marginParams(top = 22))

        statusTitle = text("STATO: FERMO", 17f, Typeface.BOLD)
        activePanel.addView(statusTitle)
        statusMessage = text("", 14f).apply { setPadding(0, dp(7), 0, dp(14)) }
        activePanel.addView(statusMessage)
        activePanel.addView(label("Fire TV deve usare"))
        relayUrl = text("—", 20f, Typeface.BOLD).apply {
            setTextColor(Color.rgb(76, 54, 181))
            setPadding(0, dp(5), 0, dp(12))
            setTextIsSelectable(true)
        }
        activePanel.addView(relayUrl)
        connectivityText = text("Wi-Fi: —\nServer Jellyfin: —", 14f)
        activePanel.addView(connectivityText)
        metricsText = text("", 14f).apply { setPadding(0, dp(10), 0, dp(12)) }
        activePanel.addView(metricsText)

        copyButton = Button(this).apply {
            text = "COPIA INDIRIZZO"
            setOnClickListener { copyRelayAddress() }
        }
        activePanel.addView(copyButton, LinearLayout.LayoutParams(MATCH, WRAP))
        stopButton = Button(this).apply {
            text = "STOP RELAY"
            setTextColor(Color.rgb(183, 28, 28))
            setOnClickListener { RelayService.stop(this@MainActivity) }
        }
        activePanel.addView(stopButton, LinearLayout.LayoutParams(MATCH, WRAP))

        root.addView(label("Diagnostica").apply { setPadding(0, dp(24), 0, dp(6)) })
        logsText = text("Nessun evento.", 12f).apply {
            typeface = Typeface.MONOSPACE
            setTextColor(Color.DKGRAY)
            setTextIsSelectable(true)
            setPadding(dp(14), dp(12), dp(14), dp(12))
            background = rounded(Color.rgb(238, 238, 246), 10)
        }
        root.addView(logsText, LinearLayout.LayoutParams(MATCH, WRAP))
        root.addView(Button(this).apply {
            text = "COPIA LOG REDATTO"
            setOnClickListener { copyLogs() }
        }, marginParams(top = 6))

        root.addView(text("Usa il relay solo su reti Wi-Fi fidate. Il collegamento Fire TV → telefono usa HTTP locale. Evita un account Jellyfin amministratore.", 13f).apply {
            setTextColor(Color.rgb(121, 77, 0))
            setPadding(dp(14), dp(14), dp(14), dp(14))
            background = rounded(Color.rgb(255, 248, 225), 12)
        }, marginParams(top = 20))
        return scroll
    }

    private fun testServer() {
        val settings = validatedSettings() ?: return
        val upstream = UrlMapper.normalizeBaseUrl(settings.upstreamBaseUrl) ?: return
        testButton.isEnabled = false
        healthText.text = "Connessione al server…"
        healthText.setTextColor(Color.DKGRAY)
        uiScope.launch {
            val result = withContext(Dispatchers.IO) { JellyfinHealthChecker().check(upstream) }
            healthText.text = result.message
            healthText.setTextColor(if (result.success) Color.rgb(27, 124, 74) else Color.rgb(183, 28, 28))
            testButton.isEnabled = true
            withContext(Dispatchers.IO) {
                if (result.success) app.settingsRepository.markWorking(settings)
                else app.settingsRepository.save(settings)
            }
        }
    }

    private fun startRelay() {
        val settings = validatedSettings() ?: return
        if (!hasLocalNetworkPermission()) {
            pendingStart = settings
            requestPermissions(arrayOf(LOCAL_NETWORK_PERMISSION), REQUEST_LOCAL_NETWORK)
            return
        }
        requestNotificationPermissionIfNeeded()
        persistAndStart(settings)
    }

    private fun persistAndStart(settings: RelaySettings) {
        uiScope.launch {
            withContext(Dispatchers.IO) { app.settingsRepository.save(settings) }
            RelayService.start(this@MainActivity, settings.upstreamBaseUrl, settings.localPort)
        }
    }

    private fun validatedSettings(): RelaySettings? {
        val upstream = upstreamInput.text.toString().trim()
        val port = portInput.text.toString().toIntOrNull()
        if (UrlMapper.normalizeBaseUrl(upstream) == null) {
            upstreamInput.error = "Inserisci un URL http:// o https:// valido, senza query"
            return null
        }
        if (port == null || port !in 1024..65535) {
            portInput.error = "Usa una porta tra 1024 e 65535"
            return null
        }
        return RelaySettings(upstream, port)
    }

    private fun render(snapshot: RelaySnapshot) {
        val isStopped = snapshot.phase == RelayPhase.STOPPED
        val isRunning = snapshot.phase == RelayPhase.RUNNING
        upstreamInput.isEnabled = isStopped
        portInput.isEnabled = isStopped
        testButton.isEnabled = isStopped
        startButton.visibility = if (isStopped) View.VISIBLE else View.GONE
        activePanel.visibility = if (isStopped) View.GONE else View.VISIBLE

        statusTitle.text = "STATO: ${snapshot.phase.name}"
        statusTitle.setTextColor(
            when (snapshot.phase) {
                RelayPhase.RUNNING -> Color.rgb(27, 124, 74)
                RelayPhase.ERROR -> Color.rgb(183, 28, 28)
                else -> Color.rgb(76, 54, 181)
            },
        )
        statusMessage.text = snapshot.message
        relayUrl.text = snapshot.relayUrl.ifBlank { "In attesa del Wi-Fi…" }
        copyButton.isEnabled = snapshot.relayUrl.isNotBlank()
        connectivityText.text = buildString {
            append("Wi-Fi: ").append(if (snapshot.wifiConnected) "connesso" else "non disponibile")
            append("\nServer Jellyfin: ").append(
                when (snapshot.upstreamReachable) {
                    true -> "raggiungibile"
                    false -> "non raggiungibile"
                    null -> "verifica in corso"
                },
            )
        }
        metricsText.text = buildString {
            append("Richieste HTTP attive: ").append(snapshot.activeHttp)
            append("\nWebSocket attivi: ").append(snapshot.activeWebSockets)
            append("\nRX Tailscale: ").append(String.format(Locale.ITALY, "%.1f Mbps", snapshot.upstreamMbps))
            append("\nTX LAN: ").append(String.format(Locale.ITALY, "%.1f Mbps", snapshot.downstreamMbps))
            append("\nDati trasferiti: ").append(formatBytes(snapshot.transferredBytes))
            append("\nUptime: ").append(formatDuration(snapshot.uptimeMillis))
        }
        logsText.text = snapshot.logs.takeLast(20).joinToString("\n").ifBlank { "Nessun evento." }
        if (isRunning && healthText.text.isBlank()) healthText.text = "Relay attivo"
    }

    private fun copyRelayAddress() {
        val address = app.relayState.snapshot().relayUrl
        if (address.isBlank()) return
        clipboard().setPrimaryClip(ClipData.newPlainText("Indirizzo Jellyfin Relay", address))
        Toast.makeText(this, "Indirizzo copiato", Toast.LENGTH_SHORT).show()
    }

    private fun copyLogs() {
        val logs = app.relayState.snapshot().logs.joinToString("\n")
        clipboard().setPrimaryClip(ClipData.newPlainText("Log JPR redatto", logs))
        Toast.makeText(this, "Log redatto copiato", Toast.LENGTH_SHORT).show()
    }

    private fun clipboard(): ClipboardManager = getSystemService(ClipboardManager::class.java)

    @Suppress("DEPRECATION")
    private fun installedVersionName(): String =
        packageManager.getPackageInfo(packageName, 0).versionName ?: "sconosciuta"

    private fun hasLocalNetworkPermission(): Boolean {
        val targetsAndroid17 = applicationInfo.targetSdkVersion >= 37 && Build.VERSION.SDK_INT >= 37
        return !targetsAndroid17 || checkSelfPermission(LOCAL_NETWORK_PERMISSION) == PackageManager.PERMISSION_GRANTED
    }

    private fun requestNotificationPermissionIfNeeded() {
        if (Build.VERSION.SDK_INT >= 33 && checkSelfPermission(Manifest.permission.POST_NOTIFICATIONS) != PackageManager.PERMISSION_GRANTED) {
            requestPermissions(arrayOf(Manifest.permission.POST_NOTIFICATIONS), REQUEST_NOTIFICATIONS)
        }
    }

    private fun openAppSettings() {
        startActivity(
            Intent(Settings.ACTION_APPLICATION_DETAILS_SETTINGS).apply {
                data = Uri.fromParts("package", packageName, null)
            },
        )
    }

    private fun label(value: String): TextView = text(value, 13f, Typeface.BOLD).apply {
        setTextColor(Color.rgb(70, 70, 82))
    }

    private fun text(value: String, size: Float, style: Int = Typeface.NORMAL): TextView = TextView(this).apply {
        text = value
        textSize = size
        setTypeface(typeface, style)
        gravity = Gravity.START
    }

    private fun rounded(fill: Int, radiusDp: Int, stroke: Int? = null): GradientDrawable = GradientDrawable().apply {
        shape = GradientDrawable.RECTANGLE
        setColor(fill)
        cornerRadius = dp(radiusDp).toFloat()
        if (stroke != null) setStroke(dp(1), stroke)
    }

    private fun marginParams(top: Int = 0, height: Int = WRAP): LinearLayout.LayoutParams =
        LinearLayout.LayoutParams(MATCH, if (height == WRAP) WRAP else dp(height)).apply {
            topMargin = dp(top)
        }

    private fun dp(value: Int): Int = (value * resources.displayMetrics.density).toInt()

    private fun formatBytes(bytes: Long): String {
        val units = arrayOf("B", "KiB", "MiB", "GiB", "TiB")
        var value = bytes.toDouble()
        var unit = 0
        while (value >= 1024 && unit < units.lastIndex) {
            value /= 1024
            unit++
        }
        return String.format(Locale.ITALY, if (unit == 0) "%.0f %s" else "%.1f %s", value, units[unit])
    }

    private fun formatDuration(milliseconds: Long): String {
        val seconds = milliseconds / 1000
        return "%02d:%02d:%02d".format(seconds / 3600, (seconds / 60) % 60, seconds % 60)
    }

    private companion object {
        const val LOCAL_NETWORK_PERMISSION = "android.permission.ACCESS_LOCAL_NETWORK"
        const val REQUEST_LOCAL_NETWORK = 37
        const val REQUEST_NOTIFICATIONS = 33
        const val MATCH = LinearLayout.LayoutParams.MATCH_PARENT
        const val WRAP = LinearLayout.LayoutParams.WRAP_CONTENT
    }
}
