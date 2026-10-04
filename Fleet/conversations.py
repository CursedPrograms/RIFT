"""conversations.py - the fleet's robots talking to each other, run by RIFT.

Every 25-60 s RIFT picks two robots that can talk (they register a
"talk:<port>" capability, or it's NORA) and has the first say a phrase and
the second answer. Each phrase is a Brainfuck program from the fleet's
phrasebook (Fleet/talk_bf.json, made by brainfuck_talk.py); a robot says it
by beeping the program on its buzzer: GET http://<robot>:<port>/chirp?u=<n>.
This is liveliness, not data - the real data goes over WiFi / the IR link.

Each robot has a personality (how chatty it is, what it likes to say) and a
mood that drifts with the time of day and how its last chats went. NORA's own
IR chats with IDA (her /talk log) are merged in, so the dashboard shows the
whole fleet's conversation in one place.
"""
import json
import os
import random
import ssl
import threading
import time
import urllib.request

HERE = os.path.dirname(os.path.abspath(__file__))
NORA_HOST = "192.168.4.1"
NORA_FLEET_PORT = 5000   # her fleet registry (/robots)
NORA_API_PORT = 5002     # her robot API (/chirp, /talk)

with open(os.path.join(HERE, "talk_bf.json"), encoding="utf-8") as f:
    UTTERANCES = json.load(f)   # [{"index", "name", "kind", "text", "bf"}], 0-6 phrases, 7-13 replies

# Mirrors brainfuck_talk.py's tone lengths: how long saying u takes.
def say_seconds(u):
    return sum((80 if c == "." else 28) + 10 for c in UTTERANCES[u]["bf"]) / 1000


# chattiness: how often it starts a conversation (relative); likes: phrases it
# picks more (indexes 0-6: hello, how are you, happy, curious, sleepy, play, bye)
PERSONALITIES = {
    "NORA":      {"chattiness": 3, "likes": [0, 1, 5], "about": "the cheerful host - greets everyone"},
    "KIDA":      {"chattiness": 3, "likes": [3, 2, 5], "about": "curious, always asking about things"},
    "MILA":      {"chattiness": 2, "likes": [5, 2, 0], "about": "playful little tank"},
    "WHIP":      {"chattiness": 1, "likes": [3, 0],    "about": "quiet, watchful hexapod"},
    "ARM":       {"chattiness": 1, "likes": [1, 2],    "about": "polite and precise"},
    "COMCENTRE": {"chattiness": 2, "likes": [4, 1, 6], "about": "DREAM: deep, dreamy, a bit sleepy"},
}
DEFAULT_PERSONALITY = {"chattiness": 1, "likes": [0], "about": "new here"}

_log = []                 # newest last: {"t", "from", "to", "u", "text", "bf", "said", "kind", "via", "ok"}
_log_lock = threading.Lock()
_moods = {}               # name -> -1 (glum/sleepy) .. +1 (bright/playful)
LOG_LEN = 60


def _personality(name):
    for key, p in PERSONALITIES.items():
        if name.upper().startswith(key):
            return p
    return DEFAULT_PERSONALITY


def _mood(name):
    hour = time.localtime().tm_hour
    night = -0.5 if hour >= 22 or hour < 7 else 0.0
    return max(-1.0, min(1.0, _moods.get(name, 0.3) + night))


def _nudge_mood(name, by):
    _moods[name] = max(-1.0, min(1.0, _moods.get(name, 0.3) + by))


def _pick_phrase(name):
    """What `name` feels like saying: its favourites, coloured by its mood."""
    mood = _mood(name)
    weights = [1.0] * 7
    for p in _personality(name)["likes"]:
        weights[p] += 2.0
    weights[2] += 2 * max(mood, 0)    # happy
    weights[5] += 2 * max(mood, 0)    # let's play
    weights[4] += 3 * max(-mood, 0)   # sleepy
    weights[6] += 1 * max(-mood, 0)   # bye
    return random.choices(range(7), weights=weights)[0]


def _get(url, timeout=3):
    """GET url; tries https (self-signed is fine) if plain http fails."""
    for u in (url, url.replace("http://", "https://", 1)):
        try:
            ctx = ssl._create_unverified_context() if u.startswith("https") else None
            with urllib.request.urlopen(u, timeout=timeout, context=ctx) as r:
                return r.read()
        except Exception:
            continue
    return None


def _record(entry):
    with _log_lock:
        _log.append(entry)
        del _log[:-LOG_LEN]


_nora_cache = {"t": 0, "roster": [], "up": False}   # NORA probes, refreshed every 30 s


