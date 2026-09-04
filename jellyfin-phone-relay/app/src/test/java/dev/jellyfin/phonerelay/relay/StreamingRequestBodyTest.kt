package dev.jellyfin.phonerelay.relay

import okio.Buffer
import org.junit.Assert.assertArrayEquals
import org.junit.Assert.assertEquals
import org.junit.Test
import java.io.ByteArrayInputStream

class StreamingRequestBodyTest {
    @Test
    fun `copies exactly the declared body and reports bytes`() {
        val payload = ByteArray(180_000) { (it % 251).toByte() }
        var counted = 0L
        val body = StreamingRequestBody(
            input = ByteArrayInputStream(payload + byteArrayOf(9, 9, 9)),
            length = payload.size.toLong(),
            mediaType = null,
            onBytes = { counted += it },
        )
        val sink = Buffer()

        body.writeTo(sink)

        assertEquals(payload.size.toLong(), counted)
        assertArrayEquals(payload, sink.readByteArray())
    }
}
