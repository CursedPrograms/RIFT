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

Robots with a mind (DREAM, KIDA-01: they register a "peer" capability, see
their peer_talk.py) get real conversations with each other whenever both say
they're free (nobody is with them): RIFT referees a game of rock paper
scissors (both beep their move, utterances 14-16), the winner picks words or
Brainfuck, and RIFT relays a few turns between them. They still chirp with the
rest of the fleet as before.
"""
import json
import os
import random
import ssl
import threading
import time
import urllib.error
import urllib.request
from concurrent.futures import ThreadPoolExecutor

from Fleet import mission

HERE = os.path.dirname(os.path.abspath(__file__))
NORA_HOST = "192.168.4.1"
NORA_FLEET_PORT = 5000   # her fleet registry (/robots)
NORA_API_PORT = 5002     # her robot API (/chirp, /talk)

with open(os.path.join(HERE, "talk_bf.json"), encoding="utf-8") as f:
    UTTERANCES = json.load(f)   # [{"index", "name", "kind", "text", "bf"}], 0-6 phrases, 7-13 replies, 14-16 moves

MOVES = ["rock", "paper", "scissors"]          # utterances 14-16
BEATS = {"rock": "scissors", "paper": "rock", "scissors": "paper"}
PEER_TURNS = (4, 8)          # lines in a peer conversation (even, so both get to say goodbye)
PEER_GAP_S = (60, 180)       # between two peer conversations, while they're both free
PEER_SAY_TIMEOUT_S = 180     # one line: the LLM thinking, then DREAM's lip-sync rendering

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
    "DREAM":     {"chattiness": 2, "likes": [4, 1, 6], "about": "DREAM: deep, dreamy, a bit sleepy"},
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


def mood_word(m):
    if m > 0.5:
        return "bright"
    if m > 0.1:
        return "content"
    if m > -0.3:
        return "quiet"
    return "sleepy"


def _nudge_mood(name, by):
    before = mood_word(_mood(name))
    _moods[name] = max(-1.0, min(1.0, _moods.get(name, 0.3) + by))
    after = mood_word(_mood(name))
    if after != before:
        mission.add(name, f"{name} is feeling {after} now.", "mood")


HELLO, HOW, HAPPY, CURIOUS, SLEEPY, PLAY, BYE = range(7)
GREET_GAP_S = 30 * 60   # apart this long, two robots say hello again before anything else
BYE_REST_S = 10 * 60    # after goodbye, a pair leaves each other alone this long
BYE_AFTER = 3           # phrases in a visit before either may say goodbye
_visits = {}            # frozenset({a, b}) -> {"said": [u, ...], "last": t, "bye": t or 0}


def _visit(a, b):
    """The pair's current visit: what's been said since they last said hello. A new one
    starts when they've been apart GREET_GAP_S, or rested after saying goodbye."""
    key, now = frozenset((a, b)), time.time()
    v = _visits.get(key)
    if v is None or now - v["last"] > GREET_GAP_S or (v["bye"] and now - v["bye"] > BYE_REST_S):
        v = _visits[key] = {"said": [], "last": now, "bye": 0}
    return v


def resting(a, b):
    """They said goodbye a moment ago: don't start them up again yet."""
    v = _visits.get(frozenset((a, b)))
    return bool(v and v["bye"] and time.time() - v["bye"] < BYE_REST_S)


def _pick_phrase(name, other):
    """What `name` says to `other`: hello first, "how are you" soon after, then its
    favourites coloured by its mood - not what was just said, not sleepy on a bright
    day, and goodbye only once they've talked a while."""
    said = _visit(name, other)["said"]
    if not said:
        return HELLO
    mood = _mood(name)
    weights = [1.0] * 7
    for p in _personality(name)["likes"]:
        weights[p] += 2.0
    weights[HAPPY] += 2 * max(mood, 0)
    weights[PLAY] += 2 * max(mood, 0)
    weights[SLEEPY] = 3 * max(-mood, 0) + (0.2 if mood < 0.1 else 0)
    weights[HELLO] = 0                                     # they've greeted already
    weights[HOW] = 0 if HOW in said else weights[HOW] + (3 if len(said) == 1 else 0)
    weights[BYE] = 0 if len(said) < BYE_AFTER else 0.4 + 0.3 * len(said) + 2 * max(-mood, 0)
    for u in said[-3:]:                                    # don't repeat what was just said
        weights[u] *= 0.15
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


