"""How RIFT sees NORA (conversations._nora_probe / _nora, near_map). On the "RIFT" network she's in
RIFT's own roster; on her fallback "NORA" AP she's found at her registry (:5000, only "NORA alive"
counts: on the RIFT network that address is RIFT itself). Her page/API (:5002) slow or silent = busy,
not gone; a few misses before she's gone; never blocking a dashboard request; her /near fetched
gently. A fake NORA with both servers on localhost."""
import threading
import time

import pytest
from flask import Flask, jsonify
from werkzeug.serving import make_server

from Fleet import conversations as conv
from Fleet import near_map


class FakeNora:
    def __init__(self):
        self.registry = "ok"      # ok | off
        self.api = "ok"           # ok | slow | off
        self.now_ms = 600000
        self.hits = []


@pytest.fixture
def nora(monkeypatch):
    fake = FakeNora()
    reg, api = Flask("nora_registry"), Flask("nora_api")

    @reg.route("/robots")
    def robots():
        fake.hits.append(":5000/robots")
        if fake.registry == "off":
            return "", 503
        return jsonify({"robots": [{"name": "WHIP", "ip": "192.168.4.3", "capabilities": ["talk:5005"]}]})

    @reg.route("/ping")
    def ping():
        fake.hits.append(":5000/ping")
        if fake.registry == "rift":
            return "RIFT alive", 200             # 192.168.4.1 on the RIFT network: RIFT itself
        return ("NORA alive", 200) if fake.registry == "ok" else ("", 503)

    @api.route("/talk")
    def talk():
        fake.hits.append(":5002/talk")
        if fake.api == "slow":
            time.sleep(1.0)                  # longer than the (test) timeout: her page holds the server
        if fake.api == "off":
            return "", 503
        return jsonify({"now": fake.now_ms, "log": []})

    servers = []
    for app in (reg, api):
        s = make_server("127.0.0.1", 0, app, threaded=True)
        threading.Thread(target=s.serve_forever, daemon=True).start()
        servers.append(s)
    monkeypatch.setattr(conv, "NORA_HOST", "127.0.0.1")
    monkeypatch.setattr(conv, "NORA_FLEET_PORT", servers[0].server_port)
    monkeypatch.setattr(conv, "NORA_API_PORT", servers[1].server_port)
    monkeypatch.setattr(conv, "NORA_TIMEOUT_S", 0.4)
    monkeypatch.setattr(conv, "_nora_cache", {"t": 0, "roster": [], "up": False, "api": False, "misses": 0,
                                              "talk": None, "talk_t": 0, "host": None, "via": None})
    monkeypatch.setattr(conv, "_roster_fn", lambda: fake.roster)
    fake.roster = []                             # RIFT's own registry: NORA not registered
    yield fake
    for s in servers:
        s.shutdown()


def test_both_answer(nora):
    conv._nora_probe()
    c = conv._nora_cache
    assert c["up"] and c["api"] and c["roster"][0]["name"] == "WHIP" and c["misses"] == 0
    assert "NORA" in conv.talkers([])


def test_page_busy_is_not_gone(nora):
    conv._nora_probe()
    nora.api = "slow"
    conv._nora_probe()
    c = conv._nora_cache
    assert c["up"] is True and c["api"] is False         # still listed, just busy
    assert "NORA" not in conv.talkers([])                # no chatter piled onto her busy server
    assert c["roster"]                                   # her registry's roster is kept


def test_a_few_misses_before_gone(nora):
    conv._nora_probe()
    nora.registry = nora.api = "off"
    for _ in range(conv.NORA_MISSES - 1):
        conv._nora_probe()
        assert conv._nora_cache["up"] is True            # one or two missed probes: still there
    conv._nora_probe()
    assert conv._nora_cache["up"] is False and conv._nora_cache["roster"] == []
    nora.registry = nora.api = "ok"
    conv._nora_probe()
    assert conv._nora_cache["up"] is True                # back at once


def test_never_up_without_her_registry(nora):
    nora.registry = "off"
    conv._nora_probe()
    assert conv._nora_cache["up"] is False and ":5002/talk" not in nora.hits


def test_roster_fetch_failing_is_fine(nora, monkeypatch):
    real = conv._get_http
    monkeypatch.setattr(conv, "_get_http", lambda url, t: None if url.endswith("/robots") else real(url, t))
    conv._nora_probe()
    assert conv._nora_cache["up"] is True and conv._nora_cache["via"] == "own_ap"    # /ping is enough


def test_rift_itself_isnt_nora(nora):
    nora.registry = "rift"                       # 192.168.4.1 answers, but it's RIFT
    conv._nora_probe()
    assert conv._nora_cache["up"] is False and ":5002/talk" not in nora.hits


def test_registered_with_rift(nora):
    nora.registry = "off"                        # no fallback AP: she's on the RIFT network
    nora.roster = [{"name": "NORA", "ip": "127.0.0.1", "type": "mecanum", "capabilities": ["talk:5002"]}]
    conv._nora_probe()
    c = conv._nora_cache
    assert c["up"] and c["api"] and c["via"] == "rift" and c["host"] == "127.0.0.1"
    assert not any(h.startswith(":5000") for h in nora.hits)           # her registry isn't asked
    assert conv.talkers(nora.roster)["NORA"] == f"http://127.0.0.1:{conv.NORA_API_PORT}"
    nora.api = "slow"
    conv._nora_probe()
    assert conv._nora_cache["up"] and not conv._nora_cache["api"]
    assert "NORA" not in conv.talkers(nora.roster)                      # registered talk:, but busy


def test_nora_never_blocks(nora):
    nora.api = "slow"
    t = time.time()
    c = conv._nora()                                     # stale: starts a probe in the background
    assert time.time() - t < 0.1 and c["up"] is False
    for _ in range(50):
        if conv._nora_cache["t"] and "probing" not in conv._nora_cache:
            break
        time.sleep(0.05)
    assert conv._nora_cache["up"] is True and conv._nora_cache["api"] is False


def test_uptime_from_the_probe(nora, monkeypatch):
    conv._nora_probe()
    nora.hits.clear()
    up = conv._uptime_s("NORA", "http://unused")
    assert 600 <= up < 602 and nora.hits == []           # aged by the probe's age, no extra request


def test_near_fetches_esp32s_gently(monkeypatch):
    calls = []
    monkeypatch.setattr(near_map, "_get", lambda url, timeout=2.5: calls.append(url) or {"robots": []})
    monkeypatch.setattr(near_map, "_last", {})
    monkeypatch.setattr(near_map, "CACHE_S", 0)          # every dashboard poll recomputes
    fleet = [{"name": "NORA", "ip": "1.1.1.1"}, {"name": "KIDA00", "ip": "2.2.2.2"}]
    for _ in range(4):
        near_map.collect(fleet)
    assert sum("1.1.1.1" in u for u in calls) == 1       # NORA: once per EVERY_S (15 s)
    assert sum("2.2.2.2" in u for u in calls) == 4       # a Pi: every time
