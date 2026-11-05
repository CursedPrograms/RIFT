"""Real robots say goodbye only when they go out of each other's range."""
import time

from Fleet import conversations as c


def test_real_robots_never_pick_bye_in_a_chat(monkeypatch):
    c._visits.clear()
    v = c._visit("NORA", "WHIP")
    v["said"] = [c.HELLO, c.HOW, c.HAPPY, c.PLAY, c.CURIOUS, c.HAPPY]
    picks = {c._pick_phrase("NORA", "WHIP") for _ in range(300)}
    assert c.BYE not in picks
    c._visits.clear()
    v = c._visit("DREAM", "TINA")
    v["said"] = [c.HELLO, c.HOW, c.HAPPY, c.PLAY, c.CURIOUS, c.HAPPY]
    assert c.BYE in {c._pick_phrase("DREAM", "TINA") for _ in range(300)}   # the PCs still can


def test_bye_when_out_of_range(monkeypatch):
    c._visits.clear()
    c._near_seen.clear()
    said = []
    monkeypatch.setattr(c, "_chirp", lambda url: said.append(url) or True)
    monkeypatch.setattr(c, "_record", lambda e: None)
    monkeypatch.setattr(c, "say_seconds", lambda u: 0)
    monkeypatch.setattr(c.time, "sleep", lambda s: None)
    monkeypatch.setattr(c.mission, "add", lambda *a, **k: None)
    urls = {"NORA": "http://nora", "WHIP": "http://whip"}
    c._visit("NORA", "WHIP")["said"] = [c.HELLO, c.HOW]
    near = {"robots": {"NORA": {"robots": [{"name": "WHIP", "rssi": -60}]}}}
    t0 = time.time()
    assert c.goodbyes(urls, near, now=t0) == []                       # near: nothing
    gone = {"robots": {"NORA": {"robots": []}}}
    assert c.goodbyes(urls, gone, now=t0 + 5) == []                   # a short dropout isn't leaving
    assert c.goodbyes(urls, gone, now=t0 + c.OUT_OF_RANGE_S + 1) == [("NORA", "WHIP")]
    assert said == ["http://nora/chirp?u=6", "http://whip/chirp?u=13"]
    assert c.goodbyes(urls, gone, now=t0 + 60) == []                  # once
