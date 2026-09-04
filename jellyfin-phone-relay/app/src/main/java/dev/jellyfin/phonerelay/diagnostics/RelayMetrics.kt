package dev.jellyfin.phonerelay.diagnostics

import java.util.concurrent.atomic.AtomicInteger
import java.util.concurrent.atomic.AtomicLong

class RelayMetrics {
    val activeHttp = AtomicInteger()
    val activeWebSockets = AtomicInteger()
    val totalHttp = AtomicLong()
    val upstreamErrors = AtomicLong()
    val upstreamToDownstreamBytes = AtomicLong()
    val downstreamToUpstreamBytes = AtomicLong()

    private val startedAt = AtomicLong(System.currentTimeMillis())
    private var sampledAt = System.currentTimeMillis()
    private var sampledRx = 0L
    private var sampledTx = 0L

    fun reset() {
        activeHttp.set(0)
        activeWebSockets.set(0)
        totalHttp.set(0)
        upstreamErrors.set(0)
        upstreamToDownstreamBytes.set(0)
        downstreamToUpstreamBytes.set(0)
        startedAt.set(System.currentTimeMillis())
        synchronized(this) {
            sampledAt = System.currentTimeMillis()
            sampledRx = 0
            sampledTx = 0
        }
    }

    @Synchronized
    fun sample(): MetricsSample {
        val now = System.currentTimeMillis()
        val rx = upstreamToDownstreamBytes.get()
        val tx = downstreamToUpstreamBytes.get()
        val elapsedSeconds = ((now - sampledAt).coerceAtLeast(1)) / 1000.0
        val result = MetricsSample(
            activeHttp = activeHttp.get(),
            activeWebSockets = activeWebSockets.get(),
            rxMbps = ((rx - sampledRx).coerceAtLeast(0) * 8.0) / elapsedSeconds / 1_000_000.0,
            txMbps = ((tx - sampledTx).coerceAtLeast(0) * 8.0) / elapsedSeconds / 1_000_000.0,
            totalBytes = rx + tx,
            uptimeMillis = (now - startedAt.get()).coerceAtLeast(0),
        )
        sampledAt = now
        sampledRx = rx
        sampledTx = tx
        return result
    }
}

data class MetricsSample(
    val activeHttp: Int,
    val activeWebSockets: Int,
    val rxMbps: Double,
    val txMbps: Double,
    val totalBytes: Long,
    val uptimeMillis: Long,
)
