"""Fleet/relay.py: ask and do for every robot, through fake robots (conftest.fleet)."""
import os

import pytest

from Fleet import mission, relay


@pytest.fixture
def slept(monkeypatch):
    """Timed drives don't really wait: what they would have slept is recorded."""
    waits = []
    monkeypatch.setattr(relay.time, "sleep", waits.append)
    return waits


class Board:
    """RIFT's own IR board, for IDA when NORA is away."""
    connected = True

    def __init__(self):
        self.sent = []

    def link(self, device, cmd):
        self.sent.append((device, cmd))
        return True


# ---------------------------------------------------------------- tiers
@pytest.mark.parametrize("action,level", [
    ("music_stop", "harmless"), ("scan", "harmless"), ("lock_wheels", "harmless"), ("stop", "harmless"),
    ("forward", "moving"), ("joint", "moving"), ("rest", "moving"),
    ("unlock", "never"), ("motorlock_off", "never"), ("motor_lock_off", "never"), ("motorlockOff", "never"), ("reboot", "never"), ("pin", "never"),
])
def test_tiers(action, level):
    assert relay.tier(action) == level


# ---------------------------------------------------------------- ask: the core fields
def test_ask_nora_core(fleet):
    code, out = relay.ask([fleet.robot("nora")], "NORA", "test")
    core = out["core"]
    assert code == 200 and out["via"] == "rift" and "music_stop" in out["does"]
    assert core["mode"] == "manual" and core["music"] == "stopped" and core["wheels_locked"] is True
    assert core["distances_cm"] == {"front": 34.5, "left": 120, "back": -1, "right": 80}
    assert fleet.paths("nora") == ["/sensors"]


def test_ask_mila_scan(fleet):
    code, out = relay.ask([fleet.robot("mila")], "mila", "test")
    core = out["core"]
    assert code == 200 and core["moving"] is True and core["distances_cm"] == {"front": 23.0}
    assert core["scan"] == {"left": 120, "front": 23, "right": 999, "age_s": 2.5}
    assert out["does"] == ["scan"]


def test_ask_mila_never_scanned(fleet):
    fleet.state["mila"].update(scan_ms=-1)
    assert "scan" not in relay.ask([fleet.robot("mila")], "MILA")[1]["core"]


def test_ask_kida00_old_status(fleet):
    core = relay.ask([fleet.robot("kida00")], "KIDA00")[1]["core"]
    assert core["moving"] is True and core["music"] == "playing" and "wheels_locked" not in core


def test_ask_kida00_new_status(fleet):
    fleet.state["kida00"] = {"direction": "FORWARD", "moving": False, "music": "stopped",
                             "music_playing": True, "motor_lock": True, "uptime_s": 12}
    core = relay.ask([fleet.robot("kida00")], "KIDA00")[1]["core"]
    assert core["moving"] is False                 # her own "moving" wins over the last direction
    assert core["music"] == "stopped" and core["wheels_locked"] is True


def test_ask_kida01_core(fleet):
    core = relay.ask([fleet.robot("kida01")], "KIDA01")[1]["core"]
    assert core["distances_cm"] == {"us0": 41.0, "us1": 77.5}
    assert core["music"] == "playing" and core["wheels_locked"] is True


def test_ask_arm_and_whip(fleet):
    arm = relay.ask([fleet.robot("arm")], "ARM")[1]
    assert arm["core"]["board_connected"] is True and arm["core"]["joints"] == {"1": 90, "2": 45}
    assert "motor" in arm["note"]
    whip = relay.ask([fleet.robot("whip")], "WHIP")[1]
    assert whip["core"]["mode"] == "web" and whip["core"]["moving"] is False
    assert whip["core"]["state"] == "active" and whip["core"]["distances_cm"] == {"front": 55}
    assert whip["does"] == [] and "PIN" in whip["note"]


