#!/usr/bin/env python3
"""
RIFT fleet dashboard — the pure-Python alternative to the native fleet
manager in `PC App/App/network-discovery.cpp` (run via ./run_server.sh).
They implement the same protocol on the same port (5000), so run one or
the other, not both, on a given machine.
"""

import io
import os
import re
import socket
import threading
import time

from flask import Flask, jsonify, render_template, request
from zeroconf import ServiceInfo, Zeroconf, ServiceBrowser

from Fleet.register import start_fleet_authority
from Fleet.internet_share import start_internet_share
from Fleet import conversations, locks, mission, music, relay, talk_mute
from Fleet.rift_board import RiftBoard
from Fleet.bt_autopair import start_autopair
from Fleet import near_map
from Fleet import fleet_net
from Fleet.fleet_near import FleetNear
from Fleet.fleet_memory import FleetMemory, Digest

# RIFT on Bluetooth LE: on a Pi it beacons as "RIFT" (a hub is always parked) and
# hears the robots; on a PC it only listens. near_map adds every robot's own view.
rift_near = FleetNear("RIFT", state="parked")

# RIFT's own Arduino (arduino/rift_link): IR transmitter, receiver and buzzer.
board = RiftBoard()
relay.board = board   # IDA over IR when NORA is away

app = Flask(__name__)

THIS_NAME = "RIFT"
THIS_PORT = 5000

# Must stay above Fleet/register.py's HEARTBEAT_SECS (10s) and match NORA's
# own FLEET_TTL_MS (esp32.ino), or a live entry/authority flaps between
# heartbeats.
FLEET_TTL_SECS = 20

# RIFT's own mDNS service, plus DREAM's dashboard's — browsing both is what lets
# DREAM show up in this dashboard without DREAM needing to know
# anything about RIFT's HTTP fleet registry below.
RIFT_ZEROCONF_TYPE      = "_rift._tcp.local."
DREAM_ZEROCONF_TYPE = "_flask-link._tcp.local."

_fleet: dict[str, dict] = {}
_fleet_lock = threading.Lock()

_peers: dict[str, str] = {}
_peers_lock = threading.Lock()

# Who hosts the fleet network. Normally RIFT is the hub: the "RIFT" router network, with RIFT at
# 192.168.4.1:5000 as THE fleet registry every robot registers with (hub/ has the setup scripts).
# RIFT_NORA_HUB=1 is the old setup: NORA hosts the network and RIFT heartbeats to her registry and
# shares internet onto her AP (Fleet/register.py, Fleet/internet_share.py).
NORA_HUB = os.environ.get("RIFT_NORA_HUB", "").strip() == "1"

# Connection Mode: "hub" (RIFT is the registry: no heartbeat to anyone), or which transport the
# fleet-authority heartbeat to NORA uses: WiFi/HTTP, or Bluetooth over Fleet/bt_link.py
# (see Fleet/register.py).
_mode_lock       = threading.Lock()
_transport_mode  = "wifi" if NORA_HUB else "hub"
_bt_port         = None
_fleet_thread    = None
_fleet_stop      = None


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


_LOOPBACK = re.compile(r"^(127\.\d+\.\d+\.\d+|::1|localhost)$")


def _for_asker(roster):
    """A program on RIFT's own PC registers as 127.0.0.1: to anyone else (a phone or RITA on RIFT's
    WiFi, the Kotlin apps) that address is themselves. Hand them the address they reached RIFT on."""
    here = request.host.rsplit(":", 1)[0].strip("[]")
    if _LOOPBACK.match(here):
        return roster
    out = []
    for r in roster:
        r = dict(r)
        if _LOOPBACK.match(str(r.get("ip", ""))):
            r["ip"] = here
        if r.get("url"):
            r["url"] = re.sub(r"//(127\.\d+\.\d+\.\d+|localhost)(?=[:/])", "//" + here, r["url"])
        out.append(r)
    return out


@app.route("/robots")
def robots():
    _prune_fleet()
    with _fleet_lock:
        roster = [
            {"name": name, "ip": m["ip"], "type": m["type"], "capabilities": m["capabilities"]}
            for name, m in _fleet.items()
        ]
    return jsonify({"authority": THIS_NAME, "robots": _for_asker(roster)})


def _fleet_snapshot():
    _prune_fleet()
    with _fleet_lock:
        return [{"name": n, "ip": m["ip"], "type": m["type"], "capabilities": m["capabilities"]} for n, m in _fleet.items()]


