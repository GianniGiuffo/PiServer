package dev.jellyfin.phonerelay.relay

import okhttp3.MediaType
import okhttp3.RequestBody
import okio.BufferedSink
import java.io.EOFException
import java.io.InputStream

class StreamingRequestBody(
    private val input: InputStream,
    private val length: Long,
    private val mediaType: MediaType?,
    private val onBytes: (Long) -> Unit,
) : RequestBody() {
    override fun contentType(): MediaType? = mediaType

    override fun contentLength(): Long = length

    override fun writeTo(sink: BufferedSink) {
        val buffer = ByteArray(BUFFER_SIZE)
        var remaining = length
        while (remaining > 0) {
            val read = input.read(buffer, 0, minOf(buffer.size.toLong(), remaining).toInt())
            if (read < 0) throw EOFException("Request body ended with $remaining bytes remaining")
            sink.write(buffer, 0, read)
            onBytes(read.toLong())
            remaining -= read
        }
    }

    private companion object {
        const val BUFFER_SIZE = 64 * 1024
    }
}
