// RiftMdns.kt - Zeroconf: publish this instance as _rift._tcp and watch for
// other RIFT instances and ComCentre (_flask-link._tcp) - browsing both is what
// lets DREAM show up in this dashboard without ComCentre knowing anything about
// RIFT. A small responder + browser over multicast UDP (224.0.0.251:5353) using
// just the DNS wire format: PTR (service -> instance), SRV (instance -> host +
// port), TXT and A (host -> address). Written on java.net.MulticastSocket rather
// than Android's NsdManager so the same code runs (and is testable) on a JVM;
// on a phone the Activity holds a WifiManager.MulticastLock so the radio
// actually delivers the packets.
package com.example.riftcontrol

import java.io.ByteArrayOutputStream
import java.net.DatagramPacket
import java.net.InetAddress
import java.net.InetSocketAddress
import java.net.MulticastSocket
import java.net.NetworkInterface
import java.net.SocketTimeoutException

class RiftMdns(private val cfg: RiftConfig, private val peers: RiftPeers, private val log: (String) -> Unit = {}) {
    private companion object {
        const val T_A = 1; const val T_PTR = 12; const val T_TXT = 16; const val T_SRV = 33; const val T_ANY = 255
        const val CLASS_IN = 1; const val CACHE_FLUSH = 0x8000
        val GROUP: InetAddress = InetAddress.getByName("224.0.0.251")
    }

    private var socket: MulticastSocket? = null
    @Volatile private var running = false
    private var recvThread: Thread? = null
    private var queryThread: Thread? = null

    // Only touched from the receive thread.
    private val srv = HashMap<String, Pair<Int, String>>()   // lowercase instance -> (port, target host)
    private val addrs = HashMap<String, String>()            // lowercase host -> IPv4
    private val instances = HashMap<String, String>()        // lowercase instance -> original case

    /** Returns null on success, else an error message. */
    fun start(): String? {
        try {
            val s = MulticastSocket(null)
            s.reuseAddress = true
            s.bind(InetSocketAddress(5353))
            val local = try { NetworkInterface.getByInetAddress(InetAddress.getByName(cfg.ip)) } catch (_: Exception) { null }
            if (local != null) {
                s.joinGroup(InetSocketAddress(GROUP, 5353), local)
                s.networkInterface = local
            } else {
                @Suppress("DEPRECATION") s.joinGroup(GROUP)
            }
            s.timeToLive = 255
            s.soTimeout = 500
            socket = s
        } catch (e: Exception) {
            return e.message ?: e.toString()
        }
        running = true
        recvThread = Thread({ receiveLoop() }, "rift-mdns-recv").apply { isDaemon = true; start() }
        queryThread = Thread({ queryLoop() }, "rift-mdns-query").apply { isDaemon = true; start() }
        return null
    }

    fun stop() {
        if (!running) return
        running = false
        send(announcePacket(0)) // goodbye
        recvThread?.join(1500)
        queryThread?.join(1500)
        socket?.close()
    }

    // ---- building ----

    private fun ByteArrayOutputStream.u16(v: Int) { write(v shr 8 and 0xff); write(v and 0xff) }
    private fun ByteArrayOutputStream.u32(v: Long) { u16((v shr 16 and 0xffff).toInt()); u16((v and 0xffff).toInt()) }

    private fun ByteArrayOutputStream.name(n: String) {
        for (label in n.trimEnd('.').split('.')) {
            val bytes = label.toByteArray(Charsets.UTF_8)
            write(bytes.size)
            write(bytes)
        }
        write(0)
    }

    private fun ByteArrayOutputStream.record(n: String, type: Int, cls: Int, ttl: Long, rdata: ByteArray) {
        name(n); u16(type); u16(cls); u32(ttl); u16(rdata.size); write(rdata)
    }

    private fun header(flags: Int, qd: Int, an: Int, ar: Int) = ByteArrayOutputStream().apply {
        u16(0); u16(flags); u16(qd); u16(an); u16(0); u16(ar)
    }

    private fun announcePacket(ttl: Long): ByteArray {
        val service = "_rift._tcp.local"
        val instance = "${cfg.name}.$service"
        val host = "${cfg.name}.local"
        val p = header(0x8400, 0, 1, 3)
        p.record(service, T_PTR, CLASS_IN, ttl, ByteArrayOutputStream().apply { name(instance) }.toByteArray())
        p.record(instance, T_SRV, CACHE_FLUSH or CLASS_IN, ttl,
            ByteArrayOutputStream().apply { u16(0); u16(0); u16(cfg.port); name(host) }.toByteArray())
        val txt = "role=fleet_manager".toByteArray()
        p.record(instance, T_TXT, CACHE_FLUSH or CLASS_IN, ttl, byteArrayOf(txt.size.toByte()) + txt)
        p.record(host, T_A, CACHE_FLUSH or CLASS_IN, ttl, InetAddress.getByName(cfg.ip).address)
        return p.toByteArray()
    }

    private fun queryPacket(name: String, type: Int) = header(0, 1, 0, 0).apply { name(name); u16(type); u16(CLASS_IN) }.toByteArray()

    private fun send(packet: ByteArray) {
        try { socket?.send(DatagramPacket(packet, packet.size, GROUP, 5353)) } catch (_: Exception) { }
    }

    // ---- parsing ----

    private class Rec(val name: String, val type: Int, val ttl: Int, val target: String, val addr: String, val port: Int)

