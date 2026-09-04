package dev.jellyfin.phonerelay.diagnostics

object Redactor {
    private val sensitiveQuery = Regex(
        "(?i)([?&](?:api_key|apikey|token|access_token|x-emby-token)=)[^&#\\s]*",
    )
    private val sensitiveHeader = Regex(
        "(?i)(Authorization|X-Emby-Authorization|X-Emby-Token)\\s*[:=]\\s*[^,\\r\\n]*",
    )

    fun redact(value: String): String = value
        .replace(sensitiveQuery) { "${it.groupValues[1]}<REDACTED>" }
        .replace(sensitiveHeader) { "${it.groupValues[1]}=<REDACTED>" }

    fun safePath(path: String): String = redact(path.substringBefore('?'))
}
