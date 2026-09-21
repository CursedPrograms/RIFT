// RiftCore.kt - the fleet hub's data model and protocol logic, with no Android
// dependency (so it can be unit-tested on a plain JVM): configuration, the
// registry of robots/managers that called POST /register, the mDNS peer list,
// the HTTP routes and the dashboard template renderer. Kotlin counterpart of
// app.py's _fleet/_peers dicts and Flask routes - same wire protocol, so
// PC App/PyGame/registration.py, PC App/App/registration.cpp and every robot's
// heartbeat work unchanged.
package com.example.riftcontrol

import org.json.JSONArray
import org.json.JSONException
import org.json.JSONObject
import java.net.URLDecoder
import java.util.LinkedHashMap
import java.util.TreeMap

data class RiftConfig(
    var name: String = "RIFT",
    var port: Int = 5000,
    var ip: String = "127.0.0.1",
    var ttlSecs: Double = 20.0,
    var noraHost: String = "192.168.4.1",
    var noraPort: Int = 5000,
    var heartbeatSecs: Double = 10.0,
    var noHeartbeat: Boolean = false,
    var noMdns: Boolean = false,
)

data class Robot(val name: String, val ip: String, val type: String, val capabilities: List<String>)

/** Robots that have registered, expiring after the TTL unless they keep heartbeating. */
class RiftRegistry(private val ttlSecs: Double) {
    private val members = LinkedHashMap<String, Pair<Robot, Long>>() // insertion order, like a Python dict

    @Synchronized
    fun add(name: String, ip: String, type: String, caps: List<String>, nowNanos: Long = System.nanoTime()) {
        // Re-registering keeps the original position (LinkedHashMap insertion order).
        members[name] = Pair(Robot(name, ip, type, caps), nowNanos)
    }

    /** The live roster, dropping anything not heard from within the TTL. */
    @Synchronized
    fun robots(nowNanos: Long = System.nanoTime()): List<Robot> {
        members.entries.removeAll { (nowNanos - it.value.second) / 1e9 > ttlSecs }
        return members.values.map { it.first }
    }
}

/** name -> "http://ip:port" for every peer seen over mDNS. */
class RiftPeers {
    private val items = TreeMap<String, String>()

    @Synchronized fun set(name: String, url: String) { items[name] = url }
    @Synchronized fun remove(name: String) { items.remove(name) }
    @Synchronized fun snapshot(): Map<String, String> = LinkedHashMap(items)
}

/** Where the dashboard's HTML and static files come from (the filesystem on a JVM, APK assets on Android). */
interface RiftAssets {
    fun template(): String?
    fun staticFile(rel: String): ByteArray?
}

class Reply(val status: Int, val contentType: String, val body: ByteArray) {
    constructor(status: Int, contentType: String, text: String) : this(status, contentType, text.toByteArray(Charsets.UTF_8))
}

// JSON responses are built by hand so key order matches every other RIFT implementation.
object J {
    fun str(s: String): String {
        val sb = StringBuilder("\"")
        for (c in s) {
            when {
                c == '"' -> sb.append("\\\"")
                c == '\\' -> sb.append("\\\\")
                c == '\n' -> sb.append("\\n")
                c == '\r' -> sb.append("\\r")
                c == '\t' -> sb.append("\\t")
                c < ' ' -> sb.append("\\u%04x".format(c.code))
                else -> sb.append(c)
            }
        }
        return sb.append('"').toString()
    }

    fun nullOrStr(s: String) = if (s.isEmpty()) "null" else str(s)
    fun obj(vararg fields: Pair<String, String>) = fields.joinToString(",", "{", "}") { str(it.first) + ":" + it.second }
    fun arr(items: List<String>) = items.joinToString(",", "[", "]")
}

private val templateTag = Regex("""\{\{\s*(.*?)\s*\}\}""")
private val urlForStatic = Regex("""^url_for\(\s*'static'\s*,\s*filename\s*=\s*'([^']*)'\s*\)$""")

/** Fills in the handful of Jinja expressions templates/index.html uses: {{ this_name }}, {{ my_ip }}, {{ this_port }}, url_for('static', filename=...). */
fun renderTemplate(tpl: String, vars: Map<String, String>): String =
    templateTag.replace(tpl) { m ->
        val expr = m.groupValues[1]
        vars[expr] ?: urlForStatic.find(expr)?.let { "/static/" + it.groupValues[1] } ?: m.value
    }

private fun contentTypeFor(path: String) = when (path.substringAfterLast('.', "").lowercase()) {
    "css" -> "text/css; charset=utf-8"
    "js" -> "application/javascript; charset=utf-8"
    "html" -> "text/html; charset=utf-8"
    "json" -> "application/json"
    "svg" -> "image/svg+xml"
    "png" -> "image/png"
    "ico" -> "image/x-icon"
    else -> "application/octet-stream"
}

