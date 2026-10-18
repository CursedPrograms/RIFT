"""Fleet/conversations.settled(): who has been online long enough to chat, and NORA's quick reboots
(her uptime falls back without her ever leaving the roster)."""
import json

import pytest

from Fleet import conversations as conv


class Clock:
    def __init__(self, t=1_000_000.0):
        self.t = t

    def time(self):
        return self.t


@pytest.fixture
def world(monkeypatch):
    clock = Clock()
    uptime = {"NORA": 600.0}          # seconds; None = she doesn't answer /talk
    monkeypatch.setattr(conv, "time", clock)
    monkeypatch.setattr(conv, "_online_since", {})
    # NORA's uptime comes from the background probe's /talk (conversations._nora_talk), fresh each time here
    monkeypatch.setattr(conv, "_nora_talk", lambda:
                        None if uptime["NORA"] is None else json.dumps({"now": uptime["NORA"] * 1000}))

    class Fresh(dict):
        def __getitem__(self, k):
            return clock.t if k == "talk_t" else dict.__getitem__(self, k)
    monkeypatch.setattr(conv, "_nora_cache", Fresh())
    return clock, uptime


URLS = {"NORA": "http://nora", "TINA": "http://tina", "KIDA00": "http://kida"}


def test_up_for_a_while_chats_at_once(world):
    assert set(conv.settled(URLS)) == {"NORA", "TINA"}        # KIDA00 just arrived: 12 s quiet


def test_new_arrival_waits_its_startup(world):
    clock, _ = world
    conv.settled(URLS)
    clock.t += 11
    assert "KIDA00" not in conv.settled(URLS)
    clock.t += 2
    assert "KIDA00" in conv.settled(URLS)


def test_quick_reboot_waits_again(world):
    clock, uptime = world
    assert "NORA" in conv.settled(URLS)
    clock.t += 30
    uptime["NORA"] = 3.0                      # she rebooted but never dropped off the roster
    assert "NORA" not in conv.settled(URLS)
    clock.t += 10
    uptime["NORA"] = 13.0
    assert "NORA" in conv.settled(URLS)


def test_dropping_out_resets(world):
    clock, uptime = world
    uptime["NORA"] = None                     # no uptime to go by: counted from when RIFT saw her
    conv.settled(URLS)
    clock.t += 20
    assert "NORA" in conv.settled(URLS)
    conv.settled({"TINA": "http://tina"})     # she left
    clock.t += 1
    assert "NORA" not in conv.settled(URLS)   # back: waits her startup again
