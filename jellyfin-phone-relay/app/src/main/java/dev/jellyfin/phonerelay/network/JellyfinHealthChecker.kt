package dev.jellyfin.phonerelay.network

import dev.jellyfin.phonerelay.relay.UrlMapper
import okhttp3.HttpUrl
import okhttp3.OkHttpClient
import okhttp3.Request
import java.net.ConnectException
import java.net.NoRouteToHostException
import java.net.SocketTimeoutException
import java.net.UnknownHostException
import java.util.concurrent.TimeUnit
import javax.net.ssl.SSLException

class JellyfinHealthChecker {
    private val client = OkHttpClient.Builder()
        .connectTimeout(12, TimeUnit.SECONDS)
        .readTimeout(15, TimeUnit.SECONDS)
        .callTimeout(20, TimeUnit.SECONDS)
        .followRedirects(true)
        .build()

    fun check(upstream: HttpUrl): HealthResult {
        val startedAt = System.nanoTime()
        return try {
            val url = UrlMapper.mapHttp(upstream, "/System/Info/Public", null)
            client.newCall(Request.Builder().url(url).get().build()).execute().use { response ->
                val latency = TimeUnit.NANOSECONDS.toMillis(System.nanoTime() - startedAt)
                if (!response.isSuccessful) {
                    return HealthResult(false, "HTTP non valido: ${response.code}", latencyMillis = latency)
                }
                val payload = response.body?.string().orEmpty()
                val version = VERSION_REGEX.find(payload)?.groupValues?.get(1)
                val looksLikeJellyfin = version != null ||
                    payload.contains("Jellyfin", ignoreCase = true) ||
                    payload.contains("ServerName", ignoreCase = true)
                if (!looksLikeJellyfin) {
                    HealthResult(false, "Risposta non riconosciuta come Jellyfin", latencyMillis = latency)
                } else {
                    HealthResult(
                        success = true,
                        message = buildString {
                            append("Server Jellyfin raggiungibile")
                            version?.let { append(" · versione ").append(it) }
                            append(" · ").append(latency).append(" ms")
                        },
                        version = version,
                        latencyMillis = latency,
                    )
                }
            }
        } catch (_: UnknownHostException) {
            HealthResult(false, "DNS non risolto")
        } catch (_: ConnectException) {
            HealthResult(false, "Connessione rifiutata")
        } catch (_: SocketTimeoutException) {
            HealthResult(false, "Timeout verso il server")
        } catch (_: SSLException) {
            HealthResult(false, "Errore TLS: certificato o configurazione HTTPS non validi")
        } catch (_: NoRouteToHostException) {
            HealthResult(false, "Nessuna route: Tailscale potrebbe essere disattivato")
        } catch (error: Exception) {
            val text = error.message.orEmpty().lowercase()
            val message = if ("route" in text || "unreachable" in text) {
                "Nessuna route: Tailscale potrebbe essere disattivato"
            } else {
                "Server non raggiungibile (${error.javaClass.simpleName})"
            }
            HealthResult(false, message)
        }
    }

    data class HealthResult(
        val success: Boolean,
        val message: String,
        val version: String? = null,
        val latencyMillis: Long? = null,
    )

    private companion object {
        val VERSION_REGEX = Regex("\\\"Version\\\"\\s*:\\s*\\\"([^\\\"]+)\\\"", RegexOption.IGNORE_CASE)
    }
}
