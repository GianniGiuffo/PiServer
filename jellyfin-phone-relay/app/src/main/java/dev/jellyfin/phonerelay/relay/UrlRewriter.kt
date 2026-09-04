package dev.jellyfin.phonerelay.relay

import okhttp3.HttpUrl
import java.net.URI

object UrlRewriter {
    const val MAX_REWRITE_BYTES = 4L * 1024L * 1024L

    fun rewriteLocation(location: String, upstream: HttpUrl, relayOrigin: String): String {
        val target = runCatching { URI(location) }.getOrNull() ?: return location
        if (!target.isAbsolute || !sameOrigin(target, upstream)) return location
        val suffix = buildString {
            append(target.rawPath?.ifEmpty { "/" } ?: "/")
            target.rawQuery?.let { append('?').append(it) }
            target.rawFragment?.let { append('#').append(it) }
        }
        return relayOrigin.trimEnd('/') + suffix
    }

    fun rewritePlaylist(text: String, upstream: HttpUrl, relayOrigin: String): String {
        val upstreamOrigin = UrlMapper.origin(upstream)
        return text.replace(upstreamOrigin, relayOrigin.trimEnd('/'))
    }

    fun isPlaylist(contentType: String?, path: String): Boolean {
        val mediaType = contentType?.substringBefore(';')?.trim()?.lowercase()
        return path.substringBefore('?').lowercase().endsWith(".m3u8") ||
            mediaType == "application/vnd.apple.mpegurl" ||
            mediaType == "application/x-mpegurl" ||
            mediaType == "audio/mpegurl"
    }

    private fun sameOrigin(target: URI, upstream: HttpUrl): Boolean {
        val targetPort = when {
            target.port >= 0 -> target.port
            target.scheme.equals("https", true) -> 443
            else -> 80
        }
        return target.scheme.equals(upstream.scheme, true) &&
            target.host.equals(upstream.host, true) &&
            targetPort == upstream.port
    }
}
