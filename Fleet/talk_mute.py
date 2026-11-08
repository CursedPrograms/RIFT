"""talk_mute.py - every robot's two talk switches, as RIFT keeps them.

    sound   "muted"     her Brainfuck isn't beeped: she still takes part in the conversations,
                        silently (the log marks her lines "silent")
    chat    "chat_off"  she's out of the conversation engine: RIFT leaves her out of the chatter
                        and the peer conversations, and she doesn't start or answer any herself

Every robot that talks answers (Fleet/talk_switch.py for the Python ones, the same in firmware):

    GET /talkmute                       {"talk_muted": bool, "chat_off": bool}
    GET /talkmute?on=1|0|toggle         the sound switch   (no PIN: it only makes her quieter)
    GET /talkmute?chat_off=1|0|toggle   the chat switch

keeps both across restarts, puts them in her /status, and her /chirp answers 200 {"silent": true}
with the sound off, 409 {"reason": "chat_off"} with the chat off. Her own page and controller have
both switches too.

RIFT keeps its own list (talk_mute.json next to app.py) so a robot that's offline gets a change
when she's back, and "all" covers newcomers too. The robot's own switches win: flip one on her page
and RIFT picks it up from her next answer. A robot with older firmware (no /talkmute) can't be
silenced on her own, but RIFT still leaves her out when her chat is off.

RIFT itself is "RIFT": its own board's buzzer (arduino/rift_link), sound only.
"""
import json
import os
import threading
import time

HERE = os.path.dirname(os.path.abspath(__file__))
PATH = os.path.join(os.path.dirname(HERE), "talk_mute.json")
RECHECK_S = 60          # how often RIFT asks each robot what her switches say
SWITCHES = ("muted", "chat_off")
_PARAM = {"muted": "on", "chat_off": "chat_off"}       # /talkmute?<param>=
_ANSWER = {"muted": "talk_muted", "chat_off": "chat_off"}

_lock = threading.Lock()
_all = {"muted": False, "chat_off": False}   # "all": the default for every robot, newcomers included
_state = {}             # NAME -> {"muted": b, "chat_off": b}  what the robot last said (or RIFT's choice)
_want = {}              # NAME -> {switch: b}  changes from RIFT not delivered yet
_no_switch = set()      # robots without /talkmute (older firmware)
_checked = {}           # NAME -> when RIFT last asked her


def _load():
    try:
        with open(PATH, encoding="utf-8") as f:
            d = json.load(f)
    except (OSError, ValueError):
        return
    a = d.get("all")
    if isinstance(a, dict):
        _all.update({k: bool(a.get(k)) for k in SWITCHES})
    elif a is not None:                     # the first talk_mute.json: one switch, sound
        _all["muted"] = bool(a)
    for src, dst in ((d.get("robots") or {}, _state), (d.get("pending") or {}, _want)):
        for k, v in src.items():
            dst[str(k).upper()] = {s: bool(v[s]) for s in SWITCHES if s in v} if isinstance(v, dict) else {"muted": bool(v)}


def _save():
    tmp = PATH + ".tmp"
    try:
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump({"all": _all, "robots": _state, "pending": _want}, f, indent=1)
        os.replace(tmp, PATH)
    except OSError as e:
        print(f"[RIFT] couldn't save {PATH}: {e}")


_load()


def _get(n, switch):
    return _want.get(n, {}).get(switch, _state.get(n, {}).get(switch, _all[switch]))


def muted(name):
    """Her sound switch: her lines aren't beeped."""
    with _lock:
        return _get(str(name).upper(), "muted")


def chat_off(name):
    """Her chat switch: she's out of the conversations."""
    with _lock:
        return _get(str(name).upper(), "chat_off")


def heard(name, **switches):
    """A robot said what her switches are (/talkmute, or /chirp's answer)."""
    n = str(name).upper()
    with _lock:
        changed = False
        for s, v in switches.items():
            if s not in SWITCHES or v is None or s in _want.get(n, {}):   # RIFT's change on its way wins
                continue
            if _state.setdefault(n, {}).get(s) != bool(v):
                _state[n][s] = bool(v)
                changed = True
        if changed:
            _save()
        _checked[n] = time.time()


def set_switch(name, switch, value):
    """From RIFT's dashboard: one robot's sound or chat switch (delivered by sync())."""
    if switch not in SWITCHES:
        raise ValueError(switch)
    n = str(name).upper()
    with _lock:
        _want.setdefault(n, {})[switch] = bool(value)
        _checked.pop(n, None)
        _save()


def set_muted(name, value):
    set_switch(name, "muted", value)


def set_all(switch, value):
    """One switch for the whole fleet: every robot RIFT knows now, and newcomers."""
    if switch not in SWITCHES:
        raise ValueError(switch)
    with _lock:
        _all[switch] = bool(value)
        for n in set(_state) | set(_want):
            _want.setdefault(n, {})[switch] = bool(value)
        _checked.clear()
        _save()


def _ask(name, url, query=""):
    """GET /talkmute(?query): her switches afterwards {"muted", "chat_off"}, or None."""
    from Fleet import conversations as _conv   # its _request_json (http, then https); imported late: it imports us
    ans = _conv._request_json(f"{url}/talkmute{query}", timeout=3)
    if isinstance(ans, dict) and "talk_muted" in ans:
        _no_switch.discard(name)
        return {s: bool(ans[_ANSWER[s]]) for s in SWITCHES if _ANSWER[s] in ans}
    if ans is not None:
        _no_switch.add(name)        # answered, but not with a switch: older firmware (404 page)
    return None


def sync(urls, board=None):
    """Deliver RIFT's changes and read the robots' switches. urls: {name: base url} of the
    robots that talk (conversations.talkers()). Call it from a background loop."""
    now = time.time()
    for name, url in urls.items():
        n = name.upper()
        with _lock:
            want = dict(_want.get(n, {}))
            new = n not in _state
            due = now - _checked.get(n, 0) >= RECHECK_S
        if want:
            got = _ask(n, url, "?" + "&".join(f"{_PARAM[s]}={1 if v else 0}" for s, v in want.items()))
            with _lock:
                if got is not None or n in _no_switch:   # delivered (or she can't: RIFT just leaves her out)
                    _state.setdefault(n, {}).update(want)
                    _state[n].update(got or {})
                    _want.pop(n, None)
                    _checked[n] = now
                    _save()
        elif new and any(_all.values()):   # a newcomer while the fleet is muted or out of the chat
            for s in SWITCHES:
                if _all[s]:
                    set_switch(n, s, True)
        elif due:
            got = _ask(n, url)
            if got is not None:
                heard(n, **got)
            else:
                with _lock:
                    _checked[n] = now
    if board is not None:           # RIFT's own buzzer
        board.set_muted(muted("RIFT"))


def snapshot(names=()):
    """For the dashboard: every robot's two switches (known talkers first)."""
    with _lock:
        everyone = sorted(set(n.upper() for n in names) | set(_state) | set(_want) | {"RIFT"})
        return {"all": dict(_all),
                "robots": {n: {"muted": _get(n, "muted"), "chat_off": _get(n, "chat_off"),
                               "pending": n in _want, "own_switch": n not in _no_switch} for n in everyone}}
