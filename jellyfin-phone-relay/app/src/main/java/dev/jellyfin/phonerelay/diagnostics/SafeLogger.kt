package dev.jellyfin.phonerelay.diagnostics

import android.util.Log
import java.text.SimpleDateFormat
import java.util.Date
import java.util.Locale

class SafeLogger(
    private val stateStore: RelayStateStore,
    private val maxLines: Int = 80,
) : RelayLogger {
    @Synchronized
    override fun info(message: String) = append(Log.INFO, message, null)

    @Synchronized
    override fun warn(message: String, error: Throwable?) = append(Log.WARN, message, error)

    @Synchronized
    override fun error(message: String, error: Throwable?) = append(Log.ERROR, message, error)

    private fun append(priority: Int, message: String, error: Throwable?) {
        val safe = Redactor.redact(message)
        Log.println(priority, TAG, safe)
        if (error != null) Log.println(priority, TAG, error.javaClass.simpleName)
        val time = SimpleDateFormat("HH:mm:ss", Locale.ITALY).format(Date())
        stateStore.update { snapshot ->
            snapshot.copy(logs = (snapshot.logs + "$time $safe").takeLast(maxLines))
        }
    }

    private companion object {
        const val TAG = "JellyfinPhoneRelay"
    }
}
