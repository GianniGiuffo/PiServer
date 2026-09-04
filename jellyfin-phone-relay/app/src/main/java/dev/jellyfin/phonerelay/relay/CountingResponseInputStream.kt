package dev.jellyfin.phonerelay.relay

import okhttp3.Response
import java.io.FilterInputStream
import java.io.InputStream
import java.util.concurrent.atomic.AtomicBoolean

class CountingResponseInputStream(
    input: InputStream,
    private val response: Response,
    private val onBytes: (Long) -> Unit,
    private val onFinished: () -> Unit,
) : FilterInputStream(input) {
    private val finished = AtomicBoolean()

    override fun read(): Int {
        val value = super.read()
        if (value >= 0) onBytes(1) else finish()
        return value
    }

    override fun read(buffer: ByteArray, offset: Int, length: Int): Int {
        val count = super.read(buffer, offset, length)
        if (count > 0) onBytes(count.toLong()) else if (count < 0) finish()
        return count
    }

    override fun close() {
        try {
            super.close()
        } finally {
            finish()
        }
    }

    private fun finish() {
        if (finished.compareAndSet(false, true)) {
            response.close()
            onFinished()
        }
    }
}