def test_ask_ida_ir_only(fleet, monkeypatch):
    code, out = relay.ask([fleet.robot("nora")], "IDA")
    assert code == 200 and out["status"] is None and "through NORA" in out["note"]
    assert fleet.hits == []                        # nothing to ask: IR is one way
    monkeypatch.setattr(relay, "board", Board())
    assert "through RIFT" in relay.ask([], "IDA")[1]["note"]
    monkeypatch.setattr(relay, "board", None)
    code, out = relay.ask([], "IDA")
    assert code == 404 and "IR only" in out["error"]


def test_ask_missing_and_silent(fleet):
    code, out = relay.ask([], "MILA")
    assert code == 404 and out["error"] == "MILA isn't online (not on RIFT's roster)"
    dead = fleet.robot("nora", url="http://127.0.0.1:9/")     # nothing listens on port 9
    code, out = relay.ask([dead], "NORA")
    assert code == 502 and "no answer" in out["error"]


# ---------------------------------------------------------------- do: tiers and answers
def test_harmless_goes_ahead(fleet):
    code, out = relay.do([fleet.robot("nora")], "NORA", "music_stop", asker="test")
    assert code == 200 and out["ok"] and out["tier"] == "harmless"
    assert fleet.paths("nora") == ["/muStop"]


def test_music_play_skipped_when_playing(fleet):
    fleet.state["nora"]["ms"] = 1                  # M:PLAY would pause her
    code, out = relay.do([fleet.robot("nora")], "NORA", "music_play")
    assert code == 200 and "skipped" in out["answer"] and "/muPlay" not in fleet.paths("nora")
    fleet.state["nora"]["ms"] = 0
    relay.do([fleet.robot("nora")], "NORA", "music_play")
    assert "/muPlay" in fleet.paths("nora")


def test_moving_needs_confirmed(fleet, slept):
    code, out = relay.do([fleet.robot("nora")], "NORA", "forward", {"seconds": 1})
    assert code == 403 and out["needs"] == "confirmed" and fleet.hits == []
    code, out = relay.do([fleet.robot("nora")], "NORA", "forward", {"seconds": 1}, confirmed=True)
    assert code == 200 and fleet.paths("nora") == ["/fw", "/stop"] and slept == [1.0]


def test_drive_capped(fleet, slept):
    relay.do([fleet.robot("nora")], "NORA", "turn_left", {"seconds": 99}, confirmed=True)
    relay.do([fleet.robot("nora")], "NORA", "back", {"seconds": "soon"}, confirmed=True)
    assert slept == [relay.MAX_DRIVE_S, 0.5]


def test_never_relayed(fleet):
    code, out = relay.do([fleet.robot("nora")], "NORA", "motorlock_off", confirmed=True)
    assert code == 403 and out["tier"] == "never" and fleet.hits == []
    assert "never relayed" in out["error"]


def test_unknown_action_and_missing_robot(fleet):
    code, out = relay.do([fleet.robot("nora")], "NORA", "dance", confirmed=True)
    assert code == 400 and "she can:" in out["error"] and "uv_on" in out["does"]
    code, out = relay.do([fleet.robot("whip")], "WHIP", "forward", confirmed=True)
    assert code == 400 and "PIN" in out["error"]
    code, out = relay.do([], "KIDA01", "photo")
    assert code == 404 and "isn't online" in out["error"]
    assert relay.do([fleet.robot("nora")], "NORA", "")[0] == 400


def test_kida00_mapping(fleet, slept):
    relay.do([fleet.robot("kida00")], "KIDA00", "music_play")
    relay.do([fleet.robot("kida00")], "KIDA00", "forward", {"seconds": 0.5}, confirmed=True)
    assert [h[3] for h in fleet.hits] == [{"command": "music"}, {"command": "forward"}, {"command": "stop"}]


def test_own_do_wins_over_mapping(fleet):
    caps = ["do:stop", "do:forward", "do:music_play", "music:5003"]
    me = fleet.robot("kida00", capabilities=caps)
    code, out = relay.do([me], "KIDA00", "forward", {"seconds": 1.5}, confirmed=True)
    assert code == 200 and out["via"] == "robot"
    assert fleet.hits == [("kida00", "POST", "/do", {"action": "forward", "seconds": 1.5})]
    assert relay.does(me) == (["stop", "forward", "music_play"], "robot")


