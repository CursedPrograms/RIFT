"""
near_map.py - who's near whom, across the whole fleet, for RIFT's dashboard.

Each robot keeps its own list of the robots around it (/near): signal strength,
zone, trend (coming closer / steady / leaving), what each says it's doing, and
whether it's making way. Over ESP-NOW the robots say what they're doing in
Brainfuck - a little program that prints park / go / wait / hand - and RIFT
decodes those programs here with the same interpreter the conversations use.

RIFT is in the picture too: on a Pi it beacons over Bluetooth LE as "RIFT"
(always parked: a hub doesn't move) and hears the robots itself; on a PC it
only listens. See fleet_near.py.

    collect(fleet_robots, rift_near)   -> {"rift": {...}, "robots": {"NORA": {...}, ...}}
"""

import json
import time
import urllib.request

from . import brainfuck_talk

# the robots that serve /near, and where (their web ports)
NEAR_PORTS = {"NORA": 5002, "WHIP": 5005, "KIDA00": 5003, "KIDA01": 5004}
CACHE_S = 3.0
_cache = {"t": 0.0, "data": None}


def _get(url, timeout=2.5):
    try:
        with urllib.request.urlopen(url, timeout=timeout) as r:
            return json.loads(r.read().decode("utf-8", "ignore"))
    except Exception:
        return None


def decode(bf):
    """What a robot said in Brainfuck (bounded, so a garbled program can't hang RIFT)."""
    if not bf or len(bf) > 200 or set(bf) - set("+-<>[].,"):
        return ""
    try:
        return brainfuck_talk.run_bf(bf, max_steps=5000)[:16]
    except Exception:
        return ""


def collect(fleet_robots, rift_near=None):
    if _cache["data"] is not None and time.time() - _cache["t"] < CACHE_S:
        return _cache["data"]
    out = {"rift": rift_near.status() if rift_near else None, "robots": {}}
    for r in fleet_robots:
        name = (r.get("name") or "").upper()
        port = NEAR_PORTS.get(name)
        if not port or not r.get("ip"):
            continue
        st = _get(f"http://{r['ip']}:{port}/near")
        if st is None:
            continue
        for peer in st.get("robots", []):
            if peer.get("bf"):
                peer["said"] = decode(peer["bf"])     # RIFT reads their Brainfuck too
        out["robots"][name] = st
    _cache.update(t=time.time(), data=out)
    return out
