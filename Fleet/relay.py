"""relay.py - ask any robot its state, tell any robot to do something, through RIFT.

Three verbs for the whole fleet (TODO.md section 1); this is ask and do:

    POST /talk {"to": "NORA", "verb": "ask"}
    POST /talk {"to": "NORA", "verb": "do", "action": "music_stop"}
    POST /talk {"to": "NORA", "verb": "do", "action": "forward", "seconds": 1, "confirmed": true}

ask  GETs the robot's /status (NORA's is /sensors) and says what it can do.
do   POSTs {"action", ...} to the robot's /do if it registered "do:<action>"
     capabilities (one per action, e.g. "do:music_stop"); robots without /do yet
     get RIFT's own mapping onto the API they already have (ADAPTERS: NORA, KIDA00, ARM, and IDA
     over IR through NORA or RIFT's own board).
     Every ask answer has "core": mode, moving, music, distances_cm, the same for all.

Safety tiers: harmless actions go ahead; anything else may move the robot, so the
asker must have a person's yes and send "confirmed": true; and nothing that unlocks
a robot (MILA's PIN, NORA's wheel lock) is ever relayed. Every exchange goes in the
mission log.
"""
import json
import re
import time
import urllib.error
import urllib.request

from Fleet import mission

TIMEOUT_S = 6
MAX_DRIVE_S = 3.0      # a timed drive never runs longer than this

HARMLESS = {"stop", "status", "scan", "lock_wheels", "photo", "sleep", "wake", "dance_stop", "manual_mode",
            "music_play", "music_next", "music_prev", "music_stop", "music_pause", "music_resume",
            "uv_on", "uv_off", "uv_blink", "lights_on", "lights_off", "sound", "chirp"}
NEVER = re.compile(r"unlock|password|pin\b|motorlock_?off|shutdown|reboot|flash", re.I)

# Robots that don't take POST /do yet: RIFT maps the actions onto their own API.
# A route is "/path" (GET) or ("/path", {json}) (POST). An action is a route,
# {"go": route, "then": route} for a timed move (go, wait "seconds", then), or
# {"route": route, "skip_if": (key, value)} to skip it when the status already says so.
ADAPTERS = {
    "NORA": {
        "status": "/sensors",
        "does": {
            # M:PLAY toggles on her music board: pressed while playing it pauses
            "music_play": {"route": "/muPlay", "skip_if": ("ms", 1)},
            "music_next": "/muNext", "music_prev": "/muPrev", "music_stop": "/muStop",
            "uv_on": "/uvOn", "uv_off": "/uvOff", "uv_blink": "/uvBlink",
            "stop": "/stop", "lock_wheels": "/motorlockOn",
            "forward": {"go": "/fw", "then": "/stop"}, "back": {"go": "/bw", "then": "/stop"},
            "left": {"go": "/left", "then": "/stop"}, "right": {"go": "/right", "then": "/stop"},
            "turn_left": {"go": "/turnL", "then": "/stop"}, "turn_right": {"go": "/turnR", "then": "/stop"},
        },
        "note": "drives only in manual mode, and not while her wheels are locked",
    },
    # Only until her Pi runs the new code: that registers do:<action> and takes POST /do itself
    # (with her wheel lock), and RIFT uses that instead. /command is on every version of her.
    "KIDA00": {
        "does": {
            "stop": ("/command", {"command": "stop"}),
            "music_play": ("/command", {"command": "music"}), "music_stop": ("/command", {"command": "stop_music"}),
            "music_next": ("/command", {"command": "skip"}), "photo": ("/command", {"command": "photo"}),
            "forward": {"go": ("/command", {"command": "forward"}), "then": ("/command", {"command": "stop"})},
            "back": {"go": ("/command", {"command": "backward"}), "then": ("/command", {"command": "stop"})},
            "turn_left": {"go": ("/command", {"command": "left"}), "then": ("/command", {"command": "stop"})},
            "turn_right": {"go": ("/command", {"command": "right"}), "then": ("/command", {"command": "stop"})},
        },
        "note": "drives best in USER mode: AUTONOMOUS / LINE / QR steer her themselves",
    },
    # IR only: through NORA's IR transmitter (/ida), or RIFT's own board when NORA's away.
    # One-way: she never answers, so there's no status and no telling whether she heard.
    "IDA": {
        "status": None,
        "does": {
            "stop": "ir:stop", "manual_mode": "ir:manual", "obstacle_mode": "ir:auto",
            "forward": {"go": "ir:fw", "then": "ir:stop"}, "back": {"go": "ir:bw", "then": "ir:stop"},
            "turn_left": {"go": "ir:left", "then": "ir:stop"}, "turn_right": {"go": "ir:right", "then": "ir:stop"},
        },
        "note": "IR only, one way: she can't answer, so nobody knows whether she heard",
    },
    # The arm's controller.py in fleet mode (:5011). Every action moves her: always asks first.
    "ARM": {
        "does": {"rest": "/reset", "joint": "/cmd?motor={motor}&angle={angle}"},
        "note": "joint takes motor (1-6) and angle (degrees; the controller keeps it within each motor's range)",
    },
    # Both take commands only from a controller unlocked with their PIN; RIFT never unlocks.
    # MILA's /scan (needs her SCAN firmware) looks left / front / right with her servo; no PIN
    # while she stands still, and she refuses it (403 / 409) while driving or in obstacle mode.
    "MILA": {"does": {"scan": "/scan"},
             "note": "scan only: driving her needs the PIN (/unlock), which RIFT never sends"},
    "WHIP": {"does": {}, "note": "ask only: /web and /mode need the PIN (/unlock), which RIFT never sends"},
    # NIKA runs MILA's firmware (NIKA-Robot-v00), with her /scan
    "NIKA": {"does": {"scan": "/scan"},
             "note": "scan only: driving her needs the PIN (/unlock), which RIFT never sends"},
}


