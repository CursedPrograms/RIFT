"""locks.py - lock or unlock every robot's wheels (WHIP's legs) at once, from RIFT's dashboard.

    POST /locks {"action": "lock"}                   every robot with a lock: no PIN, an e-stop
    POST /locks {"action": "unlock", "pin": "1234"}  needs the fleet PIN (RIFT_FLEET_PIN, 1234 by
                                                     default), which also goes to each robot as hers

Unlocking is a person at RIFT's dashboard: /locks is its own route, and relay.py's /talk still
refuses every unlock (NEVER), so no robot or mind relays one. The PIN is a safety catch, not
security, like every robot's own.

How each robot locks:
    NORA, KIDA00,  /motorlockOn, /motorlockOff?pw=<PIN>
    MILA, NIKA,
    WHIP
    KIDA01         POST /action {"command": "motor_lock_on"} / {"command": "motor_lock_off", "password"}
    IDA            over IR (NORA's /link?r=ida&c=lock|unlock, or RIFT's own board when NORA's away):
                   one way, so RIFT can't tell whether she heard; IR unlock takes no PIN (one
                   button), which is why RIFT checks the PIN before sending it. MILA, NIKA and WHIP
                   get it over IR too when they're offline or their firmware has no /motorlockOn yet
    ARM            has no wheel lock
"""
import os
import urllib.parse
from concurrent.futures import ThreadPoolExecutor

from Fleet import mission, relay

FLEET_PIN = os.environ.get("RIFT_FLEET_PIN", "1234")
HTTP_LOCKS = {
    "NORA": {"lock": "/motorlockOn", "unlock": "/motorlockOff?pw={pin}"},
    "KIDA00": {"lock": "/motorlockOn", "unlock": "/motorlockOff?pw={pin}"},
    "MILA": {"lock": "/motorlockOn", "unlock": "/motorlockOff?pw={pin}"},
    "NIKA": {"lock": "/motorlockOn", "unlock": "/motorlockOff?pw={pin}"},
    "WHIP": {"lock": "/motorlockOn", "unlock": "/motorlockOff?pw={pin}"},
    "KIDA01": {"lock": ("/action", {"command": "motor_lock_on"}),
               "unlock": ("/action", {"command": "motor_lock_off", "password": "{pin}"})},
}
IR_LOCKS = ("IDA", "MILA", "WHIP", "NIKA")   # IDA always; the rest when WiFi can't reach their lock


def _route(route, pin):
    if isinstance(route, str):
        return route.replace("{pin}", urllib.parse.quote(pin))
    path, body = route
    return path, {k: (pin if v == "{pin}" else v) for k, v in body.items()}


def _http_one(robot, action, pin):
    route = _route(HTTP_LOCKS[robot["name"].upper()][action], pin)
    try:
        code, answer = relay._call(relay._base(robot), route)
    except Exception as e:
        return {"robot": robot["name"], "ok": False, "how": "wifi", "said": f"no answer ({type(e).__name__})"}
    if code == 404:
        return None   # her firmware has no WiFi lock yet: IR instead
    ok = code < 400 and not (isinstance(answer, dict) and answer.get("ok") is False)
    if ok:
        said = ""
    elif isinstance(answer, dict):
        said = str(answer.get("error") or "wrong PIN")[:80]
    else:
        said = (str(answer) if str(answer).strip() not in ("", "DENIED") else "wrong PIN")[:80]
    return {"robot": robot["name"], "ok": ok, "how": "wifi", "said": said}


def _ir_one(name, action, nora):
    try:
        if nora:
            code, _ = relay._http("GET", relay._base(nora) + f"/link?r={name.lower()}&c={action}")
            ok, via = code < 400, "IR through NORA"
        elif relay.board is not None and relay.board.connected:
            ok, via = bool(relay.board.link(name.lower(), action)), "IR from RIFT's board"
        else:
            return {"robot": name, "ok": False, "how": "IR", "said": "neither NORA nor RIFT's IR board is up"}
    except Exception as e:
        return {"robot": name, "ok": False, "how": "IR", "said": f"no answer ({type(e).__name__})"}
    return {"robot": name, "ok": ok, "how": via, "said": "sent; she can't answer over IR" if ok else "not sent"}


def apply(fleet, action, pin="", who="RIFT dashboard"):
    """Lock or unlock the whole fleet. Returns (http code, {"ok", "action", "robots": [...]})."""
    action = str(action or "").lower()
    if action not in ("lock", "unlock"):
        return 400, {"ok": False, "error": "action is lock or unlock"}
    pin = str(pin or "")
    if action == "unlock" and pin != FLEET_PIN:
        mission.add(who[:24], "Someone tried to unlock the whole fleet with the wrong PIN.", "talk")
        return 403, {"ok": False, "action": action, "error": "wrong PIN"}
    online = {r["name"].upper(): r for r in fleet}
    nora = online.get("NORA")

    def one(name):
        result = _http_one(online[name], action, pin) if name in online and name in HTTP_LOCKS else None
        if result is None and name in IR_LOCKS:
            result = _ir_one(name, action, nora)
        return result

    names = list(dict.fromkeys([*HTTP_LOCKS, *IR_LOCKS]))   # offline WiFi-only robots drop out in one()
    with ThreadPoolExecutor(max_workers=len(names)) as pool:
        results = [r for r in pool.map(one, names) if r is not None]
    done = [r["robot"] for r in results if r["ok"]]
    verb = "locked" if action == "lock" else "unlocked"
    mission.add(who[:24], f"{who} {verb} the whole fleet: " + (", ".join(done) or "nobody answered") + ".", "talk")
    return 200, {"ok": bool(done), "action": action, "robots": results}