# ── Conversations ───────────────────────────────────────────────────────────
# The robots chatting in Brainfuck (Fleet/conversations.py): GET /talk is the
# shared log + moods; POST /talk starts one now ({"from": .., "to": ..} optional;
# {"peer": true} for DREAM and KIDA-01: rock paper scissors, then words or Brainfuck).
# POST /talk {"to": "NORA", "verb": "ask"} or {"verb": "do", "action": "music_stop"}
# asks a robot its state or tells it to do something (Fleet/relay.py).

@app.route("/talk")
def talk_log():
    return jsonify(conversations.snapshot())


# GET /talk/mute                                    every robot's two talk switches (Fleet/talk_mute.py)
# POST /talk/mute {"name": "NORA", "muted": true}     her sound: she chats, but isn't beeped ("RIFT": its buzzer)
# POST /talk/mute {"name": "NORA", "chat_off": true}  her chat: she's out of the conversations
# POST /talk/mute {"all": "muted", "on": true}        a switch for the whole fleet (newcomers too)
@app.route("/talk/mute")
def talk_mute_view():
    return jsonify(talk_mute.snapshot(conversations.talkers(_fleet_snapshot())))


@app.route("/talk/mute", methods=["POST"])
def talk_mute_set():
    data = request.get_json(silent=True) or {}
    name = str(data.get("name", "")).strip()[:24]
    if data.get("all") in talk_mute.SWITCHES and "on" in data:
        talk_mute.set_all(data["all"], bool(data["on"]))
    elif name and any(s in data for s in talk_mute.SWITCHES):
        for s in talk_mute.SWITCHES:
            if s in data:
                talk_mute.set_switch(name, s, bool(data[s]))
    else:
        return jsonify({"ok": False, "error": 'send {"name": ..., "muted" and/or "chat_off": true|false}, '
                                              'or {"all": "muted"|"chat_off", "on": true|false}'}), 400
    board.set_muted(talk_mute.muted("RIFT"))
    return jsonify(dict(talk_mute.snapshot(conversations.talkers(_fleet_snapshot())), ok=True))


# ── Music together (Fleet/music.py) ─────────────────────────────────────────
# GET /clock     RIFT's time: players set their clocks by it
# GET /music     who can play, and the last command
# POST /music    {"action": "play" | "pause" | "resume" | "stop", "track": 100}
#                ({"parts": {"NORA": 101, "TINA": 102}}: a track each)

@app.route("/clock")
def clock():
    return jsonify({"t": time.time()})


@app.route("/music")
def music_status():
    return jsonify(music.snapshot(_whole_fleet()))


@app.route("/music", methods=["POST"])
def music_now():
    data = request.get_json(silent=True) or {}
    track = data.get("track")
    out = music.conduct(_whole_fleet(), str(data.get("action", "")), int(track) if str(track).isdigit() else None,
                        data.get("parts") if isinstance(data.get("parts"), dict) else None)
    return jsonify(out), 200 if out.get("ok") else 400


# ── RIFT's own board: IR + buzzer ───────────────────────────────────────────
# GET /board                    connected? which port, the last IR frames heard
# GET /board/link?r=ida&c=fw    drive a robot over IR (same commands as NORA's /link)
# GET /board/say?r=mila&p=0     beep a phrase, then send it to that robot over IR
# GET /board/talk?u=7           beep a Brainfuck utterance (0-13) on RIFT's buzzer

# ── Who's near whom ─────────────────────────────────────────────────────────
# Every robot's /near (decoded: what they said in Brainfuck over ESP-NOW), plus
# what RIFT itself hears over Bluetooth.
@app.route("/near")
def near_view():
    return jsonify(near_map.collect(_whole_fleet(), rift_near))


@app.route("/board")
def board_status():
    return jsonify(board.status())


@app.route("/board/link")
def board_link():
    ok = board.link(request.args.get("r", ""), request.args.get("c", ""))
    return jsonify({"ok": ok}), (200 if ok else 503)


@app.route("/board/say")
def board_say():
    try:
        p = int(request.args.get("p", ""))
    except ValueError:
        return jsonify({"ok": False, "error": "p = 0-6"}), 400
    ok = board.say(request.args.get("r", ""), p)
    return jsonify({"ok": ok}), (200 if ok else 503)


