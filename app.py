#!/usr/bin/env python3
"""
RIFT fleet dashboard — the pure-Python alternative to the native fleet
manager in `PC App/App/network-discovery.cpp` (run via ./run_server.sh).
They implement the same protocol on the same port (5000), so run one or
the other, not both, on a given machine.
"""

import socket
import threading
import time

from flask import Flask, jsonify, render_template, request
from zeroconf import ServiceInfo, Zeroconf, ServiceBrowser

from Fleet.register import start_fleet_authority
from Fleet.internet_share import start_internet_share

app = Flask(__name__)

THIS_NAME = "RIFT"
THIS_PORT = 5000

# Must stay above Fleet/register.py's HEARTBEAT_SECS (10s) and match NORA's
# own FLEET_TTL_MS (esp32.ino), or a live entry/authority flaps between
# heartbeats.
FLEET_TTL_SECS = 20

# RIFT's own mDNS service, plus ComCentre's — browsing both is what lets
# DREAM show up in this dashboard without ComCentre needing to know
# anything about RIFT's HTTP fleet registry below.
RIFT_ZEROCONF_TYPE      = "_rift._tcp.local."
COMCENTRE_ZEROCONF_TYPE = "_flask-link._tcp.local."

_fleet: dict[str, dict] = {}
_fleet_lock = threading.Lock()

_peers: dict[str, str] = {}
_peers_lock = threading.Lock()


def _get_ip():
    s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        s.connect(("10.255.255.255", 1))
        return s.getsockname()[0]
    except Exception:
        return "127.0.0.1"
    finally:
        s.close()


MY_IP = _get_ip()


def _prune_fleet():
    now = time.time()
    with _fleet_lock:
        stale = [name for name, m in _fleet.items() if now - m["last_seen"] > FLEET_TTL_SECS]
        for name in stale:
            del _fleet[name]


# ── HTTP fleet registry ─────────────────────────────────────────────────────
# Same wire protocol as NORA's fleet server (NORA-Robot-v00's
# scripts/esp32/esp32.ino, setupFleetServer()) so registration.cpp and
# PC App/PyGame/registration.py can scan either node with one parser.

@app.route("/ping")
def ping():
    return f"{THIS_NAME} alive", 200, {"Content-Type": "text/plain"}


@app.route("/register", methods=["POST"])
def register():
    name = request.form.get("name")
    if not name:
        return "missing name", 400
    fleet_type = request.form.get("type", "unknown")
    caps = [c for c in request.form.get("capabilities", "").split(",") if c]
    with _fleet_lock:
        _fleet[name] = {
            "ip": request.remote_addr,
            "type": fleet_type,
            "capabilities": caps,
            "last_seen": time.time(),
        }
    return "OK"


@app.route("/robots")
def robots():
    _prune_fleet()
    with _fleet_lock:
        roster = [
            {"name": name, "ip": m["ip"], "type": m["type"], "capabilities": m["capabilities"]}
            for name, m in _fleet.items()
        ]
    return jsonify({"authority": THIS_NAME, "robots": roster})


@app.route("/peers")
def peers():
    with _peers_lock:
        return jsonify(dict(_peers))


@app.route("/")
def index():
    return render_template("index.html", this_name=THIS_NAME, my_ip=MY_IP, this_port=THIS_PORT)


# ── Zeroconf: publish self, watch for RIFT and ComCentre peers ─────────────

class _PeerListener:
    def remove_service(self, zc, type_, name):
        short = name.split(".")[0]
        with _peers_lock:
            _peers.pop(short, None)

    def add_service(self, zc, type_, name):
        self.update_service(zc, type_, name)

    def update_service(self, zc, type_, name):
        info = zc.get_service_info(type_, name)
        if info and info.addresses:
            short = name.split(".")[0]
            if short != THIS_NAME:
                addr = socket.inet_ntoa(info.addresses[0])
                with _peers_lock:
                    _peers[short] = f"http://{addr}:{info.port}"


def _start_zeroconf():
    zc = Zeroconf()
    info = ServiceInfo(
        RIFT_ZEROCONF_TYPE,
        f"{THIS_NAME}.{RIFT_ZEROCONF_TYPE}",
        addresses=[socket.inet_aton(MY_IP)],
        port=THIS_PORT,
        properties={"role": "fleet_manager"},
    )
    zc.register_service(info)
    listener = _PeerListener()
    ServiceBrowser(zc, RIFT_ZEROCONF_TYPE, listener)
    ServiceBrowser(zc, COMCENTRE_ZEROCONF_TYPE, listener)
    return zc, info


if __name__ == "__main__":
    print(f"[RIFT] IP   : {MY_IP}")
    print(f"[RIFT] Port : {THIS_PORT}")

    _zc_instance, _zc_info = _start_zeroconf()
    print(f"[RIFT] Zeroconf registered as {THIS_NAME}; "
          f"watching {RIFT_ZEROCONF_TYPE} and {COMCENTRE_ZEROCONF_TYPE}")

    start_fleet_authority(name=THIS_NAME, capabilities=["fleet_management", "monitoring"])
    print("[RIFT] Announcing to NORA as fleet authority")

    start_internet_share()
    print("[RIFT] Internet-share to NORA's AP started")

    try:
        app.run(host="0.0.0.0", port=THIS_PORT, debug=False, use_reloader=False, threaded=True)
    finally:
        _zc_instance.unregister_service(_zc_info)
        _zc_instance.close()
        print("[RIFT] Zeroconf unregistered.")
