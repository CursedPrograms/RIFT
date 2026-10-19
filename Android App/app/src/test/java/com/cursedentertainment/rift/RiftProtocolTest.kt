// RiftProtocolTest.kt - the phone hub's core on a plain JVM, over real HTTP: the same
// wire protocol as app.py (registry, dashboard, /fleet, /talk ask / do with relay.py's
// safety tiers), against RIFT's own templates/ and static/. Run: gradlew test
package com.cursedentertainment.rift

import fi.iki.elonen.NanoHTTPD
import org.json.JSONObject
import org.junit.AfterClass
import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertTrue
import org.junit.BeforeClass
import org.junit.Test
import java.io.File
import java.net.HttpURLConnection
import java.net.ServerSocket
import java.net.URL

/** RIFT's templates/ and static/, read from the repo (this project is RIFT/Android App). */
class RepoAssets(private val rift: File) : RiftAssets {
    override fun template() = page("index.html")
    override fun staticFile(rel: String) = File(rift, "static/$rel").takeIf { it.isFile }?.readBytes()
    override fun page(name: String) = File(rift, "templates/$name").takeIf { it.isFile }?.readText()
    override fun colours() = File(rift, "colour_scheme.xml").takeIf { it.isFile }?.readText()
}

/** A robot with its own /status and POST /do, recording what it was told. */
class FakeRobot(port: Int) : NanoHTTPD("127.0.0.1", port) {
    @Volatile var lastDo: JSONObject? = null
    @Volatile var refuse = false

    override fun serve(session: IHTTPSession): Response {
        if (session.uri == "/status")
            return newFixedLengthResponse(Response.Status.OK, "application/json", """{"mode":"manual","moving":false,"music":"playing"}""")
        if (session.uri == "/do" && session.method == Method.POST) {
            val len = session.headers["content-length"]?.toIntOrNull() ?: 0
            val buf = ByteArray(len)
            var read = 0
            while (read < len) read += session.inputStream.read(buf, read, len - read).coerceAtLeast(1)
            lastDo = JSONObject(String(buf))
            return newFixedLengthResponse(Response.Status.OK, "application/json", if (refuse) """{"ok":false}""" else """{"ok":true}""")
        }
        return newFixedLengthResponse(Response.Status.NOT_FOUND, "text/plain", "Not found")
    }
}

class RiftProtocolTest {
    companion object {
        private fun freePort() = ServerSocket(0).use { it.localPort }
        private val rift = File(System.getProperty("user.dir")).resolve("../..").canonicalFile   // app/ -> RIFT/
        private val port = freePort()
        private val robotPort = freePort()
        private lateinit var hub: RiftHub
        private lateinit var robot: FakeRobot

        @BeforeClass @JvmStatic fun start() {
            hub = RiftHub(RiftConfig(name = "RIFT", port = port, ip = "127.0.0.1", noMdns = true, noHeartbeat = true), RepoAssets(rift))
            assertEquals(null, hub.start())
            robot = FakeRobot(robotPort).apply { start(NanoHTTPD.SOCKET_READ_TIMEOUT, false) }
        }

        @AfterClass @JvmStatic fun stop() { hub.stop(); robot.stop() }
    }

    private class Res(val code: Int, val type: String, val body: String) {
        val json get() = JSONObject(body)
    }

    private fun call(method: String, path: String, body: String? = null, type: String = "application/json"): Res {
        val c = URL("http://127.0.0.1:$port$path").openConnection() as HttpURLConnection
        c.requestMethod = method
        if (body != null) {
            c.doOutput = true
            c.setRequestProperty("Content-Type", type)
            c.outputStream.use { it.write(body.toByteArray()) }
        }
        val code = c.responseCode
        val text = (if (code < 400) c.inputStream else c.errorStream)?.use { it.readBytes().toString(Charsets.UTF_8) }.orEmpty()
        return Res(code, c.contentType.orEmpty(), text)
    }

    private fun form(path: String, body: String) = call("POST", path, body, "application/x-www-form-urlencoded")

    private fun registerRobot() {
        assertEquals(200, form("/register", "name=TESTBOT&type=tank&capabilities=web:$robotPort,do:music_stop,do:forward&ip=127.0.0.1").code)
    }

