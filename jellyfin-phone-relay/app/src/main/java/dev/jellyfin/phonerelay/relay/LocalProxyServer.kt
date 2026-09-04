package dev.jellyfin.phonerelay.relay

import dev.jellyfin.phonerelay.diagnostics.Redactor
import dev.jellyfin.phonerelay.diagnostics.RelayLogger
import dev.jellyfin.phonerelay.diagnostics.RelayMetrics
import fi.iki.elonen.NanoHTTPD
import fi.iki.elonen.NanoWSD
import okhttp3.HttpUrl
import okhttp3.MediaType.Companion.toMediaTypeOrNull
import okhttp3.OkHttpClient
import okhttp3.Request
import okhttp3.RequestBody.Companion.toRequestBody
import java.io.ByteArrayInputStream
import java.io.IOException
import java.net.SocketTimeoutException
import java.nio.charset.StandardCharsets
import java.util.Locale
import java.util.concurrent.TimeUnit
import java.util.concurrent.atomic.AtomicBoolean

class LocalProxyServer(
    hostname: String,
    port: Int,
    private val upstream: HttpUrl,
    private val relayOrigin: String,
    private val metrics: RelayMetrics,
    private val logger: RelayLogger,
) : NanoWSD(hostname, port) {
    private val client = OkHttpClient.Builder()
        .connectTimeout(12, TimeUnit.SECONDS)
        .readTimeout(0, TimeUnit.MILLISECONDS)
        .writeTimeout(0, TimeUnit.MILLISECONDS)
        .followRedirects(false)
        .followSslRedirects(false)
        .retryOnConnectionFailure(true)
        .dispatcher(
            okhttp3.Dispatcher().apply {
                maxRequests = 64
                maxRequestsPerHost = 32
            },
        )
        .build()

    override fun serveHttp(session: IHTTPSession): Response {
        if (session.method == Method.GET && session.uri == HEALTH_PATH) return healthResponse()

        val startedAt = System.nanoTime()
        metrics.activeHttp.incrementAndGet()
        metrics.totalHttp.incrementAndGet()
        val finished = AtomicBoolean()
        fun finish() {
            if (finished.compareAndSet(false, true)) metrics.activeHttp.decrementAndGet()
        }

        return try {
            val target = UrlMapper.mapHttp(upstream, session.uri, session.queryParameterString)
            val request = buildRequest(session, target)
            val upstreamResponse = client.newCall(request).execute()
            val response = buildDownstreamResponse(session, upstreamResponse, ::finish)
            val elapsedMs = TimeUnit.NANOSECONDS.toMillis(System.nanoTime() - startedAt)
            logger.info("${session.method.name} ${Redactor.safePath(session.uri)} -> ${upstreamResponse.code} ${elapsedMs}ms")
            response
        } catch (error: SocketTimeoutException) {
            metrics.upstreamErrors.incrementAndGet()
            finish()
            logger.warn("Timeout upstream per ${Redactor.safePath(session.uri)}", error)
            plainError(ProxyStatus(504, "Gateway Timeout"), "Timeout del server Jellyfin")
        } catch (error: IOException) {
            metrics.upstreamErrors.incrementAndGet()
            finish()
            logger.warn("Upstream non raggiungibile per ${Redactor.safePath(session.uri)}", error)
            plainError(ProxyStatus(502, "Bad Gateway"), "Server Jellyfin non raggiungibile")
        } catch (error: Exception) {
            metrics.upstreamErrors.incrementAndGet()
            finish()
            logger.error("Errore relay per ${Redactor.safePath(session.uri)}", error)
            plainError(Response.Status.INTERNAL_ERROR, "Errore interno del relay")
        }
    }

    override fun openWebSocket(handshake: IHTTPSession): WebSocket {
        val target = UrlMapper.mapWebSocket(upstream, handshake.uri, handshake.queryParameterString)
        val requestBuilder = Request.Builder().url(target)
        HeaderSanitizer.requestHeaders(handshake.headers, webSocket = true).forEach { (name, value) ->
            requestBuilder.addHeader(name, value)
        }
        return RelayWebSocket(
            handshake = handshake,
            upstreamRequest = requestBuilder.build(),
            client = client,
            metrics = metrics,
            logger = logger,
        )
    }

    override fun stop() {
        super.stop()
        client.dispatcher.cancelAll()
        client.connectionPool.evictAll()
    }

    private fun buildRequest(session: IHTTPSession, target: HttpUrl): Request {
        val method = session.method.name.uppercase(Locale.US)
        val contentLength = session.headers["content-length"]?.toLongOrNull() ?: 0L
        val transferEncoding = session.headers["transfer-encoding"].orEmpty()
        if (transferEncoding.contains("chunked", ignoreCase = true)) {
            throw IOException("Le request body chunked non sono supportate dal listener MVP")
        }

        val mediaType = session.headers["content-type"]?.toMediaTypeOrNull()
        val body = when {
            contentLength > 0L -> StreamingRequestBody(
                input = session.inputStream,
                length = contentLength,
                mediaType = mediaType,
                onBytes = metrics.downstreamToUpstreamBytes::addAndGet,
            )
            requiresRequestBody(method) -> ByteArray(0).toRequestBody(mediaType)
            else -> null
        }

        return Request.Builder()
            .url(target)
            .apply {
                HeaderSanitizer.requestHeaders(session.headers).forEach { (name, value) ->
                    addHeader(name, value)
                }
                header("Accept-Encoding", "identity")
            }
            .method(method, body)
            .build()
    }

    private fun buildDownstreamResponse(
        session: IHTTPSession,
        upstreamResponse: okhttp3.Response,
        finish: () -> Unit,
    ): Response {
        val body = upstreamResponse.body
        val contentType = upstreamResponse.header("Content-Type")
        val isHead = session.method == Method.HEAD
        val noBody = isHead || body == null || upstreamResponse.code == 204 || upstreamResponse.code == 304
        val shouldRewritePlaylist = body != null &&
            !isHead &&
            UrlRewriter.isPlaylist(contentType, session.uri) &&
            body.contentLength() in 0..UrlRewriter.MAX_REWRITE_BYTES

        val rewrittenBody: ByteArray? = if (shouldRewritePlaylist) {
            val original = body!!.bytes().toString(StandardCharsets.UTF_8)
            UrlRewriter.rewritePlaylist(original, upstream, relayOrigin).toByteArray(StandardCharsets.UTF_8)
        } else {
            null
        }

        val status = ProxyStatus(upstreamResponse.code, upstreamResponse.message)
        val response = when {
            noBody -> {
                val declaredLength = if (isHead) {
                    upstreamResponse.header("Content-Length")?.toLongOrNull() ?: body?.contentLength() ?: 0L
                } else {
                    0L
                }
                upstreamResponse.close()
                finish()
                newFixedLengthResponse(status, contentType, ByteArrayInputStream(ByteArray(0)), declaredLength)
            }
            rewrittenBody != null -> {
                upstreamResponse.close()
                finish()
                metrics.upstreamToDownstreamBytes.addAndGet(rewrittenBody.size.toLong())
                newFixedLengthResponse(
                    status,
                    contentType,
                    ByteArrayInputStream(rewrittenBody),
                    rewrittenBody.size.toLong(),
                )
            }
            body!!.contentLength() >= 0 -> {
                val stream = CountingResponseInputStream(
                    input = body.byteStream(),
                    response = upstreamResponse,
                    onBytes = metrics.upstreamToDownstreamBytes::addAndGet,
                    onFinished = finish,
                )
                newFixedLengthResponse(status, contentType, stream, body.contentLength())
            }
            else -> {
                val stream = CountingResponseInputStream(
                    input = body.byteStream(),
                    response = upstreamResponse,
                    onBytes = metrics.upstreamToDownstreamBytes::addAndGet,
                    onFinished = finish,
                )
                newChunkedResponse(status, contentType, stream)
            }
        }

        HeaderSanitizer.responseHeaders(upstreamResponse.headers.map { it.first to it.second })
            .filterNot { (name, _) ->
                rewrittenBody != null && name.lowercase() in INVALID_AFTER_REWRITE
            }
            .forEach { (name, value) ->
                val actualValue = if (name.equals("location", ignoreCase = true)) {
                    UrlRewriter.rewriteLocation(value, upstream, relayOrigin)
                } else {
                    value
                }
                response.addHeader(name, actualValue)
            }
        return response
    }

    private fun healthResponse(): Response {
        val json = """{"relay":"running","activeHttp":${metrics.activeHttp.get()},"activeWebSockets":${metrics.activeWebSockets.get()}}"""
        return newFixedLengthResponse(Response.Status.OK, "application/json; charset=utf-8", json)
    }

    private fun plainError(status: Response.IStatus, message: String): Response =
        newFixedLengthResponse(status, "text/plain; charset=utf-8", message)

    private fun requiresRequestBody(method: String): Boolean = method == "POST" || method == "PUT" || method == "PATCH"

    private class ProxyStatus(
        private val code: Int,
        private val reason: String,
    ) : Response.IStatus {
        override fun getRequestStatus(): Int = code

        override fun getDescription(): String = "$code ${reason.ifBlank { "Upstream" }}"
    }

    private companion object {
        const val HEALTH_PATH = "/_jpr/health"
        val INVALID_AFTER_REWRITE = setOf("etag", "content-md5", "content-encoding")
    }
}
