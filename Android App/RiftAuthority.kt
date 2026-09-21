// RiftAuthority.kt - announces this RIFT instance to a NORA hub as the fleet
// authority, over HTTP/WiFi (default) or a Bluetooth serial link. Kotlin
// counterpart of Fleet/register.py + Fleet/bt_link.py: while RIFT keeps
// heartbeating, NORA defers her /robots response to point at RIFT; if it stops,
// the registration simply expires on her side.
package com.example.riftcontrol

import java.net.HttpURLConnection
import java.net.URL
import java.net.URLEncoder

/** A Bluetooth serial link to NORA: send "H<name>:<caps>\n", she replies "OK\n" or "ERR\n". */
interface BtLink {
    fun register(name: String, capabilities: String): Boolean
    fun close()
}

/** On Android, [port] is the paired NORA's Bluetooth MAC address; see AndroidBtLink. */
typealias BtLinkFactory = (port: String) -> BtLink

class RiftAuthority(private val cfg: RiftConfig, private val btFactory: BtLinkFactory? = null) {
    private companion object {
        const val CAPABILITIES = "fleet_management,monitoring"
    }

    private val gate = Object()
    private var mode = "wifi"
    private var btPort = ""
    private var worker: Thread? = null

    fun state(): Pair<String, String> = synchronized(gate) { Pair(mode, btPort) }

    /** Retires the current heartbeat (if any) and starts one on the given transport. */
    fun restart(newMode: String, newBtPort: String) {
        synchronized(gate) {
            stopLocked()
            mode = newMode
            btPort = newBtPort
            if (cfg.noHeartbeat) return
            val flag = java.util.concurrent.atomic.AtomicBoolean(false)
            currentFlag = flag
            worker = Thread({ loop(newMode, newBtPort, flag) }, "rift-heartbeat").apply { isDaemon = true; start() }
        }
    }

    private var currentFlag: java.util.concurrent.atomic.AtomicBoolean? = null

    private fun stopLocked() {
        val t = worker ?: return
        currentFlag?.set(true)
        t.interrupt()
        try { t.join(2500) } catch (_: InterruptedException) { }
        worker = null
        currentFlag = null
    }

    fun stop() = synchronized(gate) { stopLocked() }

    private fun announceWifi() {
        try {
            val form = "name=" + URLEncoder.encode(cfg.name, "UTF-8") +
                "&type=fleet_manager&capabilities=" + URLEncoder.encode(CAPABILITIES, "UTF-8")
            val conn = URL("http://${cfg.noraHost}:${cfg.noraPort}/register").openConnection() as HttpURLConnection
            conn.connectTimeout = 2000
            conn.readTimeout = 2000
            conn.requestMethod = "POST"
            conn.doOutput = true
            conn.setRequestProperty("Content-Type", "application/x-www-form-urlencoded")
            conn.outputStream.use { it.write(form.toByteArray()) }
            conn.responseCode
            conn.disconnect()
        } catch (_: Exception) {
            // NORA may not be reachable yet (booting, or not on her AP) - keep retrying.
        }
    }

    private fun loop(loopMode: String, loopBtPort: String, stop: java.util.concurrent.atomic.AtomicBoolean) {
        var bt: BtLink? = null
        try {
            while (!stop.get()) {
                if (loopMode == "bluetooth") {
                    try {
                        if (bt == null) bt = btFactory?.invoke(loopBtPort) ?: throw UnsupportedOperationException("no Bluetooth support")
                        bt.register(cfg.name, CAPABILITIES)
                    } catch (_: Exception) {
                        try { bt?.close() } catch (_: Exception) { }
                        bt = null // drop the link and reopen next round
                    }
                } else announceWifi()
                try { Thread.sleep((cfg.heartbeatSecs * 1000).toLong()) } catch (_: InterruptedException) { return }
            }
        } finally {
            try { bt?.close() } catch (_: Exception) { }
        }
    }
}