    // ── the fleet registry (same as app.py and NORA) ──
    @Test fun ping() = call("GET", "/ping").let { assertEquals(200, it.code); assertEquals("RIFT alive", it.body) }

    @Test fun registerFormAndRobots() {
        assertEquals("OK", form("/register", "name=KIDA00&type=tank&capabilities=camera,music").body)
        val r = call("GET", "/robots").json
        assertEquals("RIFT", r.getString("authority"))
        val kida = (0 until r.getJSONArray("robots").length()).map { r.getJSONArray("robots").getJSONObject(it) }.first { it.getString("name") == "KIDA00" }
        assertEquals("tank", kida.getString("type"))
        assertEquals(listOf("camera", "music"), (0 until 2).map { kida.getJSONArray("capabilities").getString(it) })
    }

    @Test fun registerJsonWithCapabilityArray() {
        assertEquals(200, call("POST", "/register", """{"name":"JSONBOT","type":"arm","capabilities":["a","b"]}""").code)
        assertTrue(call("GET", "/robots").body.contains("\"JSONBOT\""))
    }

    @Test fun registerWithoutNameIs400() = assertEquals(400, form("/register", "type=tank").code)
    @Test fun peersIsAnObject() = assertEquals(200, call("GET", "/peers").code)

    // ── connection mode: hub by default, like app.py ──
    @Test fun modeDefaultsToHubAndChecksInput() {
        assertEquals(400, call("POST", "/mode", """{"mode":"carrier pigeon"}""").code)
        assertEquals(400, call("POST", "/mode", """{"mode":"bluetooth"}""").code)
        assertEquals("wifi", call("POST", "/mode", """{"mode":"wifi"}""").json.getString("mode"))
        assertEquals("hub", call("POST", "/mode", """{"mode":"hub"}""").json.getString("mode"))
        assertEquals("hub", call("GET", "/mode").json.getString("mode"))
    }

    // ── the dashboard, from RIFT's own templates/ and static/ ──
    @Test fun dashboardRendersTheTemplate() {
        val r = call("GET", "/")
        assertEquals(200, r.code)
        assertTrue(r.body.contains("/static/css/styles.css"))
        assertFalse(r.body.contains("{{"))
    }

    @Test fun camerasPage() = assertEquals(200, call("GET", "/cameras").code)
    @Test fun staticFile() = call("GET", "/static/css/styles.css").let { assertEquals(200, it.code); assertTrue(it.type.startsWith("text/css")) }
    @Test fun staticRefusesEscapes() = assertEquals(404, call("GET", "/static/../app.py").code)
    @Test fun unknownIs404() = assertEquals(404, call("GET", "/nope").code)
    @Test fun wrongMethodIs405() = assertEquals(405, call("GET", "/register").code)

    @Test fun colourScheme() = call("GET", "/colour_scheme.css").let {
        assertEquals(200, it.code)
        assertTrue(it.body.startsWith(":root {"))
        assertTrue(it.body.contains("--background: #"))
        assertTrue(it.body.contains("--text-sec: #"))       // "_" written as "-"
    }

    @Test fun clockIsNow() = assertTrue(Math.abs(call("GET", "/clock").json.getDouble("t") - System.currentTimeMillis() / 1000.0) < 5)

    // ── /fleet: robots with their own page's address ──
    @Test fun fleetHasWebUrls() {
        form("/register", "name=KIDA00&type=tank&capabilities=camera")
        form("/register", "name=NOPAGE&type=thing&capabilities=x")
        registerRobot()
        val robots = call("GET", "/fleet").json.getJSONArray("robots")
        val byName = (0 until robots.length()).associate { robots.getJSONObject(it).let { r -> r.getString("name") to r } }
        assertTrue(byName.getValue("KIDA00").getString("url").endsWith(":5003/"))            // app.py's WEB_PORTS
        assertEquals("http://127.0.0.1:$robotPort/", byName.getValue("TESTBOT").getString("url"))   // web:<port>
        assertTrue(byName.getValue("NOPAGE").isNull("url"))
        val names = (0 until robots.length()).map { robots.getJSONObject(it).getString("name") }
        assertEquals(names.sorted(), names)
    }

