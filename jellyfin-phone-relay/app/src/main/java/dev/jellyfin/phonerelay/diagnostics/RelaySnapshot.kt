package dev.jellyfin.phonerelay.diagnostics

enum class RelayPhase {
    STOPPED,
    STARTING,
    RUNNING,
    ERROR,
}

data class RelaySnapshot(
    val phase: RelayPhase = RelayPhase.STOPPED,
    val upstream: String = "",
    val relayUrl: String = "",
    val wifiConnected: Boolean = false,
    val upstreamReachable: Boolean? = null,
    val activeHttp: Int = 0,
    val activeWebSockets: Int = 0,
    val upstreamMbps: Double = 0.0,
    val downstreamMbps: Double = 0.0,
    val transferredBytes: Long = 0,
    val uptimeMillis: Long = 0,
    val message: String = "Relay fermo",
    val logs: List<String> = emptyList(),
)
