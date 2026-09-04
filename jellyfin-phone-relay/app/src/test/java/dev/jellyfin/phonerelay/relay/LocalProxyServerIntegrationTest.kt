package dev.jellyfin.phonerelay.relay

import dev.jellyfin.phonerelay.diagnostics.RelayLogger
import dev.jellyfin.phonerelay.diagnostics.RelayMetrics
import fi.iki.elonen.NanoHTTPD
import fi.iki.elonen.NanoWSD
import okhttp3.OkHttpClient
import okhttp3.Request
import okhttp3.WebSocketListener
import okhttp3.Response as OkHttpResponse
import okhttp3.WebSocket as OkHttpWebSocket
import org.junit.After
import org.junit.Assert.assertArrayEquals
import org.junit.Assert.assertEquals
import org.junit.Assert.assertTrue
import org.junit.Before
import org.junit.Test
import java.io.IOException
import java.net.ServerSocket
import java.util.concurrent.CountDownLatch
import java.util.concurrent.TimeUnit
import java.util.concurrent.atomic.AtomicReference

class LocalProxyServerIntegrationTest {
    private val client = OkHttpClient.Builder().followRedirects(false).build()
    private lateinit var upstream: TestUpstream
    private lateinit var relay: LocalProxyServer
    private var upstreamPort = 0
    private var relayPort = 0

    @Before
    fun setUp() {
        upstreamPort = freePort()
        relayPort = freePort()
        upstream = TestUpstream(upstreamPort).also { it.start(0, false) }
        relay = LocalProxyServer(
            hostname = "127.0.0.1",
            port = relayPort,
            upstream = okhttp3.HttpUrl.Builder()
                .scheme("http")
                .host("127.0.0.1")
                .port(upstreamPort)
                .build(),
            relayOrigin = "http://127.0.0.1:$relayPort",
            metrics = RelayMetrics(),
            logger = FakeLogger,
        ).also { it.start(0, false) }
    }

    @After
    fun tearDown() {
        relay.stop()
        upstream.stop()
        client.dispatcher.cancelAll()
        client.connectionPool.evictAll()
    }

    @Test
    fun `passes through range status headers and bytes`() {
        val response = client.newCall(
            Request.Builder()
                .url("http://127.0.0.1:$relayPort/range?item=a%20b")
                .header("Range", "bytes=0-1023")
                .build(),
        ).execute()

        response.use {
            assertEquals(206, it.code)
            assertEquals("bytes 0-1023/4096", it.header("Content-Range"))
            assertEquals("bytes", it.header("Accept-Ranges"))
            assertEquals("bytes=0-1023", upstream.lastRange.get())
            assertArrayEquals(upstream.rangePayload, it.body!!.bytes())
        }
    }

    @Test
    fun `rewrites upstream location and HLS absolute urls`() {
        client.newCall(Request.Builder().url("http://127.0.0.1:$relayPort/redirect").build())
            .execute().use {
                assertEquals(301, it.code)
                assertEquals(
                    "http://127.0.0.1:$relayPort/Videos/next?x=1",
                    it.header("Location"),
                )
            }

        client.newCall(Request.Builder().url("http://127.0.0.1:$relayPort/playlist.m3u8").build())
            .execute().use {
                val body = it.body!!.string()
                assertTrue(body.contains("http://127.0.0.1:$relayPort/segment.ts?token=secret"))
                assertTrue(!body.contains("http://127.0.0.1:$upstreamPort/segment.ts"))
            }
    }

    @Test
    fun `relays websocket messages in both directions`() {
        val connected = CountDownLatch(1)
        val echoed = CountDownLatch(1)
        val received = AtomicReference<String>()
        val socket = client.newWebSocket(
            Request.Builder().url("http://127.0.0.1:$relayPort/socket?device=tv").build(),
            object : WebSocketListener() {
                override fun onOpen(webSocket: OkHttpWebSocket, response: OkHttpResponse) {
                    connected.countDown()
                    webSocket.send("play-on")
                }

                override fun onMessage(webSocket: OkHttpWebSocket, text: String) {
                    received.set(text)
                    echoed.countDown()
                }
            },
        )

        assertTrue("downstream websocket did not open", connected.await(5, TimeUnit.SECONDS))
        assertTrue("echo did not cross both proxy directions", echoed.await(5, TimeUnit.SECONDS))
        assertEquals("echo:play-on", received.get())
        socket.close(1000, "test complete")
    }

    private fun freePort(): Int = ServerSocket(0).use { it.localPort }

    private object FakeLogger : RelayLogger {
        override fun info(message: String) = Unit
        override fun warn(message: String, error: Throwable?) = Unit
        override fun error(message: String, error: Throwable?) = Unit
    }

    private class TestUpstream(port: Int) : NanoWSD("127.0.0.1", port) {
        val rangePayload = ByteArray(1024) { (it % 251).toByte() }
        val lastRange = AtomicReference<String>()

        override fun serveHttp(session: IHTTPSession): NanoHTTPD.Response = when (session.uri) {
            "/range" -> newFixedLengthResponse(
                NanoHTTPD.Response.Status.PARTIAL_CONTENT,
                "video/mp4",
                rangePayload.inputStream(),
                rangePayload.size.toLong(),
            ).apply {
                lastRange.set(session.headers["range"])
                addHeader("Accept-Ranges", "bytes")
                addHeader("Content-Range", "bytes 0-1023/4096")
            }

            "/redirect" -> newFixedLengthResponse(NanoHTTPD.Response.Status.REDIRECT, "text/plain", "redirect").apply {
                addHeader("Location", "http://127.0.0.1:$listeningPort/Videos/next?x=1")
            }

            "/playlist.m3u8" -> {
                val playlist = "#EXTM3U\nhttp://127.0.0.1:$listeningPort/segment.ts?token=secret\n"
                newFixedLengthResponse(NanoHTTPD.Response.Status.OK, "application/vnd.apple.mpegurl", playlist)
            }

            else -> newFixedLengthResponse(NanoHTTPD.Response.Status.NOT_FOUND, "text/plain", "not found")
        }

        override fun openWebSocket(handshake: IHTTPSession): NanoWSD.WebSocket = object : NanoWSD.WebSocket(handshake) {
            override fun onOpen() = Unit

            override fun onClose(code: WebSocketFrame.CloseCode, reason: String, initiatedByRemote: Boolean) = Unit

            override fun onMessage(message: WebSocketFrame) {
                when (message.opCode) {
                    WebSocketFrame.OpCode.Text -> send("echo:${message.textPayload}")
                    WebSocketFrame.OpCode.Binary -> send(message.binaryPayload)
                    else -> Unit
                }
            }

            override fun onPong(pong: WebSocketFrame) = Unit

            override fun onException(exception: IOException) = Unit
        }
    }
}
