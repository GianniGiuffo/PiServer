package dev.jellyfin.phonerelay.relay

import okhttp3.HttpUrl.Companion.toHttpUrl
import org.junit.Assert.assertEquals
import org.junit.Assert.assertNull
import org.junit.Test

class UrlMapperTest {
    @Test
    fun `maps path and preserves encoded query`() {
        val result = UrlMapper.mapHttp(
            "http://100.64.0.8:8096".toHttpUrl(),
            "/Videos/a%20b/stream",
            "api_key=secret%2Bvalue&x=1",
        )

        assertEquals(
            "http://100.64.0.8:8096/Videos/a%20b/stream?api_key=secret%2Bvalue&x=1",
            result.toString(),
        )
    }

    @Test
    fun `keeps an upstream base path`() {
        val result = UrlMapper.mapHttp(
            "https://media.example.test/jellyfin".toHttpUrl(),
            "/System/Info/Public",
            null,
        )

        assertEquals("https://media.example.test/jellyfin/System/Info/Public", result.toString())
    }

    @Test
    fun `maps websocket scheme without losing query`() {
        val result = UrlMapper.mapWebSocket(
            "https://media.example.test".toHttpUrl(),
            "/socket",
            "api_key=abc",
        )

        assertEquals("https://media.example.test/socket?api_key=abc", result.toString())
    }

    @Test
    fun `rejects unsupported or ambiguous base urls`() {
        assertNull(UrlMapper.normalizeBaseUrl("ftp://server/file"))
        assertNull(UrlMapper.normalizeBaseUrl("http://server:8096?api_key=nope"))
    }
}