@app.route("/board/talk")
def board_talk():
    try:
        u = int(request.args.get("u", ""))
    except ValueError:
        return jsonify({"ok": False, "error": "u = 0-13"}), 400
    ok = board.talk(u)
    return jsonify({"ok": ok}), (200 if ok else 503)


@app.route("/talk", methods=["POST"])
def talk_now():
    data = request.get_json(silent=True) or {}
    verb = str(data.get("verb", "say")).lower()
    if verb in ("ask", "do"):   # Fleet/relay.py: ask a robot its state, tell it to do something
        who = str(data.get("from") or "someone")[:24]
        if verb == "ask":
            code, out = relay.ask(_whole_fleet(), data.get("to"), who)
        else:
            args = {k: v for k, v in data.items() if k not in ("to", "from", "verb", "action", "confirmed")}
            code, out = relay.do(_whole_fleet(), data.get("to"), data.get("action"), args, who,
                                 confirmed=data.get("confirmed") is True)
        return jsonify(out), code
    if verb != "say":
        return jsonify({"error": "verb is say, ask or do"}), 400
    urls = conversations.talkers(_fleet_snapshot())
    urls = {n: u for n, u in urls.items() if not talk_mute.chat_off(n)}   # chat off: out of the conversations
    a, b = data.get("from"), data.get("to")
    names = list(urls)
    if data.get("peer"):   # two robots with minds: rock paper scissors, then words or Brainfuck
        minds = conversations.peers(urls)
        if len(minds) < 2:
            return jsonify({"error": "need two robots with a mind (\"peer\" capability)", "peers": minds}), 409
        a, b = (a, b) if a in minds and b in minds and a != b else minds[:2]
        threading.Thread(target=conversations.peer_converse, args=(a, b, urls), daemon=True).start()
        return jsonify({"started": True, "from": a, "to": b, "peer": True})
    if a not in urls:
        a = names[0] if names else None
    if b not in urls or b == a:
        b = next((n for n in names if n != a), None)
    if not a or not b:
        return jsonify({"error": "need two robots that can talk", "talkers": names}), 409
    threading.Thread(target=conversations.converse, args=(a, b, urls), daemon=True).start()
    return jsonify({"started": True, "from": a, "to": b})


# ── Whole fleet, for the dashboard ──────────────────────────────────────────
# Robots register with whichever registry is authority (usually NORA's), so
# the dashboard merges RIFT's own roster, NORA's and NORA herself, each with
# the address of its own web page: a "web:<port>" capability if it sends one,
# else its usual port below.
WEB_PORTS = {"NORA": 5002, "KIDA00": 5003, "KIDA01": 5004, "WHIP": 5005,
             "DREAM": 5009, "MILA": 5010, "ARM": 5011, "NINA": 5012, "NIKA": 5013, "ARIA": 5014}
HTTPS_ROBOTS = {"DREAM"}   # DREAM serves HTTPS when it has a certificate


def _web_url(name, ip, caps):
    port = next((c[4:] for c in caps if c.startswith("web:") and c[4:].isdigit()), None)
    port = port or WEB_PORTS.get(name.upper()) or next(
        (c[5:] for c in caps if c.startswith("talk:") and c[5:].isdigit()), None)
    if not port:
        return None
    scheme = "https" if name.upper() in HTTPS_ROBOTS else "http"
    return f"{scheme}://{ip}:{port}/"


def _whole_fleet():
    nora = conversations._nora()
    robots = {}
    for r in _fleet_snapshot() + nora["roster"]:
        caps = r.get("capabilities", [])
        robots[r["name"]] = {"name": r["name"], "ip": r["ip"], "type": r.get("type", "robot"),
                             "capabilities": caps, "url": _web_url(r["name"], r["ip"], caps)}
    if "NORA" in robots:            # registered with RIFT like everyone (the "RIFT" network)
        robots["NORA"]["busy"] = nora["up"] and not nora["api"]
    elif nora["up"] and nora["host"]:   # on her own fallback AP: found at her registry
        robots["NORA"] = {"name": "NORA", "ip": nora["host"], "type": "mecanum",
                          "capabilities": ["fleet_registry", "ir_link"], "url": _web_url("NORA", nora["host"], []),
                          "busy": not nora["api"]}    # "busy" = her page / API (:5002) didn't answer, last look
    return sorted(robots.values(), key=lambda r: r["name"])


@app.route("/fleet")
def fleet():
    return jsonify({"robots": _for_asker(_whole_fleet())})


