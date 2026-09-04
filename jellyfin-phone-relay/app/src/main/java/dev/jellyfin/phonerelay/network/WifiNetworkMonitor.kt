package dev.jellyfin.phonerelay.network

import android.content.Context
import android.net.ConnectivityManager
import android.net.Network
import android.net.NetworkCapabilities
import android.net.NetworkRequest
import android.net.wifi.WifiManager
import java.net.Inet4Address
import java.net.InetAddress
import java.net.NetworkInterface
import java.util.Collections
import java.util.concurrent.atomic.AtomicBoolean

class WifiNetworkMonitor(context: Context) {
    private val connectivityManager = context.getSystemService(ConnectivityManager::class.java)
    private val wifiManager = context.applicationContext.getSystemService(WifiManager::class.java)
    private val registered = AtomicBoolean()
    private var listener: ((String?) -> Unit)? = null
    private var lastAddress: String? = null

    private val callback = object : ConnectivityManager.NetworkCallback() {
        override fun onAvailable(network: Network) = publishIfChanged()
        override fun onLost(network: Network) = publishIfChanged()
        override fun onCapabilitiesChanged(network: Network, capabilities: NetworkCapabilities) = publishIfChanged()
        override fun onLinkPropertiesChanged(network: Network, linkProperties: android.net.LinkProperties) = publishIfChanged()
    }

    fun currentIpv4(): String? {
        val frameworkAddress = frameworkWifiAddresses()
            .firstOrNull(WifiAddressSelector::isUsableLanAddress)
        if (frameworkAddress != null) return frameworkAddress.hostAddress

        val wifiManagerAddress = legacyWifiAddress()
        if (wifiManagerAddress != null && WifiAddressSelector.isUsableLanAddress(wifiManagerAddress)) {
            return wifiManagerAddress.hostAddress
        }

        // Some Android/Tailscale combinations expose only the VPN as the active
        // framework network. In that case inspect the real Wi-Fi interface.
        return systemWifiAddresses()
            .firstOrNull(WifiAddressSelector::isUsableLanAddress)
            ?.hostAddress
    }

    @Suppress("DEPRECATION")
    private fun frameworkWifiAddresses(): Sequence<Inet4Address> = connectivityManager.allNetworks
        .asSequence()
        .filter { network ->
            val capabilities = connectivityManager.getNetworkCapabilities(network) ?: return@filter false
            capabilities.hasTransport(NetworkCapabilities.TRANSPORT_WIFI) &&
                !capabilities.hasTransport(NetworkCapabilities.TRANSPORT_VPN) &&
                capabilities.hasCapability(NetworkCapabilities.NET_CAPABILITY_NOT_VPN)
        }
        .flatMap { network ->
            connectivityManager.getLinkProperties(network)?.linkAddresses.orEmpty().asSequence()
        }
        .map { it.address }
        .filterIsInstance<Inet4Address>()

    private fun systemWifiAddresses(): Sequence<Inet4Address> = runCatching {
        val interfaces = NetworkInterface.getNetworkInterfaces() ?: return@runCatching emptySequence()
        Collections.list(interfaces)
            .asSequence()
            .filter { it.isUp && !it.isLoopback && WifiAddressSelector.isLikelyWifiInterface(it.name) }
            .sortedBy { WifiAddressSelector.interfacePriority(it.name) }
            .flatMap { Collections.list(it.inetAddresses).asSequence() }
            .filterIsInstance<Inet4Address>()
    }.getOrElse { emptySequence() }

    @Suppress("DEPRECATION")
    private fun legacyWifiAddress(): Inet4Address? = runCatching {
        val packedAddress = wifiManager.connectionInfo.ipAddress
        if (packedAddress == 0) null else WifiAddressSelector.fromLittleEndianIpv4(packedAddress)
    }.getOrNull()

    fun start(onChanged: (String?) -> Unit) {
        listener = onChanged
        lastAddress = currentIpv4()
        onChanged(lastAddress)
        if (registered.compareAndSet(false, true)) {
            val request = NetworkRequest.Builder()
                .addTransportType(NetworkCapabilities.TRANSPORT_WIFI)
                .addCapability(NetworkCapabilities.NET_CAPABILITY_NOT_VPN)
                .build()
            connectivityManager.registerNetworkCallback(request, callback)
        }
    }

    fun stop() {
        listener = null
        if (registered.compareAndSet(true, false)) {
            runCatching { connectivityManager.unregisterNetworkCallback(callback) }
        }
    }

    private fun publishIfChanged() {
        val current = currentIpv4()
        if (current != lastAddress) {
            lastAddress = current
            listener?.invoke(current)
        }
    }
}

/** Keeps Tailscale's CGNAT address from ever being advertised as the LAN listener. */
internal object WifiAddressSelector {
    fun isUsableLanAddress(address: InetAddress): Boolean =
        address is Inet4Address &&
            !address.isAnyLocalAddress &&
            !address.isLoopbackAddress &&
            !address.isLinkLocalAddress &&
            !address.isMulticastAddress &&
            !isTailscaleCgnat(address)

    fun isTailscaleCgnat(address: Inet4Address): Boolean {
        val octets = address.address
        val first = octets[0].toInt() and 0xff
        val second = octets[1].toInt() and 0xff
        return first == 100 && second in 64..127
    }

    fun isLikelyWifiInterface(name: String): Boolean {
        val normalized = name.lowercase()
        if (normalized.contains("tun") || normalized.contains("tail") || normalized.contains("vpn")) return false
        if (normalized.contains("p2p") || normalized.startsWith("ap")) return false
        return normalized.startsWith("wlan") || normalized.contains("wlan") || normalized.startsWith("wifi")
    }

    fun interfacePriority(name: String): Int = when (name.lowercase()) {
        "wlan0" -> 0
        "wlan1" -> 1
        else -> 2
    }

    fun fromLittleEndianIpv4(value: Int): Inet4Address = InetAddress.getByAddress(
        byteArrayOf(
            (value and 0xff).toByte(),
            (value shr 8 and 0xff).toByte(),
            (value shr 16 and 0xff).toByte(),
            (value shr 24 and 0xff).toByte(),
        ),
    ) as Inet4Address
}
