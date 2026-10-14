"""music.py - the fleet plays the same song together, with RIFT conducting.

Players register with the capability "music:<port>" (TINA does; KIDA00, KIDA01 and
NORA are next). POST /music {"action": "play", "track": 100} makes RIFT pick a start
LEAD_S ahead on its own clock and send every player POST <player>/music
{"action", "track", "at"}. Each player keeps its offset to RIFT's clock (GET /clock),
so they all start on the same moment however long the message took to get there;
its own start-up lag (an MP3 module is slow) each player takes off itself.

Tracks are numbered the same everywhere: the number in the file name, as on NORA's
SD card (NORA-Robot-v00/music: Track000.mp3, Track100.mp3, ...).

NORA has no clock to set (an ESP32 + MP3 shield), so RIFT plays for her: it waits
until the start itself and sends her M:TRACK:<n> (her /serial) NORA_LATENCY_S early.
"parts" gives players their own tracks: {"parts": {"NORA": 101, "TINA": 102}} - drums
on one, melody on another - all starting together; the rest play "track".
"""
import threading
import json
import time
import urllib.error
import urllib.request
from concurrent.futures import ThreadPoolExecutor

from Fleet import mission

NORA_LATENCY_S = 0.3   # her MP3 shield's start-up lag; measure it and set it here

LEAD_S = 4.0          # how far ahead the start is set: every player must hear it and load the song (TINA took 1.6 s for a 3 MB mp3)
ACTIONS = ("play", "pause", "resume", "stop")
_last = {"action": None, "track": None, "at": None, "players": {}}


def players(roster):
    """{name: base_url} of every robot that registered "music:<port>"."""
    out = {}
    for r in roster:
        for cap in r.get("capabilities", []):
            if str(cap).startswith("music:") and str(cap)[6:].isdigit():
                out[r["name"]] = f"http://{r['ip']}:{str(cap)[6:]}"
    return out


def _send(url, body):
    req = urllib.request.Request(url + "/music", data=json.dumps(body).encode(),
                                 headers={"Content-Type": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=LEAD_S) as r:
            return json.loads(r.read() or b"{}")
    except urllib.error.HTTPError as e:      # the player said no: pass on why
        try:
            return json.loads(e.read() or b"{}") | {"ok": False}
        except ValueError:
            return {"ok": False, "error": f"HTTP {e.code}"}
    except Exception as e:
        return {"ok": False, "error": type(e).__name__}


def _nora(roster):
    """NORA's base URL if she's online and doesn't register music:<port> herself."""
    nora = next((r for r in roster if r["name"].upper() == "NORA"), None)
    if nora and not any(str(c).startswith("music:") for c in nora.get("capabilities", [])):
        return (nora.get("url") or f"http://{nora['ip']}:5002/").rstrip("/")
    return None


def _get(url):
    with urllib.request.urlopen(url, timeout=3) as r:
        return r.read().decode("utf-8", "replace")


def _play_for_nora(base, action, track, at):
    """RIFT is NORA's clock: wait for the start, then press her buttons. Her M:PLAY
    toggles pause, so pause / resume look at her state first."""
    try:
        if action == "pause" or action == "resume":
            ms = json.loads(_get(base + "/sensors")).get("ms")      # 0 stopped, 1 playing, 2 paused
            if (action == "pause" and ms != 1) or (action == "resume" and ms != 2):
                return {"ok": True, "skipped": "nothing to " + action}
        url = {"play": f"/serial?cmd=M:TRACK:{track}", "stop": "/muStop"}.get(action, "/muPlay")
        threading.Timer(max(0.0, at - NORA_LATENCY_S - time.time()), lambda: _quiet(_get, base + url)).start()
        return {"ok": True, "via": "RIFT", "note": "needs her M:TRACK firmware" if action == "play" else None}
    except Exception as e:
        return {"ok": False, "error": type(e).__name__}


def _quiet(fn, *a):
    try:
        fn(*a)
    except Exception as e:
        print(f"[RIFT] music: NORA missed it: {type(e).__name__}")


def conduct(roster, action, track=None, parts=None):
    """Tell every player to do action at the same moment. -> what each answered.
    parts: {name: track} for players with their own part; the rest play track."""
    if action not in ACTIONS:
        return {"ok": False, "error": f"action is one of {', '.join(ACTIONS)}"}
    parts = {str(n).upper(): int(t) for n, t in (parts or {}).items() if str(t).isdigit()}
    if action == "play" and track is None and not parts:
        return {"ok": False, "error": "play needs a track number (or parts)"}
    found = players(roster)
    nora = _nora(roster)
    if not found and not nora:
        return {"ok": False, "error": "nobody has registered music:<port>, and NORA isn't online"}
    at = time.time() + LEAD_S
    track_of = lambda n: parts.get(n.upper(), track)
    body = lambda n: {"action": action, "track": track_of(n), "at": at}
    answers = {}
    if action == "play":     # a player with no track of its own sits this one out
        found = {n: u for n, u in found.items() if track_of(n) is not None}
    if found:
        with ThreadPoolExecutor(len(found)) as ex:
            answers = dict(zip(found, ex.map(lambda n: _send(found[n], body(n)), found)))
    if nora and (action != "play" or track_of("NORA") is not None):
        answers["NORA"] = _play_for_nora(nora, action, track_of("NORA"), at)
    _last.update(action=action, track=track, parts=parts, at=at, players=answers)
    ok = [n for n, a in answers.items() if a.get("ok")]
    if action == "play" and ok:
        what = f"track {track}" if not parts else "their parts (" + ", ".join(f"{n} {track_of(n)}" for n in ok) + ")"
        mission.add("RIFT", f"{', '.join(ok)} played {what} together.", "music")
    return {"ok": bool(ok), "at": at, "players": answers}


def snapshot(roster):
    return {"players": sorted(set(players(roster)) | ({"NORA"} if _nora(roster) else set())), "last": _last, "lead_s": LEAD_S}
