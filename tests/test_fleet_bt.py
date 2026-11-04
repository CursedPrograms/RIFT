"""fleet_bt: a robot's web API over Bluetooth serial answers exactly as over WiFi.

A socket pair stands in for the Bluetooth link; a small HTTP server for the robot's web API."""
import json
import socket
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

from Fleet import fleet_bt


class Robot(BaseHTTPRequestHandler):
    def log_message(self, *a):
        pass

    def _send(self, code, body):
        raw = body.encode()
        self.send_response(code)
        self.send_header("Content-Length", str(len(raw)))
        self.end_headers()
        self.wfile.write(raw)

    def do_GET(self):
        if self.path.startswith("/status"):
            self._send(200, json.dumps({"mode": "web", "multi": "line one\nline two", "who": self.client_address[0]}))
        elif self.path.startswith("/web?cmd=drive"):
            self._send(200, "OK")
        else:
            self._send(404, "no")

    def do_POST(self):
        body = self.rfile.read(int(self.headers["Content-Length"])).decode()
        self._send(403 if json.loads(body).get("command") == "forward" else 200, "LOCKED" if "forward" in body else "OK")


def _robot():
    srv = ThreadingHTTPServer(("127.0.0.1", 0), Robot)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    return srv


class _SockLink(fleet_bt.BtHttp):
    """BtHttp over one end of a socket pair (no Bluetooth adapter needed)."""

    def __init__(self, sock):
        import threading as t
        self._lock = t.Lock()
        self._sock, self._ser, self._ble = sock, None, None


def test_same_answers_over_bluetooth():
    srv = _robot()
    port = srv.server_address[1]
    a, b = socket.socketpair()
    threading.Thread(target=fleet_bt.serve_stream, args=(b.recv, b.sendall, port), daemon=True).start()
    link = _SockLink(a)

    code, text = link.get("/status")
    assert code == 200
    d = json.loads(text)
    assert d["multi"] == "line one\nline two"     # a body with newlines arrives whole
    assert d["who"] == "127.0.0.1"                # to the robot, a Bluetooth controller is local

    assert link.get("/web?cmd=drive&f=1&l=0&t=0") == (200, "OK")
    assert link.post("/command", {"command": "forward"}) == (403, "LOCKED")   # the robot's rules hold
    assert link.post("/command", {"command": "stop"}) == (200, "OK")
    assert link.get("/nothing")[0] == 404
    a.close(); srv.shutdown()


def test_lines_without_the_prefix_are_left_alone():
    srv = _robot()
    a, b = socket.socketpair()
    threading.Thread(target=fleet_bt.serve_stream, args=(b.recv, b.sendall, srv.server_address[1]), daemon=True).start()
    a.sendall(b"F\nS\n")                         # an older one-letter protocol (NORA's): not ours
    link = _SockLink(a)
    assert link.get("/status")[0] == 200         # ...and the next real request still works
    a.close(); srv.shutdown()


def test_request_line():
    assert fleet_bt.request_line("get", "/status") == b">GET /status\n"
    assert fleet_bt.request_line("POST", "/action", {"a": 1}) == b'>POST /action\t{"a": 1}\n'


def test_bt_session_is_a_drop_in_for_requests():
    srv = _robot()
    a, b = socket.socketpair()
    threading.Thread(target=fleet_bt.serve_stream, args=(b.recv, b.sendall, srv.server_address[1]), daemon=True).start()
    session = fleet_bt.BtSession("unused")
    session._link = _SockLink(a)
    r = session.get("http://whip.local:5005/status", params={"ctl": "1"}, timeout=1)
    assert r.status_code == 200 and r.json()["mode"] == "web" and r.headers["content-type"] == "application/json"
    assert session.get("bt://WHIP/web", params={"cmd": "drive", "f": 1}).text == "OK"
    assert session.post("bt://KIDA00/command", json={"command": "forward"}).status_code == 403
    a.close()
    import requests
    try:
        session.get("bt://WHIP/status")          # the link is gone: requests' own error, which controllers catch
        assert False
    except requests.RequestException:
        pass
    srv.shutdown()


def test_pictures_arrive_as_bytes():
    class Pic(Robot):
        def do_GET(self):
            png = bytes(range(256)) * 4
            self.send_response(200); self.send_header("Content-Length", str(len(png))); self.end_headers(); self.wfile.write(png)
    srv = ThreadingHTTPServer(("127.0.0.1", 0), Pic)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    a, b = socket.socketpair()
    threading.Thread(target=fleet_bt.serve_stream, args=(b.recv, b.sendall, srv.server_address[1]), daemon=True).start()
    session = fleet_bt.BtSession("unused")
    session._link = _SockLink(a)
    assert session.get("bt://KIDA00/qr.png").content == bytes(range(256)) * 4
    a.close(); srv.shutdown()


def test_another_port_like_noras_fleet_list():
    web, fleet = _robot(), _robot()                 # her web API, and her fleet list on another port
    a, b = socket.socketpair()
    threading.Thread(target=fleet_bt.serve_stream, args=(b.recv, b.sendall, web.server_address[1]), daemon=True).start()
    session = fleet_bt.BtSession("unused", home_port=web.server_address[1])
    session._link = _SockLink(a)
    assert session._path(f"http://nora:{fleet.server_address[1]}/robots", None) == f":{fleet.server_address[1]}/robots"
    assert session._path(f"http://nora:{web.server_address[1]}/sensors", None) == "/sensors"
    assert session.get(f"http://nora:{fleet.server_address[1]}/status").status_code == 200   # reached the other port
    a.close(); web.shutdown(); fleet.shutdown()
