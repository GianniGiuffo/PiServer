package dev.jellyfin.phonerelay.relay

import okhttp3.HttpUrl
import okhttp3.HttpUrl.Companion.toHttpUrlOrNull

object UrlMapper {
    fun normalizeBaseUrl(value: String): HttpUrl? {
        val candidate = value.trim().trimEnd('/')
        val parsed = candidate.toHttpUrlOrNull() ?: return null
        if (parsed.scheme != "http" && parsed.scheme != "https") return null
        if (parsed.query != null || parsed.fragment != null) return null
        return parsed
    }

    fun mapHttp(base: HttpUrl, encodedPath: String, rawQuery: String?): HttpUrl {
        val basePath = base.encodedPath.trimEnd('/').takeUnless { it == "/" }.orEmpty()
        val downstreamPath = "/" + encodedPath.trimStart('/')
        return base.newBuilder()
            .encodedPath(basePath + downstreamPath)
            .encodedQuery(rawQuery)
            .fragment(null)
            .build()
    }

    fun mapWebSocket(base: HttpUrl, encodedPath: String, rawQuery: String?): HttpUrl {
        // OkHttp's WebSocket API intentionally receives an HTTP(S) Request and
        // performs the Upgrade itself; TLS HTTP becomes WSS on the wire.
        return mapHttp(base, encodedPath, rawQuery)
    }

    fun origin(url: HttpUrl): String {
        val defaultPort = if (url.isHttps) 443 else 80
        val port = if (url.port == defaultPort) "" else ":${url.port}"
        return "${url.scheme}://${url.host}$port"
    }
}