def core(name, status):
    """The fields every robot's answer has, whatever its own /status looks like:
    mode, moving, music, distances_cm (None where it doesn't say)."""
    s = status if isinstance(status, dict) else {}
    n = name.upper()
    out = {"name": name, "mode": s.get("mode"), "moving": s.get("moving"), "music": None, "distances_cm": {}}
    pick = lambda xs, i: xs[i] if isinstance(i, int) and 0 <= i < len(xs) else i
    if n == "NORA":
        out.update(mode=pick(["manual", "auto", "line", "ir"], s.get("mode")),
                   music=pick(["stopped", "playing", "paused"], s.get("ms")),
                   distances_cm={k: s[c] for k, c in (("front", "F"), ("left", "L"), ("back", "B"), ("right", "R")) if c in s},
                   wheels_locked=bool(s.get("lock")) if "lock" in s else None)
    elif n in ("MILA", "NIKA"):
        out.update(moving=bool(s.get("ml") or s.get("mr")) if "ml" in s else None,
                   distances_cm={"front": s["dist"]} if "dist" in s else {})
        if s.get("scan_ms", -1) >= 0:          # her last SCAN: left / front / right, and how old it is
            out["scan"] = {"left": s.get("scan_l"), "front": s.get("scan_f"), "right": s.get("scan_r"),
                           "age_s": round(s["scan_ms"] / 1000, 1)}
    elif n == "WHIP":
        out.update(mode=pick(["obstacle", "ir", "web"], s.get("controlMode")),
                   moving=s["move"] != 0 if "move" in s else None,
                   state=pick(["active", "tilt_safe", "shutdown"], s.get("sysState")),
                   distances_cm={"front": s["distance"]} if "distance" in s else {})
    elif n.startswith("KIDA") and isinstance(s.get("sensors"), dict):      # KIDA01
        us = {k.lower(): v for k, v in s["sensors"].items() if k in ("US0", "US1") and isinstance(v, (int, float))}
        out.update(music="playing" if s.get("music_on") else "stopped", distances_cm=us,
                   wheels_locked=bool(s.get("motor_lock")))
    elif n == "ARM":
        out.update(board_connected=s.get("connected"),
                   joints={k: m.get("angle") for k, m in (s.get("motors") or {}).items()})
    elif n.startswith("KIDA"):
        if "motor_lock" in s:
            out["wheels_locked"] = bool(s["motor_lock"])
        if s.get("music") in ("playing", "stopped"):        # her new /status says it herself
            out["music"] = s["music"]
        elif "music_playing" in s:
            out["music"] = "playing" if s["music_playing"] else "stopped"
        if not isinstance(s.get("moving"), bool) and "direction" in s:
            out["moving"] = str(s["direction"]).upper() not in ("STOPPED", "STOP", "")
    return out