class RiftRoutes(
    private val cfg: RiftConfig,
    val registry: RiftRegistry,
    val peers: RiftPeers,
    private val authority: RiftAuthority,
    private val assets: RiftAssets,
) {
    private val known = setOf("/ping", "/register", "/robots", "/peers", "/mode", "/")

    /**
     * A registration or mode change: app.py reads a form body; the Android app's
     * Registration.kt sends JSON, so both are accepted. Arrays such as
     * "capabilities" are joined back into a CSV.
     */
    private fun fields(contentType: String, body: String, formParams: Map<String, String>): Map<String, String> {
        if (!contentType.startsWith("application/json", ignoreCase = true)) {
            if (formParams.isNotEmpty()) return formParams
            return body.split('&').filter { it.isNotEmpty() }.associate {
                val eq = it.indexOf('=')
                val key = URLDecoder.decode(if (eq < 0) it else it.substring(0, eq), "UTF-8")
                key to if (eq < 0) "" else URLDecoder.decode(it.substring(eq + 1), "UTF-8")
            }
        }
        val out = LinkedHashMap<String, String>()
        try {
            val json = JSONObject(body)
            for (key in json.keys()) {
                when (val v = json.get(key)) {
                    is String -> out[key] = v
                    is JSONArray -> out[key] = (0 until v.length()).map { v.optString(it) }.joinToString(",")
                }
            }
        } catch (_: JSONException) {
        }
        return out
    }

    private fun robotJson(r: Robot) = J.obj(
        "name" to J.str(r.name), "ip" to J.str(r.ip), "type" to J.str(r.type),
        "capabilities" to J.arr(r.capabilities.map { J.str(it) }),
    )

    private fun json(status: Int, body: String) = Reply(status, "application/json", body)

    private fun register(contentType: String, body: String, params: Map<String, String>, remoteIp: String): Reply {
        val f = fields(contentType, body, params)
        val name = f["name"].orEmpty()
        if (name.isEmpty()) return Reply(400, "text/plain", "missing name")
        val ip = f["ip"].orEmpty().ifEmpty { remoteIp }
        registry.add(name, ip, f["type"].orEmpty().ifEmpty { "unknown" }, f["capabilities"].orEmpty().split(',').filter { it.isNotEmpty() })
        return Reply(200, "text/plain", "OK")
    }

    private fun setMode(contentType: String, body: String, params: Map<String, String>): Reply {
        val f = fields(contentType, body, params)
        val mode = f["mode"].orEmpty().trim().lowercase()
        val btPort = f["bt_port"].orEmpty().trim()
        if (mode != "wifi" && mode != "bluetooth")
            return json(400, J.obj("error" to J.str("mode must be 'wifi' or 'bluetooth'")))
        if (mode == "bluetooth" && btPort.isEmpty())
            return json(400, J.obj("error" to J.str("bt_port is required for Bluetooth mode")))
        authority.restart(mode, btPort)
        return json(200, J.obj("mode" to J.str(mode), "bt_port" to J.nullOrStr(btPort)))
    }

    private fun serveStatic(rawRel: String): Reply {
        val rel = URLDecoder.decode(rawRel, "UTF-8")
        val safe = rel.isNotEmpty() && !rel.startsWith("/") && !rel.contains('\\') && rel.split('/').none { it == ".." || it.isEmpty() }
        val bytes = if (safe) assets.staticFile(rel) else null
        return if (bytes != null) Reply(200, contentTypeFor(rel), bytes) else Reply(404, "text/plain", "Not found")
    }

    fun handle(method: String, path: String, contentType: String, body: String, params: Map<String, String>, remoteIp: String): Reply = when {
        method == "GET" && path == "/ping" -> Reply(200, "text/plain", cfg.name + " alive")
        method == "POST" && path == "/register" -> register(contentType, body, params, remoteIp)
        method == "GET" && path == "/robots" ->
            json(200, J.obj("authority" to J.str(cfg.name), "robots" to J.arr(registry.robots().map { robotJson(it) })))
        method == "GET" && path == "/peers" ->
            json(200, J.obj(*peers.snapshot().map { it.key to J.str(it.value) }.toTypedArray()))
        method == "GET" && path == "/mode" -> {
            val (mode, btPort) = authority.state()
            json(200, J.obj("mode" to J.str(mode), "bt_port" to J.nullOrStr(btPort)))
        }
        method == "POST" && path == "/mode" -> setMode(contentType, body, params)
        method == "GET" && path == "/" -> {
            val tpl = assets.template()
            if (tpl == null) Reply(500, "text/plain", "dashboard template not found")
            else Reply(200, "text/html; charset=utf-8", renderTemplate(tpl, mapOf(
                "this_name" to cfg.name, "my_ip" to cfg.ip, "this_port" to cfg.port.toString())))
        }
        method == "GET" && path.startsWith("/static/") -> serveStatic(path.removePrefix("/static/"))
        path in known -> Reply(405, "text/plain", "Method Not Allowed")
        else -> Reply(404, "text/plain", "Not found")
    }
}
