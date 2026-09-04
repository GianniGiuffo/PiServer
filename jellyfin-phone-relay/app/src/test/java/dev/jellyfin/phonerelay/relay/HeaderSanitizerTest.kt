package dev.jellyfin.phonerelay.relay

import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertTrue
import org.junit.Test

class HeaderSanitizerTest {
    @Test
    fun `preserves jellyfin and range headers while dropping hop by hop headers`() {
        val result = HeaderSanitizer.requestHeaders(
            linkedMapOf(
                "Host" to "192.168.1.50:8097",
                "Connection" to "keep-alive, X-Temporary",
                "Keep-Alive" to "timeout=5",
                "X-Temporary" to "remove-me",
                "Authorization" to "MediaBrowser token=secret",
                "X-Emby-Authorization" to "MediaBrowser DeviceId=tv-1",
                "Range" to "bytes=0-1048575",
                "If-Range" to "etag-value",
                "User-Agent" to "Jellyfin Android TV",
            ),
        ).associate { it.first.lowercase() to it.second }

        assertFalse("host" in result)
        assertFalse("connection" in result)
        assertFalse("keep-alive" in result)
        assertFalse("x-temporary" in result)
        assertEquals("bytes=0-1048575", result["range"])
        assertEquals("MediaBrowser token=secret", result["authorization"])
        assertEquals("MediaBrowser DeviceId=tv-1", result["x-emby-authorization"])
        assertEquals("Jellyfin Android TV", result["user-agent"])
    }

    @Test
    fun `drops response framing but preserves range metadata`() {
        val result = HeaderSanitizer.responseHeaders(
            listOf(
                "Transfer-Encoding" to "chunked",
                "Content-Length" to "1024",
                "Content-Range" to "bytes 0-1023/4096",
                "Accept-Ranges" to "bytes",
                "ETag" to "abc",
            ),
        ).associate { it.first.lowercase() to it.second }

        assertFalse("transfer-encoding" in result)
        assertFalse("content-length" in result)
        assertTrue("content-range" in result)
        assertTrue("accept-ranges" in result)
        assertTrue("etag" in result)
    }
}