def _request_json(url, payload=None, timeout=5):
    """GET (or POST payload as JSON to) url; the JSON answer, or None. 409 answers
    (a robot that has become busy) still come back as JSON."""
    for u in (url, url.replace("http://", "https://", 1)):
        ctx = ssl._create_unverified_context() if u.startswith("https") else None
        data = json.dumps(payload).encode() if payload is not None else None
        req = urllib.request.Request(u, data=data, headers={"Content-Type": "application/json"} if data else {})
        try:
            with urllib.request.urlopen(req, timeout=timeout, context=ctx) as r:
                return json.loads(r.read() or b"null")
        except urllib.error.HTTPError as e:
            try:
                return json.loads(e.read() or b"null")
            except ValueError:
                return None
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


_peer_caps = set()   # names of the robots that registered "peer" (a mind of their own)


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
                elif cap == "peer":
                    _peer_caps.add(r["name"])
    if nora["up"]:
        found["NORA"] = f"http://{NORA_HOST}:{NORA_API_PORT}"
    return found


# Their programs play a startup sound: nobody talks to them until it's over.
STARTUP_QUIET_S = {"KIDA": 12, "NORA": 12}    # name prefix -> seconds online first (KIDA00, KIDA01)
_online_since = {}


def settled(urls):
    """The talkers that have been online long enough to chat. One that drops out
    and comes back waits again."""
    now = time.time()
    for n in list(_online_since):
        if n not in urls:
            del _online_since[n]
    for n in urls:
        _online_since.setdefault(n, now)
    return {n: u for n, u in urls.items()
            if now - _online_since[n] >= next((s for k, s in STARTUP_QUIET_S.items() if n.upper().startswith(k)), 0)}


BUSY_REST_S = 60     # a robot that said it's busy (409) is left out of the chatter this long
_busy_until = {}


def _chirp(url):
    """True: said it. "busy": the robot declined (409 - TINA while she's working or
    in use). False: no answer at all."""
    for u in (url, url.replace("http://", "https://", 1)):
        try:
            ctx = ssl._create_unverified_context() if u.startswith("https") else None
            with urllib.request.urlopen(u, timeout=3, context=ctx):
                return True
        except urllib.error.HTTPError as e:
            return "busy" if e.code == 409 else False
        except Exception:
            continue
    return False


def busy(name):
    return time.time() < _busy_until.get(name, 0)


def _declined(who, to):
    """who is busy: a quiet note, a minute's rest from the chatter, no hard feelings."""
    _busy_until[who] = time.time() + BUSY_REST_S
    _record({"t": time.time(), "from": who, "to": to, "u": None, "said": None, "kind": "note",
             "text": "is busy right now", "bf": "", "via": "wifi", "ok": True})


def converse(a, b, urls, phrase=None):
    """a says a phrase to b and b answers. Logs both. Returns True if both spoke."""
    p = _pick_phrase(a, b) if phrase is None else phrase
    ok_a = _chirp(f"{urls[a]}/chirp?u={p}")
    if ok_a == "busy":
        _declined(a, b)
        return False
    if ok_a:                               # the visit remembers what was actually said
        v = _visit(a, b)
        v["said"].append(p)
        v["last"] = time.time()
        if p == BYE:
            v["bye"] = time.time()
    _record({"t": time.time(), "from": a, "to": b, "u": p, "said": UTTERANCES[p]["name"], "kind": "phrase",
             "text": UTTERANCES[p]["text"], "bf": UTTERANCES[p]["bf"], "via": "wifi", "ok": ok_a})
    if not ok_a:
        _nudge_mood(a, -0.1)
        return False
    time.sleep(say_seconds(p) + 0.6)   # let a finish before b answers
    r = 7 + p
    ok_b = _chirp(f"{urls[b]}/chirp?u={r}")
    if ok_b == "busy":
        _declined(b, a)
        return False
    _record({"t": time.time(), "from": b, "to": a, "u": r, "said": UTTERANCES[r]["name"], "kind": "reply",
             "text": UTTERANCES[r]["text"], "bf": UTTERANCES[r]["bf"], "via": "wifi", "ok": ok_b})
    said, reply = UTTERANCES[p]["text"], UTTERANCES[r]["text"]
    mission.add(a, f'{a} said "{said}" to {b}' + (f' and {b} answered "{reply}".' if ok_b else f", but {b} didn't answer."),
                "chat")
    # a good chat lifts both moods a little; being ignored doesn't
    _nudge_mood(a, 0.15 if ok_b else -0.15)
    _nudge_mood(b, 0.1 if ok_b else 0)
    return ok_b


