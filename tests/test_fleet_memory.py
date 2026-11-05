"""Fleet/fleet_memory.py: memories wait in a file while DREAM's server is away, and nothing waits on it."""
import sys
import time
import types

from Fleet import fleet_memory
from Fleet.fleet_memory import Digest, FleetMemory


class FakeHindsight:
    banks = {}
    slow = False

    def __init__(self, base_url, timeout):
        self.url = base_url

    def retain(self, bank_id, content, context=None, timestamp=None, retain_async=False):
        self.banks.setdefault(bank_id, []).append(content)

    def recall(self, bank_id, query, max_tokens=0, budget=""):
        if self.slow:
            time.sleep(5)
        hits = [types.SimpleNamespace(text=t) for t in self.banks.get(bank_id, []) if query.lower() in t.lower()]
        return types.SimpleNamespace(results=hits)


def _memory(tmp_path, monkeypatch, up):
    monkeypatch.setitem(sys.modules, "hindsight_client", types.SimpleNamespace(Hindsight=FakeHindsight))
    FakeHindsight.banks, FakeHindsight.slow = {}, False
    state = {"up": up}
    monkeypatch.setattr(FleetMemory, "_find", lambda self: "http://dream:8888" if state["up"] else None)
    m = FleetMemory("nina", pending=tmp_path / "pending.jsonl", enabled=False)   # no worker thread: flush by hand
    m.enabled = True
    return m, state


def test_kept_while_away_then_sent(tmp_path, monkeypatch):
    m, state = _memory(tmp_path, monkeypatch, up=False)
    m.retain("NORA went quiet", "a fleet problem")
    assert not m._flush()
    assert m.status()["pending"] == 1 and "nina" not in FakeHindsight.banks
    state["up"], m._down_until = True, 0
    assert m._flush()
    assert FakeHindsight.banks["nina"] == ["NORA went quiet"]
    assert not (tmp_path / "pending.jsonl").exists()


def test_recall_and_other_banks(tmp_path, monkeypatch):
    m, _ = _memory(tmp_path, monkeypatch, up=True)
    FakeHindsight.banks = {"nina": ["NORA went quiet at 3"], "rift": ["WHIP came online"]}
    assert m.recall("nora") == ["NORA went quiet at 3"]
    assert m.recall("whip", bank="rift") == ["WHIP came online"]


def test_recall_never_waits_long(tmp_path, monkeypatch):
    m, _ = _memory(tmp_path, monkeypatch, up=True)
    FakeHindsight.slow = True
    monkeypatch.setattr(fleet_memory, "RECALL_TIMEOUT_S", 0.2)
    t = time.time()
    assert m.recall("anything") == []
    assert time.time() - t < 1


def test_digest_is_one_memory(tmp_path, monkeypatch):
    m, _ = _memory(tmp_path, monkeypatch, up=True)
    d = Digest(m, "test", every_s=3600, max_lines=3)
    for line in ("a", "b", "c"):
        d.add(line)
    assert m.status()["pending"] == 1          # three lines, one memory
    assert m._flush() and len(FakeHindsight.banks["nina"]) == 1