    private fun rd16(b: ByteArray, p: Int): Int {
        if (p + 2 > b.size) throw IndexOutOfBoundsException()
        return (b[p].toInt() and 0xff shl 8) or (b[p + 1].toInt() and 0xff)
    }

    /** Reads a (possibly compressed) name at [start]; returns the name and the position just past it. */
    private fun readName(b: ByteArray, start: Int): Pair<String, Int> {
        val labels = ArrayList<String>()
        var pos = start
        var next = -1
        var hops = 0
        while (true) {
            if (pos >= b.size) throw IndexOutOfBoundsException()
            val len = b[pos].toInt() and 0xff
            if (len == 0) { pos++; break }
            if (len and 0xc0 == 0xc0) {
                if (pos + 1 >= b.size || ++hops > 32) throw IndexOutOfBoundsException()
                if (next < 0) next = pos + 2
                pos = (len and 0x3f shl 8) or (b[pos + 1].toInt() and 0xff)
            } else {
                if (pos + 1 + len > b.size) throw IndexOutOfBoundsException()
                labels.add(String(b, pos + 1, len, Charsets.UTF_8))
                pos += 1 + len
            }
        }
        return Pair(labels.joinToString("."), if (next >= 0) next else pos)
    }

    private fun parse(b: ByteArray): Pair<List<Pair<String, Int>>, List<Rec>> {
        val qd = rd16(b, 4)
        val total = rd16(b, 6) + rd16(b, 8) + rd16(b, 10)
        var p = 12
        val questions = ArrayList<Pair<String, Int>>()
        repeat(qd) {
            val (n, after) = readName(b, p)
            questions.add(Pair(n, rd16(b, after)))
            p = after + 4
        }
        val recs = ArrayList<Rec>()
        repeat(total) {
            val (n, after) = readName(b, p)
            val type = rd16(b, after)
            val ttl = (rd16(b, after + 4) shl 16) or rd16(b, after + 6)
            val rdlen = rd16(b, after + 8)
            val rd = after + 10
            if (rd + rdlen > b.size) throw IndexOutOfBoundsException()
            var target = ""; var addr = ""; var port = 0
            when {
                type == T_PTR -> target = readName(b, rd).first
                type == T_SRV -> { port = rd16(b, rd + 4); target = readName(b, rd + 6).first }
                type == T_A && rdlen == 4 -> addr = (0 until 4).joinToString(".") { (b[rd + it].toInt() and 0xff).toString() }
            }
            recs.add(Rec(n, type, ttl, target, addr, port))
            p = rd + rdlen
        }
        return Pair(questions, recs)
    }

    private fun isBrowsedService(l: String) = l == "_rift._tcp.local" || l == "_flask-link._tcp.local"
    private fun isBrowsedInstance(l: String) = l.contains("._rift._tcp.local") || l.contains("._flask-link._tcp.local")

    private fun publishPeers() {
        for ((key, portAndHost) in srv) {
            val instance = instances[key] ?: continue
            val short = instance.substringBefore('.')
            if (short == cfg.name) continue
            val ip = addrs[portAndHost.second.lowercase()] ?: continue
            peers.set(short, "http://$ip:${portAndHost.first}")
        }
    }

    private fun handle(packet: ByteArray) {
        val (questions, recs) = parse(packet)
        val service = "_rift._tcp.local"
        val instance = "${cfg.name}.$service".lowercase()
        val host = "${cfg.name}.local".lowercase()
        for ((qname, t) in questions) {
            val n = qname.lowercase()
            if ((n == service && (t == T_PTR || t == T_ANY)) || (n == instance && (t == T_SRV || t == T_TXT || t == T_ANY)) ||
                (n == host && (t == T_A || t == T_ANY))) {
                send(announcePacket(120)) // someone is asking about us
                break
            }
        }
        for (r in recs) {
            val lname = r.name.lowercase()
            when {
                r.type == T_PTR && isBrowsedService(lname) -> {
                    val short = r.target.substringBefore('.')
                    if (r.ttl == 0) peers.remove(short) // goodbye
                    else if (short != cfg.name) {
                        instances[r.target.lowercase()] = r.target
                        if (!srv.containsKey(r.target.lowercase())) send(queryPacket(r.target, T_SRV))
                    }
                }
                r.type == T_SRV && isBrowsedInstance(lname) -> {
                    instances[lname] = r.name
                    srv[lname] = Pair(r.port, r.target)
                    if (!addrs.containsKey(r.target.lowercase())) send(queryPacket(r.target, T_A))
                }
                r.type == T_A && r.addr.isNotEmpty() -> addrs[lname] = r.addr
            }
        }
        publishPeers()
    }

    private fun receiveLoop() {
        val buf = ByteArray(9000)
        while (running) {
            try {
                val dp = DatagramPacket(buf, buf.size)
                socket?.receive(dp) ?: break
                handle(dp.data.copyOf(dp.length))
            } catch (_: SocketTimeoutException) {
                // re-check running
            } catch (e: java.io.IOException) {
                if (!running) break
            } catch (_: Exception) {
                // A malformed packet from someone else must never take the responder down.
            }
        }
    }

    private fun queryLoop() {
        var announced = 0
        while (running) {
            send(queryPacket("_rift._tcp.local", T_PTR))
            send(queryPacket("_flask-link._tcp.local", T_PTR))
            if (announced < 3) { send(announcePacket(120)); announced++ }
            var i = 0
            while (i++ < (if (announced < 3) 10 else 100) && running) Thread.sleep(100)
        }
    }
}