# ---- robots with minds: rock paper scissors, then words or Brainfuck

_in_session = set()   # robots in a peer conversation right now - kept out of the chirping
_peer_state = {"next": 0.0}


def peers(urls):
    """The robots that can talk that also have a mind."""
    return [n for n in urls if n in _peer_caps]


def free(name, urls):
    """(free?, why not, their mind snapshot) from the robot's GET /peer."""
    st = _request_json(f"{urls[name]}/peer", timeout=4)
    if not st:
        return False, "no answer", {}
    return bool(st.get("available")), st.get("reason", ""), st.get("mind") or {}


def rps(a, b, urls):
    """Rock paper scissors between a and b, refereed here. Both are asked at once, so
    neither can see the other's move, and both beep it. Ties go again (three times,
    then a coin decides). Returns the winner."""
    for _ in range(3):
        with ThreadPoolExecutor(2) as ex:
            answers = list(ex.map(lambda n: _request_json(f"{urls[n]}/peer/rps", timeout=5), (a, b)))
        moves = {}
        for n, ans in zip((a, b), answers):
            m = (ans or {}).get("move")
            moves[n] = m if m in MOVES else random.choice(MOVES)
        with ThreadPoolExecutor(2) as ex:            # both throw at once
            list(ex.map(lambda n: _get(f"{urls[n]}/chirp?u={14 + MOVES.index(moves[n])}"), (a, b)))
        for n, other in ((a, b), (b, a)):
            u = 14 + MOVES.index(moves[n])
            _record({"t": time.time(), "from": n, "to": other, "u": u, "said": moves[n], "kind": "move",
                     "text": moves[n], "bf": UTTERANCES[u]["bf"], "via": "wifi", "ok": True})
        time.sleep(1.5)
        if moves[a] != moves[b]:
            winner = a if BEATS[moves[a]] == moves[b] else b
            loser = b if winner == a else a
            mission.add(winner, f"{winner}'s {moves[winner]} beat {loser}'s {moves[loser]}.", "chat")
            return winner
    return random.choice((a, b))


