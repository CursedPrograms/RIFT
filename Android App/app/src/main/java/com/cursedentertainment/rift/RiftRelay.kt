// RiftRelay.kt - the phone hub's /fleet and the "ask" / "do" verbs of POST /talk:
// the Kotlin counterpart of app.py's _whole_fleet() and Fleet/relay.py, for robots
// that registered with this hub. Pure JVM (no Android imports), so it's tested off-device.
//
// Same safety tiers as relay.py: harmless actions go ahead, anything else may move the
// robot and needs "confirmed": true (a person said yes), and nothing that unlocks or
// powers a robot down is ever relayed. relay.py also maps actions onto the APIs of
// robots without their own POST /do (NORA's web API, KIDA00's Flask...); the phone
// relays only to robots that registered "do:<action>" capabilities.
package com.cursedentertainment.rift

import org.json.JSONObject
import org.json.JSONTokener
import java.net.HttpURLConnection
import java.net.URL

/** (HTTP status, body) for a GET (body null) or a JSON POST. */
typealias HttpCall = (method: String, url: String, body: String?) -> Pair<Int, String>

fun httpCall(method: String, url: String, body: String?): Pair<Int, String> {
    val conn = URL(url).openConnection() as HttpURLConnection
    conn.connectTimeout = 3000
    conn.readTimeout = 6000
    conn.requestMethod = method
    if (body != null) {
        conn.doOutput = true
        conn.setRequestProperty("Content-Type", "application/json")
        conn.outputStream.use { it.write(body.toByteArray(Charsets.UTF_8)) }
    }
    val code = conn.responseCode
    val text = (if (code < 400) conn.inputStream else conn.errorStream)?.use { it.readBytes().toString(Charsets.UTF_8) }.orEmpty()
    conn.disconnect()
    return Pair(code, text)
}

class RiftRelay(private val registry: RiftRegistry, private val http: HttpCall = ::httpCall) {
    companion object {
        // app.py's WEB_PORTS: where each robot's own web page is, unless it registers "web:<port>"
        val WEB_PORTS = mapOf("NORA" to 5002, "KIDA00" to 5003, "KIDA01" to 5004, "WHIP" to 5005,
                              "DREAM" to 5009, "MILA" to 5010, "ARM" to 5011, "NINA" to 5012)
        val HTTPS_ROBOTS = setOf("DREAM")
        val HARMLESS = setOf("stop", "status", "scan", "lock_wheels", "photo", "sleep", "wake", "dance_stop", "manual_mode",
                             "music_play", "music_next", "music_prev", "music_stop", "music_pause", "music_resume",
                             "uv_on", "uv_off", "uv_blink", "lights_on", "lights_off", "sound", "chirp")
        val NEVER = Regex("""unlock|password|pin\b|motor_?lock_?off|shutdown|reboot|flash""", RegexOption.IGNORE_CASE)
        const val PHONE_NOTE = "the phone hub relays only to robots with their own POST /do; RIFT's PC maps the others"

        fun tier(action: String) = when {
            NEVER.containsMatchIn(action) -> "never"
            action in HARMLESS -> "harmless"
            else -> "moving"
        }

        fun webUrl(r: Robot): String? {
            val port = r.capabilities.firstOrNull { it.startsWith("web:") && it.drop(4).all(Char::isDigit) }?.drop(4)
                ?: WEB_PORTS[r.name.uppercase()]?.toString()
                ?: r.capabilities.firstOrNull { it.startsWith("talk:") && it.drop(5).all(Char::isDigit) }?.drop(5)
                ?: return null
            val scheme = if (r.name.uppercase() in HTTPS_ROBOTS) "https" else "http"
            return "$scheme://${r.ip}:$port/"
        }

        fun does(r: Robot) = r.capabilities.filter { it.startsWith("do:") }.map { it.removePrefix("do:") }
    }

    /** GET /fleet: every robot registered here, with its own web page's address. */
    fun fleetJson(): String = J.obj("robots" to J.arr(registry.robots().sortedBy { it.name }.map { r ->
        J.obj("name" to J.str(r.name), "ip" to J.str(r.ip), "type" to J.str(r.type),
              "capabilities" to J.arr(r.capabilities.map { J.str(it) }),
              "url" to (webUrl(r)?.let { J.str(it) } ?: "null"))
    }))

    private fun find(name: String?) = registry.robots().firstOrNull { it.name.equals(name ?: "", ignoreCase = true) }

    private fun missing(name: String?) =
        "${name ?: "(nobody)"} isn't registered with this hub" +
            registry.robots().joinToString(", ", prefix = " (online: ", postfix = ")") { it.name }.let { if (registry.robots().isEmpty()) "" else it }

