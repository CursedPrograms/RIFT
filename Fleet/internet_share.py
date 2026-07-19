"""
Shares this RIFT instance's existing internet connection (its normal home-
network link) out to every device that joins NORA's WiFi AP.

NORA (https://github.com/CursedPrograms/NORA-Robot-v00) hosts an isolated
WiFi AP (SSID "NORA") with no internet of its own — it's a self-contained
field network for the fleet. RIFT is the one machine that's also expected
to be on the home network, so it's the natural point to bridge the two:
join NORA's AP as a secondary connection over a spare WiFi radio, then let
NetworkManager's "shared" method (its own DHCP server + NAT/IP forwarding)
hand internet access to NORA and anything else parked on her AP — while
RIFT's own default route (Ethernet, home WiFi, whatever it already is) is
left completely alone.
"""

import subprocess
import threading
import time

NORA_SSID      = "NORA"
NORA_PASSWORD  = "12345678"
CHECK_INTERVAL = 30  # seconds between checks that the share is still up


def _nmcli(*args, timeout=20):
    return subprocess.run(["nmcli", *args], capture_output=True, text=True, timeout=timeout)


def _wifi_iface():
    """First WiFi device NetworkManager knows about, or None."""
    try:
        r = _nmcli("-t", "-f", "DEVICE,TYPE", "device", "status")
        for line in r.stdout.splitlines():
            parts = line.split(":")
            if len(parts) >= 2 and parts[1] == "wifi":
                return parts[0]
    except Exception:
        pass
    return None


def _active_connections():
    try:
        r = _nmcli("-t", "-f", "NAME", "connection", "show", "--active")
        return [s.strip() for s in r.stdout.splitlines()]
    except Exception:
        return []


def ensure_internet_share():
    """
    Joins NORA's AP (if not already connected) over a spare WiFi radio and
    marks that connection "shared" so NetworkManager runs DHCP+NAT on it —
    giving NORA and her fleet internet through RIFT. Safe to call
    repeatedly; it's a no-op once already connected and shared. Returns
    True if NORA is joined by the time it returns.
    """
    iface = _wifi_iface()
    if not iface:
        return False

    if NORA_SSID in _active_connections():
        return True

    try:
        existing = _nmcli("-t", "-f", "NAME", "connection", "show")
        if NORA_SSID not in [s.strip() for s in existing.stdout.splitlines()]:
            _nmcli("device", "wifi", "connect", NORA_SSID,
                   "password", NORA_PASSWORD, "ifname", iface, timeout=30)
            # "shared" = NetworkManager runs its own DHCP server + NAT/IP
            # forwarding on this interface, using RIFT's existing default
            # route as the upstream. RIFT's own connection stays untouched.
            _nmcli("connection", "modify", NORA_SSID, "ipv4.method", "shared")
        else:
            _nmcli("connection", "up", NORA_SSID, timeout=30)
        return NORA_SSID in _active_connections()
    except Exception:
        return False


def start_internet_share(interval=CHECK_INTERVAL):
    """
    Start a background thread that keeps NORA's AP joined and shared. Safe
    to call even if NORA isn't in range yet — it just keeps retrying on
    the same interval.

    Returns the daemon thread so callers can join() it if they want to,
    though that's rarely necessary since it never returns on its own.
    """
    def _loop():
        while True:
            ensure_internet_share()
            time.sleep(interval)

    t = threading.Thread(target=_loop, daemon=True, name="nora-internet-share")
    t.start()
    return t


if __name__ == "__main__":
    print(f"Sharing internet to NORA's fleet AP ({NORA_SSID}) "
          f"every {CHECK_INTERVAL}s (Ctrl+C to stop)...")
    start_internet_share()
    try:
        while True:
            time.sleep(1)
    except KeyboardInterrupt:
        print("\nstopped")