def peer_converse(a, b, urls):
    """A real conversation between two robots with minds. Returns True if it happened."""
    snaps = {}
    for n in (a, b):
        ok, why, snap = free(n, urls)
        if not ok:
            print(f"[RIFT] {n} can't chat with {b if n == a else a} now: {why}")
            return False
        snaps[n] = snap
    _in_session.update((a, b))
    try:
        winner = rps(a, b, urls)
        other = b if winner == a else a
        mode = (_request_json(f"{urls[winner]}/peer/choose", timeout=5) or {}).get("talk")
        mode = mode if mode in ("words", "brainfuck") else random.choice(["words", "brainfuck"])
        how = "out loud" if mode == "words" else "in Brainfuck"
        _record({"t": time.time(), "from": winner, "to": other, "u": None, "said": mode, "kind": "decision",
                 "text": f"won rock paper scissors and wants to talk {how}", "bf": "", "via": "wifi", "ok": True})
        mission.add(winner, f"{winner} won rock paper scissors and chose to talk with {other} {how}.", "chat")

        turns = random.randrange(PEER_TURNS[0], PEER_TURNS[1] + 1, 2)
        last = {"text": "", "u": None, "mind": snaps[other]}
        speakers = [winner, other]
        said = 0
        for i in range(turns):
            me, them = speakers[i % 2], speakers[(i + 1) % 2]
            msg = {"from": them, "mode": mode, "text": last["text"], "u": last["u"],
                   "mind": last["mind"] if i else snaps[them], "opening": i < 2, "closing": i >= turns - 2}
            ans = _request_json(f"{urls[me]}/peer/say", msg, timeout=PEER_SAY_TIMEOUT_S)
            if not ans or not ans.get("ok"):
                why = (ans or {}).get("reason") or "no answer"
                _record({"t": time.time(), "from": me, "to": them, "u": None, "said": None, "kind": "note",
                         "text": f"stopped talking ({why})", "bf": "", "via": "wifi", "ok": False})
                if mode == "brainfuck":
                    _get(f"{urls[them]}/chirp?u=6")      # the other one says bye anyway
                break
            u = ans.get("u")
            bf = UTTERANCES[u]["bf"] if isinstance(u, int) and 0 <= u < len(UTTERANCES) else ""
            kind = "words" if mode == "words" else ("reply" if isinstance(u, int) and 7 <= u < 14 else "phrase")
            _record({"t": time.time(), "from": me, "to": them, "u": u, "said": ans.get("text"), "kind": kind,
                     "text": ans.get("text", ""), "bf": bf, "via": "wifi", "ok": True})
            said += 1
            last = {"text": ans.get("text", ""), "u": u, "mind": ans.get("mind") or {}}
            time.sleep((say_seconds(u) if bf else (ans.get("seconds") or 0)) + 0.8)
        if said:
            mission.add(a, f"{a} and {b} talked {how} ({said} lines).", "chat")
            _nudge_mood(a, 0.1 * min(said, 4) / 4)
            _nudge_mood(b, 0.1 * min(said, 4) / 4)
        return said > 0
    finally:
        _in_session.difference_update((a, b))


def maybe_peer_chat(urls):
    """If two robots with minds are free, start them talking (on its own thread: a
    conversation takes minutes). Tries again every PEER_GAP_S while they stay free."""
    if _in_session or time.time() < _peer_state["next"]:
        return
    names = peers(urls)
    if len(names) < 2:
        return
    a, b = random.sample(names, 2)
    _peer_state["next"] = time.time() + 30          # not free: look again in half a minute

    def run():
        try:
            if peer_converse(a, b, urls):
                _peer_state["next"] = time.time() + random.uniform(*PEER_GAP_S)
        except Exception as e:
            print(f"[RIFT] peer conversation error: {e}")
    threading.Thread(target=run, daemon=True, name="peer-conversation").start()


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
        t = time.time() - (now_ms - key) / 1000
        _record({"t": t, "from": e.get("from", "NORA"), "to": e.get("to", "IDA"),
                 "u": None, "said": e.get("said"), "kind": "phrase", "text": e.get("text", ""), "bf": e.get("bf", ""),
                 "via": "ir", "ok": True})
        mission.add("NORA", f'NORA said "{e.get("text", "")}" to {e.get("to", "IDA")} over IR.', "chat", t=t)


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
                urls = settled(talkers(get_fleet_snapshot()))
                maybe_peer_chat(urls)
                if time.time() >= next_chat:
                    urls = {n: u for n, u in urls.items() if n not in _in_session and not busy(n)}
                    if len(urls) >= 2:
                        names = list(urls)
                        weights = [_personality(n)["chattiness"] for n in names]
                        a = random.choices(names, weights=weights)[0]
                        others = [n for n in names if n != a and not resting(a, n)]
                        if others:
                            converse(a, random.choice(others), urls)
                    next_chat = time.time() + random.uniform(min_gap, max_gap)
            except Exception as e:   # never let one bad robot stop the chatter
                print(f"[RIFT] conversation error: {e}")
            time.sleep(10)

    t = threading.Thread(target=_loop, daemon=True, name="fleet-conversations")
    t.start()
    return t
