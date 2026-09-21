// NetworkDiscovery.kt - the HTTP server (NanoHTTPD) and RiftHub, which ties
// the registry, routes, mDNS and NORA heartbeat together. Pure JVM (no Android
// imports) so it runs and is tested off-device; RiftService hosts it on a phone.
package com.example.riftcontrol

import fi.iki.elonen.NanoHTTPD

class RiftServer(port: Int, private val routes: RiftRoutes) : NanoHTTPD(port) {

    override fun serve(session: IHTTPSession): Response {
        // Read the body ourselves so JSON, form and query-less requests all work identically.
        var body = ""
        val contentType = session.headers["content-type"].orEmpty()
        if (session.method == Method.POST || session.method == Method.PUT) {
            val len = session.headers["content-length"]?.toIntOrNull() ?: 0
            if (len in 1..1_000_000) {
                val buf = ByteArray(len)
                var read = 0
                while (read < len) {
                    val n = session.inputStream.read(buf, read, len - read)
                    if (n < 0) break
                    read += n
                }
                body = String(buf, 0, read, Charsets.UTF_8)
            }
        }
        val remote = session.remoteIpAddress ?: ""
        val reply = routes.handle(session.method.name, session.uri, contentType, body, emptyMap(), remote)
        return newFixedLengthResponse(
            Response.Status.lookup(reply.status) ?: Response.Status.INTERNAL_ERROR,
            reply.contentType, reply.body.inputStream(), reply.body.size.toLong(),
        )
    }
}

class RiftHub(
    val cfg: RiftConfig,
    private val assets: RiftAssets,
    btFactory: BtLinkFactory? = null,
    private val log: (String) -> Unit = {},
) {
    val registry = RiftRegistry(cfg.ttlSecs)
    val peers = RiftPeers()
    val authority = RiftAuthority(cfg, btFactory)
    private val routes = RiftRoutes(cfg, registry, peers, authority, assets)
    private val server = RiftServer(cfg.port, routes)
    private val mdns = RiftMdns(cfg, peers, log)

    /** Returns null on success, else an error message. */
    fun start(): String? {
        try {
            server.start(NanoHTTPD.SOCKET_READ_TIMEOUT, false)
        } catch (e: Exception) {
            return e.message ?: e.toString()
        }
        log("[RIFT] ${cfg.name} listening on http://${cfg.ip}:${cfg.port}")
        if (!cfg.noMdns) {
            val err = mdns.start()
            if (err != null) log("[RIFT] mDNS disabled: $err")
        }
        authority.restart("wifi", "")
        return null
    }

    fun stop() {
        authority.stop()
        mdns.stop()
        server.stop()
    }
}