def tier(action):
    if NEVER.search(action):
        return "never"
    return "harmless" if action in HARMLESS else "moving"


board = None   # RIFT's own IR board (app.py sets it): IDA's way in when NORA is away


def _find(fleet, name):
    robot = next((r for r in fleet if r["name"].upper() == str(name).upper()), None)
    if robot or str(name).upper() != "IDA":
        return robot
    nora = _find(fleet, "NORA")         # IDA never registers: she's reached over IR
    if nora:
        return {"name": "IDA", "ip": nora["ip"], "capabilities": [], "url": nora.get("url"), "ir_via": "NORA"}
    if board is not None and board.connected:
        return {"name": "IDA", "ip": None, "capabilities": [], "url": None, "ir_via": "RIFT"}
    return None


def _missing(name):
    if str(name).upper() == "IDA":
        return "IDA is IR only, and neither NORA nor RIFT's IR board is up to reach her"
    return f"{name} isn't online (not on RIFT's roster)"


def _base(robot):
    if robot.get("ir_via") == "RIFT":
        return ""
    return (robot.get("url") or f"http://{robot['ip']}/").rstrip("/")


def does(robot):
    """What this robot can be told to do, and whether it's its own /do or RIFT's mapping."""
    own = [c[3:] for c in robot.get("capabilities", []) if str(c).startswith("do:") and c[3:]]
    if own:
        return own, "robot"
    adapter = ADAPTERS.get(robot["name"].upper())
    return (sorted(adapter["does"]), "rift") if adapter and adapter["does"] else ([], None)


def _http(method, url, body=None):
    data = json.dumps(body).encode() if body is not None else None
    req = urllib.request.Request(url, data=data, method=method,
                                 headers={"Content-Type": "application/json"} if data else {})
    try:
        with urllib.request.urlopen(req, timeout=TIMEOUT_S) as r:
            raw = r.read().decode("utf-8", "replace")
            code = r.status
    except urllib.error.HTTPError as e:
        raw, code = e.read().decode("utf-8", "replace"), e.code
    try:
        return code, json.loads(raw)
    except ValueError:
        return code, raw.strip()


def _log(who, text):
    mission.add(who[:24], text[:280], "talk")


def ask(fleet, name, asker="someone"):
    robot = _find(fleet, name)
    if not robot:
        return 404, {"ok": False, "error": _missing(name)}
    actions, via = does(robot)
    adapter = ADAPTERS.get(robot["name"].upper(), {})
    if "status" in adapter and adapter["status"] is None:     # IR only: nothing to ask
        _log(asker, f"{asker} asked {robot['name']} how she is, but she can't answer (IR only).")
        return 200, {"ok": True, "to": robot["name"], "core": core(robot["name"], None), "status": None,
                     "does": actions, "via": via, "note": adapter["note"] + f" (reached through {robot['ir_via']})"}
    url = _base(robot) + adapter.get("status", "/status")
    try:
        code, answer = _http("GET", url)
    except Exception as e:
        _log(asker, f"{asker} asked {robot['name']} how she is: no answer ({type(e).__name__}).")
        return 502, {"ok": False, "to": robot["name"], "error": f"no answer from {url}: {type(e).__name__}"}
    _log(asker, f"{asker} asked {robot['name']} how she is.")
    out = {"ok": code < 400, "to": robot["name"], "core": core(robot["name"], answer), "status": answer,
           "does": actions, "via": via}
    if adapter.get("note"):
        out["note"] = adapter["note"]
    return (200 if code < 400 else 502), out


