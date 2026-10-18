"""Fleet/fleet_ladder.py: who joins whom, who hosts, moving up, noticing a lost network, and several
programs on one computer. A fake WiFi card; the real one is never touched, and the fleet list runs
on a free port instead of :5000."""
import json
import socket
from urllib.request import Request, urlopen

import pytest

from Fleet import fleet_ladder as fl


class FakeWifi:
    def __init__(self, seen=(), on=None):
        self.seen, self.on, self.ap, self.calls = set(seen), on, None, []

    def scan(self):
        return set(self.seen)

    def connected(self):
        return self.on

    def hosting(self):
        return self.ap is not None

    def join(self, ssid, pw):
        self.calls.append(("join", ssid))
        if ssid not in self.seen:
            return False, "not in range"
        self.ap, self.on = None, ssid
        return True, ""

    def host(self, ssid, pw):
        self.calls.append(("host", ssid))
        self.ap, self.on = ssid, None
        return True, ""

    def stop_hosting(self):
        self.ap = None

    def gateway(self):
        return "192.168.4.1" if self.on else None


def free_port():
    s = socket.socket()
    s.bind(("127.0.0.1", 0))
    port = s.getsockname()[1]
    s.close()
    return port


@pytest.fixture
def make(tmp_path, monkeypatch):
    made = []

    def _make(name, wifi, alive=True):
        lad = fl.FleetLadder(name, enabled=True, wifi=wifi, log=lambda *a: None,
                             local_dir=str(tmp_path), ping=lambda host: alive)
        lad.registry.port = free_port()
        made.append(lad)
        return lad
    yield _make
    for lad in made:
        lad.registry.stop()


def test_the_ladder_order():
    assert fl.LADDER[:4] == ["RIFT", "DREAM", "NINA", "TINA"]
    assert fl.rank("ARMCTL") < fl.rank("NORA") < fl.rank("ARM") < fl.rank("MILA")


def test_joins_the_highest_one_above_it(make):
    w = FakeWifi(seen={"NORA", "DREAM", "MILA", "HomeWifi"})
    assert make("NINA", w).check() == "joined"
    assert w.on == "DREAM"


def test_hosts_when_nobody_above_is_around_and_serves_the_list(make):
    w = FakeWifi(seen={"NORA", "MILA", "HomeWifi"}, on="HomeWifi")
    lad = make("DREAM", w)
    assert lad.check() == "hosting"
    assert w.ap == "DREAM"
    base = f"http://127.0.0.1:{lad.registry.port}"
    assert urlopen(f"{base}/ping").read() == b"DREAM alive"
    urlopen(Request(f"{base}/register", data=b"name=NORA&type=omni&capabilities=music,uv", method="POST"))
    robots = json.loads(urlopen(f"{base}/robots").read())
    assert robots["authority"] == "DREAM"
    assert robots["robots"][0]["name"] == "NORA" and robots["robots"][0]["capabilities"] == ["music", "uv"]
    assert lad.registry_host() == "127.0.0.1"


def test_a_host_moves_up_when_a_higher_one_appears(make):
    w = FakeWifi(seen=set())
    lad = make("TINA", w)
    assert lad.check() == "hosting"
    w.seen.add("RIFT")
    assert lad.check() == "joined"
    assert w.on == "RIFT" and w.ap is None and lad.registry.server is None


def test_moves_up_from_a_lower_network(make):
    w = FakeWifi(seen={"NORA"}, on="NORA")
    lad = make("KIDA00", w)
    assert lad.check() == "joined"
    w.seen.add("NINA")
    lad.check()
    assert w.on == "NINA"


def test_a_lost_network_is_noticed_after_a_few_checks(make):
    w = FakeWifi(seen={"NORA"}, on="NORA")
    lad = make("KIDA00", w, alive=False)        # connected, but NORA's list never answers
    for _ in range(fl.LOST_CHECKS - 1):
        assert lad.check() == "joined"
    assert lad.check() == "hosting"             # nobody else above her: she hosts
    assert w.ap == "KIDA00"


def test_a_lost_network_hands_over_to_the_next_one_up(make):
    w = FakeWifi(seen={"NORA", "WHIP"}, on="NORA")
    lad = make("KIDA00", w)
    lad.check()
    w.seen.discard("NORA")                      # NORA switched off: gone from the scan too
    for _ in range(fl.LOST_CHECKS):
        lad.check()
    assert w.on == "WHIP"


def test_only_the_highest_program_on_a_computer_drives_the_wifi(make):
    w = FakeWifi(seen=set())
    dream, ctl = make("DREAM", w), make("NORACTL", w)
    dream.check()                               # DREAM hosts...
    assert ctl.check() == "riding"              # ...the controller next to it leaves the WiFi alone
    assert ("host", "NORACTL") not in w.calls
    dream._unmark()                             # DREAM closed
    assert ctl.check() == "hosting"


def test_off_unless_asked(tmp_path):
    lad = fl.FleetLadder("DREAM", wifi=FakeWifi(), local_dir=str(tmp_path))
    assert not lad.enabled and lad.start()._thread is None
    with pytest.raises(ValueError):
        fl.FleetLadder("BOB", wifi=FakeWifi())


def test_nmcli_parsing():
    out = {("nmcli", "-t", "-f", "ACTIVE,SSID", "device", "wifi"): "no:HomeWifi\nyes:NORA\n",
           ("nmcli", "-t", "-f", "SSID", "device", "wifi", "list", "--rescan", "yes"): "NORA\n\nDREAM\n",
           ("nmcli", "-t", "-f", "DEVICE,TYPE", "device"): "eth0:ethernet\nwlan1:wifi\n"}
    w = fl.NmcliWifi(sh=lambda args, timeout=30: (0, out.get(tuple(args), "default via 192.168.4.1 dev wlan1")))
    assert w.connected() == "NORA"
    assert w.scan() == {"NORA", "DREAM"}
    assert w.gateway() == "192.168.4.1" and w.ifname == "wlan1"


def test_netsh_parsing():
    nets = "Interface name : Wi-Fi\nThere are 2 networks currently visible.\n\nSSID 1 : RIFT\n    Network type : Infrastructure\n\nSSID 2 : HomeWifi\n"
    iface = "    Name                   : Wi-Fi\n    State                  : connected\n    SSID                   : HomeWifi\n    BSSID                  : aa:bb\n"
    w = fl.NetshWifi(sh=lambda args, timeout=30: (0, nets if "networks" in args else iface))
    assert w.scan() == {"RIFT", "HomeWifi"}
    assert w.connected() == "HomeWifi"
