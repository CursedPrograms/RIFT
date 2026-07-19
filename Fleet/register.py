"""
Announces this RIFT instance to a NORA hub as the fleet authority.

NORA (https://github.com/CursedPrograms/NORA-Robot-v00) is the network's
always-on node at a fixed address, so she hosts the fleet registry that
`PC App/PyGame/registration.py` and `PC App/App/registration.cpp` used to
find by brute-force scanning the whole subnet for `/robots` on port 5000.
This module lets RIFT claim that registry's authority instead of NORA
self-authoring it: while RIFT keeps heartbeating here, NORA defers her
`/robots` response to point at RIFT. If RIFT stops calling this (closed,
crashed, network dropped), the registration simply expires on NORA's side
and she reclaims the role automatically — no explicit handoff required.
"""

import threading
import time

import requests

NORA_HOST = "192.168.4.1"   # NORA's fixed WiFi AP address
NORA_PORT = 5000            # NORA's fleet-registry port
HEARTBEAT_SECS = 10         # must be well under NORA's FLEET_TTL_MS (20s) or the authority will flap


def _announce(host, port, name, capabilities):
    try:
        requests.post(
            f"http://{host}:{port}/register",
            data={
                "name": name,
                "type": "fleet_manager",
                "capabilities": ",".join(capabilities),
            },
            timeout=2,
        )
        return True
    except requests.RequestException:
        return False


def start_fleet_authority(name="RIFT", capabilities=None,
                           host=NORA_HOST, port=NORA_PORT,
                           interval=HEARTBEAT_SECS):
    """
    Start a background heartbeat thread that repeatedly registers this
    RIFT instance with NORA as the fleet authority. Safe to call even if
    NORA isn't reachable yet (e.g. still booting, or not connected to her
    WiFi AP) — it just keeps retrying on the same interval.

    Returns the daemon thread so callers can join() it if they want to,
    though that's rarely necessary since it never returns on its own.
    """
    capabilities = capabilities or ["fleet_management", "monitoring"]

    def _loop():
        while True:
            _announce(host, port, name, capabilities)
            time.sleep(interval)

    t = threading.Thread(target=_loop, daemon=True, name="nora-fleet-authority")
    t.start()
    return t


if __name__ == "__main__":
    print(f"Announcing RIFT to NORA at {NORA_HOST}:{NORA_PORT} "
          f"every {HEARTBEAT_SECS}s as the fleet authority (Ctrl+C to stop)...")
    start_fleet_authority()
    try:
        while True:
            time.sleep(1)
    except KeyboardInterrupt:
        print("\nstopped")