def do(fleet, name, action, args=None, asker="someone", confirmed=False):
    args = dict(args or {})
    action = str(action or "").strip().lower()
    robot = _find(fleet, name)
    if not action:
        return 400, {"ok": False, "error": "do needs an action"}
    if not robot:
        return 404, {"ok": False, "error": _missing(name)}
    level = tier(action)
    if level == "never":
        _log(asker, f"{asker} asked {robot['name']} to {action}: refused, RIFT never relays that.")
        return 403, {"ok": False, "to": robot["name"], "tier": level,
                     "error": "never relayed: unlocking or powering a robot down is for a person at the robot"}
    if level == "moving" and not confirmed:
        return 403, {"ok": False, "to": robot["name"], "tier": level, "needs": "confirmed",
                     "error": f"{action} can move {robot['name']}: get a person's yes, then send \"confirmed\": true"}
    actions, via = does(robot)
    if action not in actions:
        return 400, {"ok": False, "to": robot["name"], "does": actions,
                     "error": f"{robot['name']} can't {action}" + (f"; she can: {', '.join(actions)}" if actions else
                                                                    f" ({ADAPTERS.get(robot['name'].upper(), {}).get('note') or 'she registers no do:<action> capabilities and RIFT has no mapping for her yet'})")}
    try:
        if via == "robot":
            code, answer = _http("POST", _base(robot) + "/do", dict(args, action=action))
        else:
            code, answer = _adapted(robot, action, args)
    except Exception as e:
        _log(asker, f"{asker} told {robot['name']} to {action}: no answer ({type(e).__name__}).")
        return 502, {"ok": False, "to": robot["name"], "action": action, "error": f"no answer: {type(e).__name__}"}
    ok = code < 400 and not (isinstance(answer, dict) and answer.get("ok") is False)
    _log(asker, f"{asker} told {robot['name']} to {action}" + ("." if ok else f": she said no ({answer})."))
    return (200 if ok else code if 400 <= code < 500 else 502), {"ok": ok, "to": robot["name"], "action": action,
                                                                 "tier": level, "via": via, "answer": answer}


def _call(base, route):
    if isinstance(route, str) and route.startswith("ir:"):     # IDA: NORA's /ida, or RIFT's board
        if base:
            return _http("GET", base + "/ida?c=" + route[3:])
        return (200, "OK") if board is not None and board.link("ida", route[3:]) else (503, "RIFT's IR board didn't send it")
    if isinstance(route, str):
        return _http("GET", base + route)
    path, body = route
    return _http("POST", base + path, body)


def _adapted(robot, action, args):
    adapter = ADAPTERS[robot["name"].upper()]
    route = adapter["does"][action]
    base = _base(robot)
    if isinstance(route, dict) and "skip_if" in route:
        key, value = route["skip_if"]
        code, status = _http("GET", base + adapter.get("status", "/status"))
        if code < 400 and isinstance(status, dict) and status.get(key) == value:
            return 200, {"ok": True, "skipped": f"status already says {key}={value}"}
        return _call(base, route["route"])
    if isinstance(route, str) and "{" in route:     # whole numbers from the request, e.g. ARM's motor and angle
        try:
            route = route.format(**{k: int(args[k]) for k in re.findall(r"{(\w+)}", route)})
        except (KeyError, TypeError, ValueError):
            return 400, {"ok": False, "error": f"{action} needs " + ", ".join(re.findall(r"{(\w+)}", route)) + " (whole numbers)"}
    if not isinstance(route, dict):
        return _call(base, route)
    try:
        seconds = min(MAX_DRIVE_S, max(0.1, float(args.get("seconds", 0.5))))
    except (TypeError, ValueError):
        seconds = 0.5
    code, answer = _call(base, route["go"])
    if code >= 400:
        return code, answer
    try:
        time.sleep(seconds)
    finally:
        _call(base, route["then"])     # always stop, even if the wait was cut short
    return code, {"ok": True, "moved_s": seconds, "answer": answer}
