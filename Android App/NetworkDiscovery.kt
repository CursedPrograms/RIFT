import fi.iki.elonen.NanoHTTPD

class RiftServer(port: Int) : NanoHTTPD(port) {

    override fun serve(session: IHTTPSession): Response {
        return when (session.uri) {
            "/ping" -> newFixedLengthResponse("RIFT alive")

            "/" -> {
                val html = """
                    <html>
                        <body style="text-align:center;">
                            <h1>RIFT Active</h1>
                            <script>
                                setTimeout(() => location.reload(), 3000);
                            </script>
                        </body>
                    </html>
                """.trimIndent()

                newFixedLengthResponse(html)
            }

            else -> newFixedLengthResponse("Not Found")
        }
    }
}