def test_arm_joint(fleet):
    code, out = relay.do([fleet.robot("arm")], "ARM", "joint", {"motor": "3", "angle": 120}, confirmed=True)
    assert code == 200 and fleet.hits[-1][2:] == ("/cmd", "motor=3&angle=120")
    code, out = relay.do([fleet.robot("arm")], "ARM", "joint", {"motor": 3}, confirmed=True)
    assert code == 400 and "needs motor, angle" in out["answer"]["error"]


def test_ida_via_nora_and_board(fleet, slept, monkeypatch):
    relay.do([fleet.robot("nora")], "IDA", "forward", {"seconds": 1}, confirmed=True)
    assert [(h[2], h[3]) for h in fleet.hits] == [("/ida", "c=fw"), ("/ida", "c=stop")]
    board = Board()
    monkeypatch.setattr(relay, "board", board)
    code, out = relay.do([], "IDA", "stop")
    assert code == 200 and board.sent == [("ida", "stop")]


def test_mila_scan_and_refusal(fleet):
    code, out = relay.do([fleet.robot("mila")], "MILA", "scan")
    assert code == 200 and out["answer"]["front"] == 23 and fleet.paths("mila") == ["/scan"]
    fleet.mila_scan = (409, {"ok": False, "error": "obstacle mode"})
    code, out = relay.do([fleet.robot("mila")], "MILA", "scan")
    assert code == 409 and out["ok"] is False          # her refusal passes through as it is
    code, out = relay.do([fleet.robot("mila")], "MILA", "forward", confirmed=True)
    assert code == 400 and out["error"] == "MILA can't forward; she can: scan"     # driving her needs the PIN


def test_mission_log_is_private(fleet):
    before = os.path.getmtime(REAL) if os.path.exists(REAL) else None
    relay.do([fleet.robot("nora")], "NORA", "uv_on", asker="pytest")
    assert any("pytest told NORA to uv_on" in e["text"] for e in mission._entries)
    assert mission.PATH != REAL and os.path.exists(mission.PATH)
    assert (os.path.getmtime(REAL) if os.path.exists(REAL) else None) == before


from conftest import REAL_LOG as REAL  # noqa: E402


def test_kida01_mapping(fleet, slept):
    me = fleet.robot("kida01")
    # music_on is already true: pressing play would skip the song, so it's skipped
    code, out = relay.do([me], "KIDA01", "music_play")
    assert code == 200 and out["answer"]["skipped"]
    relay.do([me], "KIDA01", "photo")
    relay.do([me], "KIDA01", "lock_wheels")
    posts = [h[3] for h in fleet.hits if h[1] == "POST"]
    assert posts == [{"command": "photo"}, {"command": "motor_lock_on"}]


def test_kida01_drive_feeds_her_dead_man_switch(fleet, slept):
    fleet.hits.clear()
    code, out = relay.do([fleet.robot("kida01")], "KIDA01", "forward", {"seconds": 1.0}, confirmed=True)
    assert code == 200 and out["answer"]["moved_s"] == 1.0
    cmds = [h[3]["command"] for h in fleet.hits]
    # the go every 0.3 s (her switch stops her 0.8 s after the last), then the stop
    assert cmds == ["move_forward"] * 4 + ["move_stop"]
    assert sum(slept) == pytest.approx(1.0)


def test_kida01_moves_ask_and_never_unlocks(fleet):
    code, out = relay.do([fleet.robot("kida01")], "KIDA01", "mind_mode")
    assert out["tier"] == "moving" and not out["ok"]
    code, out = relay.do([fleet.robot("kida01")], "KIDA01", "motor_lock_off", confirmed=True)
    assert code == 403 and out["tier"] == "never"
