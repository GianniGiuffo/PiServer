package dev.jellyfin.phonerelay.relay

object HeaderSanitizer {
    private val hopByHop = setOf(
        "connection",
        "keep-alive",
        "proxy-authenticate",
        "proxy-authorization",
        "te",
        "trailer",
        "transfer-encoding",
        "upgrade",
    )

    private val webSocketGenerated = setOf(
        "sec-websocket-key",
        "sec-websocket-version",
        "sec-websocket-extensions",
    )

    fun requestHeaders(headers: Map<String, String>, webSocket: Boolean = false): List<Pair<String, String>> {
        val connectionTokens = connectionTokens(headers)
        return headers.mapNotNull { (name, value) ->
            val lower = name.lowercase()
            val skip = lower == "host" ||
                lower == "content-length" ||
                lower in hopByHop ||
                lower in connectionTokens ||
                (webSocket && lower in webSocketGenerated)
            if (skip) null else name to value
        }
    }

    fun responseHeaders(headers: Iterable<Pair<String, String>>): List<Pair<String, String>> {
        val materialized = headers.toList()
        val connectionTokens = materialized
            .filter { it.first.equals("connection", ignoreCase = true) }
            .flatMap { it.second.split(',') }
            .map { it.trim().lowercase() }
            .filter { it.isNotEmpty() }
            .toSet()
        return materialized.filterNot { (name, _) ->
            val lower = name.lowercase()
            lower == "content-length" ||
                lower == "content-type" ||
                lower in hopByHop ||
                lower in connectionTokens
        }
    }

    private fun connectionTokens(headers: Map<String, String>): Set<String> = headers.entries
        .firstOrNull { it.key.equals("connection", ignoreCase = true) }
        ?.value
        ?.split(',')
        ?.map { it.trim().lowercase() }
        ?.filter { it.isNotEmpty() }
        ?.toSet()
        .orEmpty()
}
