package dev.jellyfin.phonerelay.network

import org.junit.Assert.assertFalse
import org.junit.Assert.assertTrue
import org.junit.Test
import java.net.Inet4Address
import java.net.InetAddress

class WifiAddressSelectorTest {
    @Test
    fun `rejects the Tailscale CGNAT range`() {
        assertFalse(WifiAddressSelector.isUsableLanAddress(ipv4("100.64.0.1")))
        assertFalse(WifiAddressSelector.isUsableLanAddress(ipv4("100.121.73.5")))
        assertFalse(WifiAddressSelector.isUsableLanAddress(ipv4("100.127.255.254")))
    }

    @Test
    fun `accepts normal private WiFi addresses`() {
        assertTrue(WifiAddressSelector.isUsableLanAddress(ipv4("192.168.1.47")))
        assertTrue(WifiAddressSelector.isUsableLanAddress(ipv4("10.0.0.25")))
        assertTrue(WifiAddressSelector.isUsableLanAddress(ipv4("172.20.10.4")))
    }

    @Test
    fun `rejects non routable listener addresses`() {
        assertFalse(WifiAddressSelector.isUsableLanAddress(ipv4("0.0.0.0")))
        assertFalse(WifiAddressSelector.isUsableLanAddress(ipv4("127.0.0.1")))
        assertFalse(WifiAddressSelector.isUsableLanAddress(ipv4("169.254.12.4")))
        assertFalse(WifiAddressSelector.isUsableLanAddress(ipv4("224.0.0.1")))
    }

    @Test
    fun `recognizes WiFi interfaces but never VPN interfaces`() {
        assertTrue(WifiAddressSelector.isLikelyWifiInterface("wlan0"))
        assertTrue(WifiAddressSelector.isLikelyWifiInterface("swlan1"))
        assertFalse(WifiAddressSelector.isLikelyWifiInterface("tun0"))
        assertFalse(WifiAddressSelector.isLikelyWifiInterface("tailscale0"))
        assertFalse(WifiAddressSelector.isLikelyWifiInterface("p2p0"))
    }

    @Test
    fun `decodes the WifiManager packed IPv4 address`() {
        assertTrue(WifiAddressSelector.fromLittleEndianIpv4(0x2f01a8c0).hostAddress == "192.168.1.47")
    }

    private fun ipv4(value: String): Inet4Address = InetAddress.getByName(value) as Inet4Address
}