# ── Every robot's wheel lock at once (Fleet/locks.py) ───────────────────────
# POST /locks {"action": "lock"}                   lock them all (no PIN)
# POST /locks {"action": "unlock", "pin": "1234"}  the fleet PIN: a person at the dashboard

@app.route("/locks")
def fleet_locks_info():   # the dashboard shows its Wheel locks section when this answers
    return jsonify({"wifi": sorted(locks.HTTP_LOCKS), "ir": list(locks.IR_LOCKS)})


@app.route("/locks", methods=["POST"])
def fleet_locks():
    data = request.get_json(silent=True) or {}
    code, out = locks.apply(_whole_fleet(), data.get("action"), data.get("pin", ""),
                            str(data.get("from") or "RIFT dashboard")[:24])
    return jsonify(out), code


# ── Mission log ─────────────────────────────────────────────────────────────
# GET /mission: the fleet's diary (Fleet/mission.py). POST /mission
# {"who": "DREAM", "text": "..."} lets a robot write its own entry.

@app.route("/mission")
def mission_log():
    return jsonify(mission.snapshot())


@app.route("/mission", methods=["POST"])
def mission_note():
    data = request.get_json(silent=True) or request.form
    who, text = (data.get("who") or "").strip(), (data.get("text") or "").strip()
    if not who or not text:
        return jsonify({"error": "need who and text"}), 400
    mission.add(who[:24], text[:280], "note")
    return jsonify({"ok": True})


# ── The fleet's memory (Hindsight, hosted by DREAM: Fleet/fleet_memory.py) ──
# RIFT keeps the mission log there too (bank "rift"), as a digest every half
# hour rather than one memory per line, so DREAM's LLM isn't kept busy. The
# Brainfuck chatter stays out of it. RIFT_MEMORY=0 turns it off.
# GET /memory                      where the memory is, and what's waiting
# GET /memory/recall?q=...&bank=   what it remembers (bank: rift, nina, tina, dream)
MEMORY = FleetMemory("rift", url=os.environ.get("RIFT_MEMORY_URL", "auto"), rift=f"http://127.0.0.1:{THIS_PORT}",
                     enabled=os.environ.get("RIFT_MEMORY", "1") != "0")
MEMORY_BANKS = ("rift", "nina", "tina", "dream")
_mission_digest = Digest(MEMORY, "RIFT's mission log: the fleet's day", every_s=1800) if MEMORY.enabled else None
if _mission_digest:
    mission.listeners.append(lambda who, text, kind: kind != "chat" and _mission_digest.add(f"{who}: {text}"))


@app.route("/memory")
def memory_status():
    return jsonify(MEMORY.status())


@app.route("/memory/recall")
def memory_recall():
    q, bank = (request.args.get("q") or "").strip(), request.args.get("bank", "rift")
    if not q:
        return jsonify({"error": "need q"}), 400
    if bank not in MEMORY_BANKS:
        return jsonify({"error": f"bank: one of {', '.join(MEMORY_BANKS)}"}), 400
    return jsonify({"bank": bank, "query": q, "memories": MEMORY.recall(q, k=6, bank=bank)})


def _watch_fleet():
    while True:
        try:
            mission.watch_roster(r["name"] for r in _whole_fleet())
        except Exception as e:
            print(f"[RIFT] mission watcher: {e}")
        time.sleep(10)


@app.route("/peers")
def peers():
    with _peers_lock:
        return jsonify(dict(_peers))


@app.route("/")
def index():
    return render_template("index.html", this_name=THIS_NAME, my_ip=MY_IP, this_port=THIS_PORT)


# ── DREAM on a call (static/js/dream_call.js) ───────────────────────────────
# When DREAM runs on another PC, RIFT's dashboard can show her live, in step with her own screen
# (her mirror on :5015: the clip she's on and how far in, her voice as she speaks), and you talk back:
# a video call. On the same PC her own window is the call, so the dashboard hides it.
# GET /dream/info    where she is, whether she's on this PC, her mirror and dashboard
# POST /dream/call   your words (audio or {"text"}) to her /api/dream/call: she answers on her own screen

DREAM_PORT, DREAM_LOCAL_PORT, DREAM_MIRROR_PORT = 5009, 5010, 5015


def _this_pc(ip):
    if not ip or ip.startswith("127.") or ip in ("localhost", "::1", MY_IP):
        return True
    try:
        return ip in socket.gethostbyname_ex(socket.gethostname())[2]
    except OSError:
        return False