    /** The fields every robot's answer has: mode, moving, music, distances_cm (null where it doesn't say). */
    private fun core(name: String, status: Any?): String {
        val s = status as? JSONObject ?: JSONObject()
        val mode = s.opt("mode")?.takeIf { it != JSONObject.NULL }?.toString()
        val moving = (s.opt("moving") as? Boolean)?.toString() ?: "null"
        val music = when {
            s.opt("music") is String -> s.getString("music")
            s.opt("music_playing") is Boolean -> if (s.getBoolean("music_playing")) "playing" else "stopped"
            else -> null
        }
        val dist = (s.optJSONObject("distances_cm") ?: JSONObject()).let { d ->
            J.obj(*d.keys().asSequence().map { it to d.get(it).toString() }.toList().toTypedArray())
        }
        return J.obj("name" to J.str(name), "mode" to (mode?.let { J.str(it) } ?: "null"), "moving" to moving,
                     "music" to (music?.let { J.str(it) } ?: "null"), "distances_cm" to dist)
    }

    /** POST /talk with "verb": "ask" or "do" -> (status, JSON). "say" (conversations) is RIFT's PC's. */
    fun talk(body: String): Pair<Int, String> {
        val data = try { JSONObject(body.ifBlank { "{}" }) } catch (_: Exception) { JSONObject() }
        return when (data.optString("verb", "say").lowercase()) {
            "ask" -> ask(data.optString("to", ""))
            "do" -> doAction(data)
            else -> Pair(501, J.obj("error" to J.str("robot conversations run on RIFT's PC; the phone hub takes verb ask or do")))
        }
    }

    fun ask(name: String): Pair<Int, String> {
        val r = find(name) ?: return Pair(404, J.obj("ok" to "false", "error" to J.str(missing(name))))
        val base = webUrl(r)?.trimEnd('/')
            ?: return Pair(502, J.obj("ok" to "false", "to" to J.str(r.name), "error" to J.str("no web address for ${r.name}")))
        val url = base + if (r.name.equals("NORA", true)) "/sensors" else "/status"   // NORA's status page, as in relay.py
        val (code, text) = try { http("GET", url, null) } catch (e: Exception) {
            return Pair(502, J.obj("ok" to "false", "to" to J.str(r.name), "error" to J.str("no answer from $url: ${e.javaClass.simpleName}")))
        }
        val status = try { JSONTokener(text).nextValue() } catch (_: Exception) { null }
        val actions = does(r)
        val fields = mutableListOf("ok" to (code < 400).toString(), "to" to J.str(r.name), "core" to core(r.name, status),
            "status" to (if (status is JSONObject) status.toString() else "null"),
            "does" to J.arr(actions.map { J.str(it) }), "via" to J.str("robot"))
        if (actions.isEmpty()) fields += "note" to J.str(PHONE_NOTE)
        return Pair(if (code < 400) 200 else 502, J.obj(*fields.toTypedArray()))
    }

    fun doAction(data: JSONObject): Pair<Int, String> {
        val action = data.optString("action", "").trim().lowercase()
        val name = data.optString("to", "")
        if (action.isEmpty()) return Pair(400, J.obj("ok" to "false", "error" to J.str("do needs an action")))
        val r = find(name) ?: return Pair(404, J.obj("ok" to "false", "error" to J.str(missing(name))))
        val level = tier(action)
        if (level == "never")
            return Pair(403, J.obj("ok" to "false", "to" to J.str(r.name), "tier" to J.str(level),
                "error" to J.str("never relayed: unlocking or powering a robot down is for a person at the robot")))
        if (level == "moving" && data.optBoolean("confirmed", false) != true)
            return Pair(403, J.obj("ok" to "false", "to" to J.str(r.name), "tier" to J.str(level), "needs" to J.str("confirmed"),
                "error" to J.str("$action can move ${r.name}: get a person's yes, then send \"confirmed\": true")))
        val actions = does(r)
        if (action !in actions)
            return Pair(400, J.obj("ok" to "false", "to" to J.str(r.name), "does" to J.arr(actions.map { J.str(it) }),
                "error" to J.str("${r.name} can't $action" + if (actions.isNotEmpty()) "; she can: ${actions.joinToString()}" else " ($PHONE_NOTE)")))
        val base = webUrl(r)?.trimEnd('/')
            ?: return Pair(502, J.obj("ok" to "false", "to" to J.str(r.name), "error" to J.str("no web address for ${r.name}")))
        // Everything the request carried except the relay's own fields goes to the robot, as relay.py does
        val forward = JSONObject()
        for (key in data.keys()) if (key !in setOf("to", "from", "verb", "confirmed")) forward.put(key, data.get(key))
        forward.put("action", action)
        val (code, text) = try { http("POST", "$base/do", forward.toString()) } catch (e: Exception) {
            return Pair(502, J.obj("ok" to "false", "to" to J.str(r.name), "action" to J.str(action), "error" to J.str("no answer: ${e.javaClass.simpleName}")))
        }
        val answer = try { JSONTokener(text).nextValue() } catch (_: Exception) { text }
        val ok = code < 400 && !(answer is JSONObject && answer.opt("ok") == false)
        val answerJson = when (answer) { is JSONObject -> answer.toString(); is String -> J.str(answer); else -> J.str(text) }
        return Pair(if (ok) 200 else if (code in 400..499) code else 502,
            J.obj("ok" to ok.toString(), "to" to J.str(r.name), "action" to J.str(action), "tier" to J.str(level),
                  "via" to J.str("robot"), "answer" to answerJson))
    }
}
