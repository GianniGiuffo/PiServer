package dev.jellyfin.phonerelay.relay

import okhttp3.HttpUrl.Companion.toHttpUrl
import org.junit.Assert.assertEquals
import org.junit.Test

class UrlRewriterTest {
    private val upstream = "http://100.88.12.3:8096".toHttpUrl()
    private val relay = "http://192.168.1.47:8097"

    @Test
    fun `rewrites same-origin redirects and preserves raw query`() {
        assertEquals(
            "$relay/Videos/a%20b?api_key=secret%2Bvalue",
            UrlRewriter.rewriteLocation(
                "http://100.88.12.3:8096/Videos/a%20b?api_key=secret%2Bvalue",
                upstream,
                relay,
            ),
        )
    }

    @Test
    fun `does not rewrite external redirects`() {
        val external = "https://login.example.test/continue"
        assertEquals(external, UrlRewriter.rewriteLocation(external, upstream, relay))
    }

    @Test
    fun `rewrites absolute HLS urls only for the upstream origin`() {
        val source = """#EXTM3U
#EXT-X-KEY:METHOD=AES-128,URI="http://100.88.12.3:8096/key?id=1"
http://100.88.12.3:8096/Videos/segment.ts?api_key=secret
https://cdn.example.test/unrelated.ts
"""
        val expected = source.replace("http://100.88.12.3:8096", relay)

        assertEquals(expected, UrlRewriter.rewritePlaylist(source, upstream, relay))
    }
}
