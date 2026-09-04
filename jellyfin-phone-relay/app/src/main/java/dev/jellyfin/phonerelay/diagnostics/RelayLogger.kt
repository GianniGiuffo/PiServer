package dev.jellyfin.phonerelay.diagnostics

interface RelayLogger {
    fun info(message: String)
    fun warn(message: String, error: Throwable? = null)
    fun error(message: String, error: Throwable? = null)
}