def _nora():
    if time.time() - _nora_cache["t"] > 30:
        raw = _get(f"http://{NORA_HOST}:{NORA_FLEET_PORT}/robots", timeout=2)
        roster = []
        if raw:
            try:
                roster = json.loads(raw).get("robots", [])
            except ValueError:
                pass
        _nora_cache.update(t=time.time(), roster=roster,
                           up=_get(f"http://{NORA_HOST}:{NORA_API_PORT}/talk", timeout=2) is not None)
    return _nora_cache


def talkers(fleet_snapshot):
    """{name: base_url} of every robot that can talk right now: RIFT's own
    registry, NORA's registry, and NORA herself."""
    found = {}
    nora = _nora()
    rosters = [fleet_snapshot, nora["roster"]]
    for roster in rosters:
        for r in roster:
            for cap in r.get("capabilities", []):
                if cap.startswith("talk:") and cap[5:].isdigit():
                    found[r["name"]] = f"http://{r['ip']}:{cap[5:]}"
    if nora["up"]:
        found["NORA"] = f"http://{NORA_HOST}:{NORA_API_PORT}"
    return found


def converse(a, b, urls, phrase=None):
    """a says a phrase to b and b answers. Logs both. Returns True if both spoke."""
    p = _pick_phrase(a) if phrase is None else phrase
    ok_a = _get(f"{urls[a]}/chirp?u={p}") is not None
    _record({"t": time.time(), "from": a, "to": b, "u": p, "said": UTTERANCES[p]["name"], "kind": "phrase",
             "text": UTTERANCES[p]["text"], "bf": UTTERANCES[p]["bf"], "via": "wifi", "ok": ok_a})
    if not ok_a:
        _nudge_mood(a, -0.1)
        return False
    time.sleep(say_seconds(p) + 0.6)   # let a finish before b answers
    r = 7 + p
    ok_b = _get(f"{urls[b]}/chirp?u={r}") is not None
    _record({"t": time.time(), "from": b, "to": a, "u": r, "said": UTTERANCES[r]["name"], "kind": "reply",
             "text": UTTERANCES[r]["text"], "bf": UTTERANCES[r]["bf"], "via": "wifi", "ok": ok_b})
    # a good chat lifts both moods a little; being ignored doesn't
    _nudge_mood(a, 0.15 if ok_b else -0.15)
    _nudge_mood(b, 0.1 if ok_b else 0)
    return ok_b


_nora_seen_ms = set()


def merge_nora_ir_log():
    """Copy NORA's IR chats with IDA (her /talk log) into the fleet log."""
    if not _nora()["up"]:
        return
    raw = _get(f"http://{NORA_HOST}:{NORA_API_PORT}/talk", timeout=2)
    if not raw:
        return
    try:
        data = json.loads(raw)
    except ValueError:
        return
    now_ms = data.get("now", 0)
    for e in data.get("log", []):
        key = e.get("ms")
        if key in _nora_seen_ms:
            continue
        _nora_seen_ms.add(key)
        _record({"t": time.time() - (now_ms - key) / 1000, "from": e.get("from", "NORA"), "to": e.get("to", "IDA"),
                 "u": None, "said": e.get("said"), "kind": "phrase", "text": e.get("text", ""), "bf": e.get("bf", ""),
                 "via": "ir", "ok": True})


def snapshot():
    with _log_lock:
        log = sorted(_log, key=lambda e: e["t"])[-LOG_LEN:]
    return {"log": log, "moods": {n: round(_mood(n), 2) for n in sorted(_moods)},
            "personalities": PERSONALITIES}


def start(get_fleet_snapshot, min_gap=25, max_gap=60):
    """Background thread: a conversation every min_gap-max_gap s, and NORA's IR
    log merged every 10 s. get_fleet_snapshot() returns RIFT's own roster."""
    def _loop():
        next_chat = time.time() + 10
        while True:
            try:
                merge_nora_ir_log()
                if time.time() >= next_chat:
                    urls = talkers(get_fleet_snapshot())
                    if len(urls) >= 2:
                        names = list(urls)
                        weights = [_personality(n)["chattiness"] for n in names]
                        a = random.choices(names, weights=weights)[0]
                        b = random.choice([n for n in names if n != a])
                        converse(a, b, urls)
                    next_chat = time.time() + random.uniform(min_gap, max_gap)
            except Exception as e:   # never let one bad robot stop the chatter
                print(f"[RIFT] conversation error: {e}")
            time.sleep(10)

    t = threading.Thread(target=_loop, daemon=True, name="fleet-conversations")
    t.start()
    return t
