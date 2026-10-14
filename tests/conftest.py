"""Shared test setup for RIFT: offline, no robots, and RIFT's real mission_log.json is never touched.

fleet_server: one local Flask app playing every robot the relay talks to, each under its own
path (http://127.0.0.1:<port>/nora/..., /kida00/..., /mila/...), recording what it was sent.
Run from the RIFT folder:  venv\\Scripts\\python -m pytest tests
"""
import os
import sys
import threading

import pytest
from flask import Flask, jsonify, request
from werkzeug.serving import make_server

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from Fleet import mission  # noqa: E402

REAL_LOG = mission.PATH


@pytest.fixture(autouse=True)
def private_mission_log(tmp_path, monkeypatch):
    """Every test writes its mission log to a temp file, never RIFT's real one."""
    monkeypatch.setattr(mission, "PATH", str(tmp_path / "mission_log.json"))
    monkeypatch.setattr(mission, "_entries", [])
    monkeypatch.setattr(mission, "_started", None)
    yield


class Fleet:
    """What the fake robots were sent, and what they answer (tests change .state)."""

    def __init__(self):
        self.hits = []          # (robot, method, path, json body or query string)
        self.state = {}
        self.reset()

    def reset(self):
        self.hits.clear()
        self.state.clear()
        self.state.update({
            "nora": {"F": 34.5, "L": 120, "B": -1, "R": 80, "mode": 0, "ms": 0, "lock": 1, "now": 600000},
            "kida00": {"direction": "FORWARD", "music_playing": True, "mode": "USER"},
            "kida01": {"mode": "MANUAL", "moving": False, "music_on": True, "motor_lock": True,
                       "sensors": {"US0": 41.0, "US1": 77.5, "IMU": "ok"}},
            "mila": {"dist": 23.0, "ml": 1, "mr": 0, "scan_l": 120, "scan_f": 23, "scan_r": 999, "scan_ms": 2500},
            "arm": {"connected": True, "motors": {"1": {"angle": 90}, "2": {"angle": 45}}},
            "whip": {"controlMode": 2, "move": 0, "sysState": 0, "distance": 55},
        })
        self.mila_scan = (200, {"ok": True, "left": 120, "front": 23, "right": 999})

    def robot(self, name, **extra):
        """A roster entry pointing at the fake robot `name`."""
        return dict({"name": name.upper(), "ip": "127.0.0.1", "capabilities": [],
                     "url": f"{self.base}/{name.lower()}/"}, **extra)

    def paths(self, robot):
        return [h[2] for h in self.hits if h[0] == robot]


@pytest.fixture(scope="session")
def _server():
    fleet = Fleet()
    app = Flask("fake_fleet")

    @app.route("/<robot>/<path:path>", methods=["GET", "POST"])
    def any_robot(robot, path):
        body = request.get_json(silent=True) if request.method == "POST" else request.query_string.decode()
        fleet.hits.append((robot, request.method, "/" + path, body))
        st = fleet.state.get(robot, {})
        if robot == "nora" and path == "sensors":
            return jsonify(st)
        if robot == "nora" and path == "talk":
            return jsonify({"now": st["now"]})
        if path == "status":
            return jsonify(st)
        if robot == "mila" and path == "scan":
            code, out = fleet.mila_scan
            return jsonify(out), code
        if path == "do":
            return jsonify({"ok": True, "did": body.get("action")})
        return "OK"

    @app.route("/music", methods=["POST"])
    def player():
        fleet.hits.append(("player", "POST", "/music", request.get_json()))
        return jsonify({"ok": True})

    srv = make_server("127.0.0.1", 0, app, threaded=True)
    fleet.base = f"http://127.0.0.1:{srv.server_port}"
    fleet.port = srv.server_port
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    yield fleet
    srv.shutdown()


@pytest.fixture
def fleet(_server):
    _server.reset()
    return _server
