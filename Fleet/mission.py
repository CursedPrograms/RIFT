"""mission.py - the fleet's shared mission log, kept by RIFT.

A diary of the little beings' mission: who came online or went quiet, who
chatted with whom (and what they said, from the Brainfuck phrasebook), whose
mood changed, plus anything a robot reports itself with POST /mission. It's
saved to mission_log.json next to app.py so the mission carries on across
restarts; day 1 is the day the log was started.
"""
import json
import os
import threading
import time

PATH = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "mission_log.json")
KEEP = 500   # entries kept on disk

_lock = threading.Lock()
_entries = []      # {"t", "who", "text", "kind"}  kind: arrive, leave, chat, mood, note, system
_started = None    # epoch seconds of the first entry = mission day 1


def _load():
    global _entries, _started
    try:
        with open(PATH, encoding="utf-8") as f:
            data = json.load(f)
        _entries = data.get("entries", [])
        _started = data.get("started")
    except (OSError, ValueError):
        _entries, _started = [], None


def _save():
    tmp = PATH + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump({"started": _started, "entries": _entries[-KEEP:]}, f, indent=1)
    os.replace(tmp, PATH)


def day(t=None):
    """Mission day of time t (1 = the day the log started)."""
    if _started is None:
        return 1
    start = time.localtime(_started)
    midnight = time.mktime((start.tm_year, start.tm_mon, start.tm_mday, 0, 0, 0, 0, 0, -1))
    return int(((t or time.time()) - midnight) // 86400) + 1


def add(who, text, kind="note", t=None):
    global _started
    with _lock:
        if _started is None:
            _started = t or time.time()
        _entries.append({"t": t or time.time(), "who": who, "text": text, "kind": kind})
        try:
            _save()
        except OSError as e:
            print(f"[RIFT] mission log not saved: {e}")


def snapshot(limit=40):
    with _lock:
        entries = sorted(_entries, key=lambda e: e["t"])[-limit:]
    return {"day": day(), "started": _started,
            "entries": [dict(e, day=day(e["t"])) for e in entries]}


# ── Roster watcher: arrivals and departures ──────────────────────────────────
_present = None


def watch_roster(names):
    """Call with the names currently online; logs who arrived and who left."""
    global _present
    names = set(names)
    if _present is None:            # first look after RIFT starts: just note who's here
        _present = names
        add("RIFT", "RIFT woke up on mission day %d. %s" % (
            day(), ("Online: " + ", ".join(sorted(names)) + ".") if names else "Nobody else is online yet."), "system")
        return
    for n in sorted(names - _present):
        add(n, f"{n} came online and joined the fleet.", "arrive")
    for n in sorted(_present - names):
        add(n, f"{n} went quiet.", "leave")
    _present = names


_load()