def _dream_ip():
    for r in _whole_fleet():
        if r.get("name") == "DREAM" and r.get("ip"):
            return r["ip"]
    return None


@app.route("/dream/info")
def dream_info():
    ip = _dream_ip()
    if not ip:
        return jsonify({"found": False})
    same = _this_pc(ip)
    return jsonify({
        "found": True, "same_pc": same, "ip": ip,
        "mirror": f"http://{ip}:{DREAM_MIRROR_PORT}",
        # on this PC her plain-HTTP local port (no certificate warning); elsewhere her HTTPS dashboard
        "dashboard": f"http://localhost:{DREAM_LOCAL_PORT}/" if same else f"https://{ip}:{DREAM_PORT}/",
    })


@app.route("/dream/call", methods=["POST"])
def dream_call():
    import requests
    import urllib3
    urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)   # her certificate is her own
    ip = _dream_ip()
    if not ip:
        return jsonify({"error": "DREAM isn't on the fleet"}), 404
    f = request.files.get("audio")
    kw = {"files": {"audio": (f.filename or "call.webm", f.read(), f.mimetype or "audio/webm")}} if f else \
         {"json": request.get_json(silent=True) or {}}
    last = None
    for scheme in ("https", "http"):
        try:
            r = requests.post(f"{scheme}://{ip}:{DREAM_PORT}/api/dream/call", timeout=180, verify=False, **kw)
            return r.content, r.status_code, {"Content-Type": r.headers.get("Content-Type", "application/json")}
        except requests.RequestException as e:
            last = e
    return jsonify({"error": f"can't reach DREAM: {last}"}), 502


@app.route("/cameras")
def cameras():
    # A live wall of every robot's camera feed, driven by the fleet roster.
    return render_template("cameras.html", this_name=THIS_NAME, my_ip=MY_IP, this_port=THIS_PORT)


# ── Colour scheme ───────────────────────────────────────────────────────────
# colour_scheme.xml (repo root) as CSS variables, linked after styles.css, so
# editing the XML restyles the dashboard with no CSS change. Read on every
# request: an edit shows on the next page load. A missing or unreadable file
# serves an empty sheet and styles.css's built-in defaults apply.

COLOUR_SCHEME_XML = os.path.join(os.path.dirname(os.path.abspath(__file__)), "colour_scheme.xml")


@app.route("/colour_scheme.css")
def colour_scheme_css():
    try:
        with open(COLOUR_SCHEME_XML, encoding="utf-8") as f:
            pairs = re.findall(r'name="(\w+)"\s+value="(#[0-9A-Fa-f]{6})"', f.read())
    except OSError:
        pairs = []
    css = ":root {\n" + "".join(f"    --{n.replace('_', '-')}: {v};\n" for n, v in pairs) + "}\n"
    return css, 200, {"Content-Type": "text/css", "Cache-Control": "no-cache"}


# ── Connection Mode: WiFi (default) or Bluetooth heartbeat to NORA ─────────

def _restart_fleet_authority(transport, bt_port=None):
    """Stops the current heartbeat thread (if any) and starts a new one on
    the given transport. Caller must hold _mode_lock."""
    global _fleet_thread, _fleet_stop
    if _fleet_stop is not None:
        _fleet_stop.set()
        _fleet_thread.join(timeout=2)
        _fleet_thread = _fleet_stop = None
    if transport == "hub":          # RIFT is the registry itself: nobody to announce to
        return
    _fleet_thread, _fleet_stop = start_fleet_authority(
        name=THIS_NAME,
        capabilities=["fleet_management", "monitoring"],
        transport=transport,
        bt_port=bt_port,
    )


@app.route("/mode")
def get_mode():
    with _mode_lock:
        return jsonify({"mode": _transport_mode, "bt_port": _bt_port})


@app.route("/mode", methods=["POST"])
def set_mode():
    global _transport_mode, _bt_port
    data = request.get_json(silent=True) or request.form
    mode = (data.get("mode") or "").strip().lower()
    if mode not in ("hub", "wifi", "bluetooth"):
        return jsonify({"error": "mode must be 'hub', 'wifi' or 'bluetooth'"}), 400

    bt_port = (data.get("bt_port") or "").strip() or None
    if mode == "bluetooth" and not bt_port:
        return jsonify({"error": "bt_port is required for Bluetooth mode"}), 400

    with _mode_lock:
        try:
            _restart_fleet_authority(mode, bt_port)
        except Exception as e:
            return jsonify({"error": str(e)}), 500
        _transport_mode = mode
        _bt_port = bt_port
        return jsonify({"mode": _transport_mode, "bt_port": _bt_port})


