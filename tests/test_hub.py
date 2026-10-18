"""RIFT as the hub (the default): no heartbeat to NORA, and NORA in /fleet whether she registered
with RIFT (the "RIFT" network) or was found on her own fallback AP."""
import pytest

import app as rift
from Fleet import conversations


def nora_state(**kw):
    s = {"t": 1e18, "roster": [], "up": False, "api": False, "misses": 0, "talk": None, "talk_t": 0,
         "host": None, "via": None}
    s.update(kw)
    return s


@pytest.fixture
def client(monkeypatch):
    monkeypatch.setattr(rift, "_fleet", {})
    return rift.app.test_client()


def register(client, name, ip, caps):
    client.environ_base["REMOTE_ADDR"] = ip
    assert client.post("/register", data={"name": name, "type": "robot", "capabilities": caps}).status_code == 200


def test_rift_is_the_hub_by_default():
    assert rift.NORA_HUB is False and rift._transport_mode == "hub"


def test_hub_mode_starts_no_heartbeat(monkeypatch):
    started = []
    monkeypatch.setattr(rift, "start_fleet_authority", lambda **kw: started.append(kw) or (None, None))
    rift._restart_fleet_authority("hub")
    assert started == [] and rift._fleet_thread is None


def test_mode_route_takes_hub(client, monkeypatch):
    monkeypatch.setattr(rift, "start_fleet_authority", lambda **kw: (None, None))
    assert client.post("/mode", json={"mode": "hub"}).get_json()["mode"] == "hub"
    assert client.get("/mode").get_json()["mode"] == "hub"
    assert client.post("/mode", json={"mode": "nonsense"}).status_code == 400


def test_registered_nora_listed_with_busy_flag(client, monkeypatch):
    register(client, "NORA", "192.168.4.23", "talk:5002,music")
    monkeypatch.setattr(conversations, "_nora", lambda: nora_state(up=True, api=False, host="192.168.4.23", via="rift"))
    nora = next(r for r in client.get("/fleet").get_json()["robots"] if r["name"] == "NORA")
    assert nora["ip"] == "192.168.4.23" and nora["busy"] is True and nora["url"] == "http://192.168.4.23:5002/"


def test_nora_on_her_own_ap(client, monkeypatch):
    monkeypatch.setattr(conversations, "_nora", lambda: nora_state(up=True, api=True, host="192.168.4.1", via="own_ap"))
    nora = next(r for r in client.get("/fleet").get_json()["robots"] if r["name"] == "NORA")
    assert nora["ip"] == "192.168.4.1" and nora["busy"] is False


def test_no_nora(client, monkeypatch):
    monkeypatch.setattr(conversations, "_nora", lambda: nora_state())
    assert all(r["name"] != "NORA" for r in client.get("/fleet").get_json()["robots"])
