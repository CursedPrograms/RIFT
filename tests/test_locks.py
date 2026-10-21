"""Fleet/locks.py: every robot's wheel lock at once from the dashboard; unlocking needs the PIN."""
from Fleet import locks, mission, relay


def _roster(fleet):
    return [fleet.robot("nora"), fleet.robot("kida00"), fleet.robot("kida01"), fleet.robot("mila")]


def test_lock_all_reaches_every_robot(fleet, monkeypatch):
    monkeypatch.setattr(relay, "board", None)
    code, out = locks.apply(_roster(fleet), "lock")
    assert code == 200 and out["ok"]
    assert "/motorlockOn" in fleet.paths("nora")
    assert "/motorlockOn" in fleet.paths("kida00")
    assert ("kida01", "POST", "/action", {"command": "motor_lock_on"}) in fleet.hits
    ir = sorted(h[3] for h in fleet.hits if h[0] == "nora" and h[2] == "/link")
    assert ir == ["r=ida&c=lock", "r=mila&c=lock", "r=nika&c=lock", "r=whip&c=lock"]
    assert {r["robot"] for r in out["robots"] if r["ok"]} == {"NORA", "KIDA00", "KIDA01", "IDA", "MILA", "WHIP", "NIKA"}
    assert "locked the whole fleet" in mission.snapshot()["entries"][-1]["text"]


def test_unlock_needs_the_pin(fleet):
    code, out = locks.apply(_roster(fleet), "unlock", "4321")
    assert code == 403 and out["error"] == "wrong PIN"
    assert fleet.hits == []          # nothing was sent, not even over IR (that takes no PIN)


def test_unlock_all_sends_the_pin_to_each_robot(fleet, monkeypatch):
    monkeypatch.setattr(relay, "board", None)
    code, out = locks.apply(_roster(fleet), "unlock", locks.FLEET_PIN)
    assert code == 200 and out["ok"]
    assert ("nora", "GET", "/motorlockOff", f"pw={locks.FLEET_PIN}") in fleet.hits
    assert ("kida00", "GET", "/motorlockOff", f"pw={locks.FLEET_PIN}") in fleet.hits
    assert ("kida01", "POST", "/action", {"command": "motor_lock_off", "password": locks.FLEET_PIN}) in fleet.hits
    assert ("nora", "GET", "/link", "r=whip&c=unlock") in fleet.hits


def test_without_nora_or_the_board_ir_robots_say_so(fleet, monkeypatch):
    monkeypatch.setattr(relay, "board", None)
    code, out = locks.apply([fleet.robot("kida00")], "lock")
    ir = {r["robot"]: r for r in out["robots"] if r["how"] == "IR"}
    assert set(ir) == {"IDA", "MILA", "WHIP", "NIKA"} and not any(r["ok"] for r in ir.values())
    assert out["ok"]                  # KIDA00 still locked


def test_relay_still_never_unlocks(fleet):
    code, out = relay.do([fleet.robot("nora")], "NORA", "motorlock_off", confirmed=True)
    assert code == 403 and out["tier"] == "never"


def test_bad_action(fleet):
    assert locks.apply([], "explode")[0] == 400