    // ── POST /talk ask / do: relay.py's tiers ──
    @Test fun sayIsForRiftsPc() = assertEquals(501, call("POST", "/talk", "{}").code)
    @Test fun askNobodyIs404() = assertEquals(404, call("POST", "/talk", """{"verb":"ask","to":"GHOST"}""").code)

    @Test fun askRelaysStatusAndDoes() {
        registerRobot()
        val r = call("POST", "/talk", """{"verb":"ask","to":"testbot"}""")
        assertEquals(200, r.code)
        val j = r.json
        assertEquals("TESTBOT", j.getString("to"))
        assertEquals("manual", j.getJSONObject("core").getString("mode"))
        assertEquals("playing", j.getJSONObject("core").getString("music"))
        assertEquals(listOf("music_stop", "forward"), (0 until 2).map { j.getJSONArray("does").getString(it) })
    }

    @Test fun neverRelaysUnlocking() {
        registerRobot()
        val r = call("POST", "/talk", """{"verb":"do","to":"TESTBOT","action":"unlock","confirmed":true}""")
        assertEquals(403, r.code)
        assertEquals("never", r.json.getString("tier"))
    }

    @Test fun movingNeedsAPersonsYes() {
        registerRobot()
        val r = call("POST", "/talk", """{"verb":"do","to":"TESTBOT","action":"forward","seconds":1}""")
        assertEquals(403, r.code)
        assertEquals("confirmed", r.json.getString("needs"))
    }

    @Test fun cantDoWhatItDoesntList() {
        registerRobot()
        val r = call("POST", "/talk", """{"verb":"do","to":"TESTBOT","action":"lights_on"}""")
        assertEquals(400, r.code)
        assertTrue(r.json.getString("error").contains("can't lights_on"))
    }

    @Test fun doNeedsAnAction() = assertEquals(400, call("POST", "/talk", """{"verb":"do","to":"TESTBOT"}""").code)

    @Test fun harmlessDoGoesToTheRobot() {
        registerRobot()
        robot.refuse = false
        val r = call("POST", "/talk", """{"verb":"do","to":"TESTBOT","action":"music_stop","from":"test"}""")
        assertEquals(200, r.code)
        assertTrue(r.json.getBoolean("ok"))
        assertEquals("music_stop", robot.lastDo!!.getString("action"))
        assertFalse(robot.lastDo!!.has("from"))                 // the relay's own fields stay with the relay
    }

    @Test fun confirmedMoveGoesWithItsSeconds() {
        registerRobot()
        robot.refuse = false
        val r = call("POST", "/talk", """{"verb":"do","to":"TESTBOT","action":"forward","seconds":1.5,"confirmed":true}""")
        assertEquals(200, r.code)
        assertEquals(1.5, robot.lastDo!!.getDouble("seconds"), 0.0)
        assertFalse(robot.lastDo!!.has("confirmed"))
    }

    @Test fun robotSayingNoIsNotOk() {
        registerRobot()
        robot.refuse = true
        val r = call("POST", "/talk", """{"verb":"do","to":"TESTBOT","action":"music_stop"}""")
        robot.refuse = false
        assertFalse(r.json.getBoolean("ok"))
    }

    // ── pieces without the server ──
    @Test fun registryForgetsSilentRobots() {
        val reg = RiftRegistry(20.0)
        reg.add("OLD", "1.2.3.4", "tank", emptyList(), nowNanos = 0)
        reg.add("NEW", "1.2.3.5", "tank", emptyList(), nowNanos = 15_000_000_000)
        assertEquals(listOf("NEW"), reg.robots(nowNanos = 25_000_000_000).map { it.name })
    }

    @Test fun tiersMatchRelayPy() {
        assertEquals("harmless", RiftRelay.tier("music_stop"))
        assertEquals("moving", RiftRelay.tier("forward"))
        assertEquals("moving", RiftRelay.tier("something_new"))       // unknown counts as moving
        assertEquals("never", RiftRelay.tier("motorlock_off"))
        assertEquals("never", RiftRelay.tier("reboot"))
    }

    @Test fun templateUrlFor() =
        assertEquals("/static/js/main.js", renderTemplate("{{ url_for('static', filename='js/main.js') }}", emptyMap()))
}