# ── The network devices: which one is the internet, which one carries the fleet (Fleet/fleet_net.py)

@app.route("/network")
def get_network():
    return jsonify(fleet_net.status())


@app.route("/qr.svg")
def qr_svg():
    """A QR code for RIFT's side: ?for=wifi joins the fleet WiFi, ?for=page opens this page."""
    import segno
    if request.args.get("for") == "wifi":
        text = f"WIFI:T:WPA;S:{fleet_net.FLEET_SSID};P:{fleet_net.FLEET_PASSWORD};;"
    else:
        text = request.args.get("url") or f"http://{MY_IP}:{THIS_PORT}/"
    buf = io.BytesIO()
    segno.make(text, error="m").save(buf, kind="svg", scale=6, border=2, dark="#000000", light="#ffffff")
    return app.response_class(buf.getvalue(), mimetype="image/svg+xml", headers={"Cache-Control": "no-store"})


@app.route("/network", methods=["POST"])
def set_network():
    data = request.get_json(silent=True) or request.form
    if data.get("internet") or data.get("fleet"):
        ok, msg = fleet_net.choose((data.get("internet") or "").strip(), (data.get("fleet") or "").strip())
        if not ok:
            return jsonify({"error": msg}), 400
    if "broadcast" in data:
        ok, msg = fleet_net.broadcast(str(data.get("broadcast")).lower() in ("1", "true", "on"))
        if not ok:
            return jsonify({"error": msg}), 409
    else:
        msg = "saved"
    out = fleet_net.status()
    out["message"] = msg
    return jsonify(out)


# ── Zeroconf: publish self, watch for RIFT and DREAM peers ─────────────

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
    ServiceBrowser(zc, DREAM_ZEROCONF_TYPE, listener)
    return zc, info


if __name__ == "__main__":
    print(f"[RIFT] IP   : {MY_IP}")
    print(f"[RIFT] Port : {THIS_PORT}")

    _zc_instance = _zc_info = None
    try:       # optional: the robots find RIFT at 192.168.4.1 anyway (no multicast on some networks)
        _zc_instance, _zc_info = _start_zeroconf()
        print(f"[RIFT] Zeroconf registered as {THIS_NAME}; "
              f"watching {RIFT_ZEROCONF_TYPE} and {DREAM_ZEROCONF_TYPE}")
    except Exception as e:
        print(f"[RIFT] Zeroconf unavailable ({type(e).__name__}: {e}); carrying on without it")

    with _mode_lock:
        _restart_fleet_authority(_transport_mode)
    fleet_net.keep_broadcasting()   # the fleet's WiFi, RIFT, on the chosen device (Fleet/fleet_net.py)
    if NORA_HUB:
        print(f"[RIFT] NORA is the hub (RIFT_NORA_HUB=1): announcing to her as fleet authority "
              f"(mode: {_transport_mode})")
        start_internet_share()
        print("[RIFT] Internet-share to NORA's AP started")
    else:
        print(f"[RIFT] RIFT is the hub: the fleet registry at {MY_IP}:{THIS_PORT} "
              f"(the robots expect 192.168.4.1; set RIFT_NORA_HUB=1 if NORA hosts the network)")

    conversations.start(_fleet_snapshot, board=board)
    board.start()   # looks for its own Arduino after 25 s, on ports nobody else has open
    start_autopair()   # pairs with NORA (and any fleet robot) over Bluetooth; skips if there's no radio
    rift_near.start()  # who's near RIFT over Bluetooth LE (needs bleak; beacons too on a Pi)
    threading.Thread(target=_watch_fleet, daemon=True, name="mission-watcher").start()
    print(f"[RIFT] Mission log: {mission.PATH} (day {mission.day()})")
    print("[RIFT] Fleet conversations started (Brainfuck chirps, see /talk)")

    try:
        app.run(host="0.0.0.0", port=THIS_PORT, debug=False, use_reloader=False, threaded=True)
    finally:
        if _zc_instance is not None:
            _zc_instance.unregister_service(_zc_info)
            _zc_instance.close()
            print("[RIFT] Zeroconf unregistered.")
