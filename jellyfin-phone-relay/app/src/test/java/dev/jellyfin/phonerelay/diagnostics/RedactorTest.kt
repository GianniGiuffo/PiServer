package dev.jellyfin.phonerelay.diagnostics

import org.junit.Assert.assertFalse
import org.junit.Assert.assertTrue
import org.junit.Test

class RedactorTest {
    @Test
    fun `redacts query tokens and authorization headers`() {
        val source = "GET /Videos/1?api_key=top-secret&x=1 Authorization: Bearer also-secret"
        val result = Redactor.redact(source)

        assertFalse(result.contains("top-secret"))
        assertFalse(result.contains("also-secret"))
        assertTrue(result.contains("api_key=<REDACTED>"))
        assertTrue(result.contains("Authorization=<REDACTED>"))
    }

    @Test
    fun `safe path drops the entire query`() {
        val result = Redactor.safePath("/Items/42?token=secret&harmless=value")
        assertTrue(result == "/Items/42")
    }
}
