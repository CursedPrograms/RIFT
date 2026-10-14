"""Fleet/music.py: RIFT conducts; NORA is played for (her M:TRACK NORA_LATENCY_S early), parts, pause/resume."""
import time

import pytest

from Fleet import mission, music


@pytest.fixture(autouse=True)
def short_lead(monkeypatch):
    monkeypatch.setattr(music, "LEAD_S", 0.6)       # every start 0.6 s ahead instead of 4 s


def player(fleet, name="TINA"):
    return {"name": name, "ip": "127.0.0.1", "capabilities": [f"music:{fleet.port}"]}


def test_players_from_capabilities(fleet):
    roster = [player(fleet), {"name": "MILA", "ip": "1.2.3.4", "capabilities": ["talk:5010", "music:x"]}]
    assert music.players(roster) == {"TINA": f"http://127.0.0.1:{fleet.port}"}


def test_play_reaches_players_and_logs(fleet):
    out = music.conduct([player(fleet)], "play", 100)
    assert out["ok"] and out["players"]["TINA"]["ok"]
    body = [h[3] for h in fleet.hits if h[0] == "player"][0]
    assert body["action"] == "play" and body["track"] == 100 and abs(body["at"] - out["at"]) < 1e-6
    assert out["at"] - time.time() > 0.3            # the start is ahead, for everyone to load the song
    assert any("played track 100 together" in e["text"] for e in mission._entries)


def test_nora_played_for_early_by_her_latency(fleet):
    hits_at = {}
    real_get = music._get

    def stamped(url):
        hits_at[url.split("/", 3)[3]] = time.time()
        return real_get(url)

    music._get = stamped
    try:
        out = music.conduct([fleet.robot("nora")], "play", 101)
        assert out["players"]["NORA"]["ok"] and out["players"]["NORA"]["via"] == "RIFT"
        time.sleep(music.LEAD_S + 0.3)
    finally:
        music._get = real_get
    sent = hits_at.get("nora/serial?cmd=M:TRACK:101")
    assert sent is not None, hits_at
    assert abs(sent - (out["at"] - music.NORA_LATENCY_S)) < 0.1     # her MP3 lag taken off


def test_parts(fleet):
    sent = {}
    real_get = music._get
    music._get = lambda url: sent.setdefault(url.split("/", 3)[3], real_get(url))
    try:
        out = music.conduct([player(fleet), fleet.robot("nora")], "play", None, parts={"nora": 101, "TINA": "102"})
        time.sleep(music.LEAD_S + 0.3)
    finally:
        music._get = real_get
    assert out["ok"]
    assert [h[3]["track"] for h in fleet.hits if h[0] == "player"] == [102]
    assert "nora/serial?cmd=M:TRACK:101" in sent
    assert any("their parts (" in e["text"] for e in mission._entries)


def test_player_without_a_part_sits_out(fleet):
    out = music.conduct([player(fleet), fleet.robot("nora")], "play", None, parts={"NORA": 101})
    assert "TINA" not in out["players"] and "NORA" in out["players"]


@pytest.mark.parametrize("action,ms,pressed", [
    ("pause", 1, True), ("pause", 0, False), ("pause", 2, False),
    ("resume", 2, True), ("resume", 1, False), ("resume", 0, False),
])
def test_pause_resume_guard(fleet, action, ms, pressed):
    fleet.state["nora"]["ms"] = ms                   # M:PLAY toggles: only press it when it does what's asked
    out = music.conduct([fleet.robot("nora")], action)
    time.sleep(music.LEAD_S + 0.3)
    assert out["players"]["NORA"]["ok"]
    assert ("/muPlay" in fleet.paths("nora")) is pressed
    assert ("skipped" in out["players"]["NORA"]) is (not pressed)


def test_refusals(fleet):
    assert not music.conduct([player(fleet)], "dance")["ok"]
    assert "track number" in music.conduct([player(fleet)], "play")["error"]
    assert "nobody has registered" in music.conduct([], "play", 100)["error"]
