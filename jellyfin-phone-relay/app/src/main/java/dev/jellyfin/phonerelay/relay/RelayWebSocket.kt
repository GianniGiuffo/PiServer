package dev.jellyfin.phonerelay.relay

import dev.jellyfin.phonerelay.diagnostics.Redactor
import dev.jellyfin.phonerelay.diagnostics.RelayLogger
import dev.jellyfin.phonerelay.diagnostics.RelayMetrics
import fi.iki.elonen.NanoHTTPD.IHTTPSession
import fi.iki.elonen.NanoWSD
import okhttp3.OkHttpClient
import okhttp3.Request
import okhttp3.Response
import okhttp3.WebSocketListener
import okio.ByteString
import java.io.IOException
import java.util.concurrent.atomic.AtomicBoolean

class RelayWebSocket(
    handshake: IHTTPSession,
    private val upstreamRequest: Request,
    private val client: OkHttpClient,
    private val metrics: RelayMetrics,
    private val logger: RelayLogger,
) : NanoWSD.WebSocket(handshake) {
    @Volatile
    private var upstreamSocket: okhttp3.WebSocket? = null
    private val finished = AtomicBoolean()

    override fun onOpen() {
        metrics.activeWebSockets.incrementAndGet()
        logger.info("WS connesso ${Redactor.safePath(handshakeRequest.uri)}")
        upstreamSocket = client.newWebSocket(upstreamRequest, UpstreamListener())
    }

    override fun onClose(code: NanoWSD.WebSocketFrame.CloseCode, reason: String, initiatedByRemote: Boolean) {
        upstreamSocket?.close(code.value, reason.take(120))
        finish("WS chiuso ${Redactor.safePath(handshakeRequest.uri)}")
    }

    override fun onMessage(message: NanoWSD.WebSocketFrame) {
        val socket = upstreamSocket ?: return
        when (message.opCode) {
            NanoWSD.WebSocketFrame.OpCode.Text -> socket.send(message.textPayload)
            NanoWSD.WebSocketFrame.OpCode.Binary -> socket.send(ByteString.of(*message.binaryPayload))
            else -> Unit
        }
    }

    override fun onPong(pong: NanoWSD.WebSocketFrame) = Unit

    override fun onException(exception: IOException) {
        upstreamSocket?.cancel()
        finish("Errore WebSocket locale")
        logger.warn("Errore WS ${Redactor.safePath(handshakeRequest.uri)}", exception)
    }

    private fun closeDownstream(reason: String) {
        try {
            close(NanoWSD.WebSocketFrame.CloseCode.NormalClosure, reason.take(120), false)
        } catch (_: IOException) {
            finish("WS terminato")
        }
    }

    private fun finish(message: String) {
        if (finished.compareAndSet(false, true)) {
            metrics.activeWebSockets.decrementAndGet()
            logger.info(message)
        }
    }

    private inner class UpstreamListener : WebSocketListener() {
        override fun onMessage(webSocket: okhttp3.WebSocket, text: String) {
            try {
                send(text)
            } catch (error: IOException) {
                webSocket.cancel()
                onException(error)
            }
        }

        override fun onMessage(webSocket: okhttp3.WebSocket, bytes: ByteString) {
            try {
                send(bytes.toByteArray())
            } catch (error: IOException) {
                webSocket.cancel()
                onException(error)
            }
        }

        override fun onClosing(webSocket: okhttp3.WebSocket, code: Int, reason: String) {
            webSocket.close(code, reason)
            closeDownstream(reason.ifBlank { "Upstream chiuso" })
        }

        override fun onClosed(webSocket: okhttp3.WebSocket, code: Int, reason: String) {
            closeDownstream(reason.ifBlank { "Upstream chiuso" })
            finish("WS upstream chiuso")
        }

        override fun onFailure(webSocket: okhttp3.WebSocket, error: Throwable, response: Response?) {
            logger.warn("Connessione WS upstream fallita", error)
            try {
                close(NanoWSD.WebSocketFrame.CloseCode.InternalServerError, "Upstream non raggiungibile", false)
            } catch (_: IOException) {
                // The downstream socket may already be gone.
            }
            finish("WS upstream non raggiungibile")
        }
    }
}
