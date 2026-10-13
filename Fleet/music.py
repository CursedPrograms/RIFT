"""music.py - the fleet plays the same song together, with RIFT conducting.

Players register with the capability "music:<port>" (TINA does; KIDA00, KIDA01 and
NORA are next). POST /music {"action": "play", "track": 100} makes RIFT pick a start
LEAD_S ahead on its own clock and send every player POST <player>/music
{"action", "track", "at"}. Each player keeps its offset to RIFT's clock (GET /clock),
so they all start on the same moment however long the message took to get there;
its own start-up lag (an MP3 module is slow) each player takes off itself.

Tracks are numbered the same everywhere: the number in the file name, as on NORA's
SD card (NORA-Robot-v00/music: Track000.mp3, Track100.mp3, ...).
"""
import json
import time
import urllib.error
import urllib.request
from concurrent.futures import ThreadPoolExecutor

from Fleet import mission

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


def conduct(roster, action, track=None):
    """Tell every player to do action at the same moment. -> what each answered."""
    if action not in ACTIONS:
        return {"ok": False, "error": f"action is one of {', '.join(ACTIONS)}"}
    if action == "play" and track is None:
        return {"ok": False, "error": "play needs a track number"}
    found = players(roster)
    if not found:
        return {"ok": False, "error": "nobody has registered music:<port>"}
    at = time.time() + LEAD_S
    body = {"action": action, "track": track, "at": at}
    with ThreadPoolExecutor(len(found)) as ex:
        answers = dict(zip(found, ex.map(lambda u: _send(u, body), found.values())))
    _last.update(action=action, track=track, at=at, players=answers)
    ok = [n for n, a in answers.items() if a.get("ok")]
    if action == "play" and ok:
        mission.add("RIFT", f"{', '.join(ok)} played track {track} together.", "music")
    return {"ok": bool(ok), "at": at, "players": answers}


def snapshot(roster):
    return {"players": sorted(players(roster)), "last": _last, "lead_s": LEAD_S}
