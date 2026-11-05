"""fleet_net.py - which of this PC's network devices is the internet, and which carries the fleet.

RIFT is the top of the fleet's WiFi ladder: the robots look for a network called "RIFT" (the fleet
password) and find RIFT at its gateway, on :5000. A PC often has two network devices, and which does
what depends on the PC:

    this PC   internet: Ethernet (the home network)       fleet: a WiFi dongle, broadcasting "RIFT"
    other PC  internet: a WiFi dongle (the home WiFi)      fleet: Ethernet, with a router on it

The choice is saved in network.json (this PC's own, gitignored). RIFT broadcasts by itself when
it starts and keeps it up (Windows turns an idle hotspot off after a while); "Stop broadcasting"
on the page turns that off until "Broadcast RIFT" again. Broadcasting means:

    fleet device is WiFi      Windows' Mobile Hotspot, named RIFT with the fleet password, sharing the
                              internet device's connection. RIFT is 192.168.137.1 on it.
    fleet device is Ethernet  Internet Connection Sharing from the internet device to that port: RIFT
                              becomes 192.168.137.1 there and hands out addresses. The router on it must
                              be in access point mode (no DHCP of its own) with its WiFi named RIFT and
                              the fleet password, so the robots' gateway is RIFT. Needs RIFT run as admin.

Windows only (the WiFi ladder's Linux side is fleet_ladder.py's nmcli).
"""

import json
import os
import subprocess
import sys
import threading
import time

WINDOWS = sys.platform.startswith("win")
FLEET_SSID = "RIFT"
FLEET_PASSWORD = "mmvbkbak"    # the fleet's, the same as every robot's secrets.h (fleet_ladder.py)
HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
CONFIG = os.path.join(HERE, "network.json")


def _ps(script, timeout=60):
    """Run a PowerShell script; (exit code, output). Never raises."""
    try:
        r = subprocess.run(["powershell.exe", "-NoProfile", "-NonInteractive", "-Command", script],
                           capture_output=True, text=True, timeout=timeout, creationflags=0x08000000)
        return r.returncode, ((r.stdout or "") + (r.stderr or "")).strip()
    except (OSError, subprocess.TimeoutExpired) as e:
        return 1, str(e)


def devices():
    """The PC's physical network devices: [{name, description, kind (wifi/ethernet), up, internet}]."""
    if not WINDOWS:
        return []
    code, out = _ps(
        "$net = @{}; Get-NetConnectionProfile -ErrorAction SilentlyContinue | ForEach-Object { $net[$_.InterfaceAlias] = "
        "\"$($_.IPv4Connectivity)\" }; "
        "@(Get-NetAdapter -Physical | ForEach-Object { [pscustomobject]@{ name = $_.Name; description = $_.InterfaceDescription; "
        "media = \"$($_.PhysicalMediaType)\"; up = ($_.Status -eq 'Up'); internet = ($net[$_.Name] -eq 'Internet') } }) | "
        "ConvertTo-Json -Compress")
    try:
        rows = json.loads(out) if code == 0 and out else []
    except ValueError:
        return []
    if isinstance(rows, dict):
        rows = [rows]
    return [{"name": r["name"], "description": r["description"], "up": bool(r["up"]), "internet": bool(r["internet"]),
             "kind": "wifi" if "802.11" in r["media"] or "Wireless" in r["media"] else "ethernet"} for r in rows]


def load():
    try:
        with open(CONFIG, encoding="utf-8") as f:
            return json.load(f)
    except (OSError, ValueError):
        return {}


def save(cfg):
    with open(CONFIG, "w", encoding="utf-8") as f:
        json.dump(cfg, f, indent=2)


def auto():
    """Broadcast by itself? Yes unless "Stop broadcasting" was pressed."""
    return load().get("auto", True)


def choice(devs=None):
    """The saved internet and fleet devices, or a guess: the one with internet, and another one
    (a WiFi one first)."""
    devs = devices() if devs is None else devs
    cfg = load()
    names = [d["name"] for d in devs]
    internet = cfg.get("internet") if cfg.get("internet") in names else next((d["name"] for d in devs if d["internet"]), None)
    others = [d for d in devs if d["name"] != internet]
    fleet = cfg.get("fleet") if cfg.get("fleet") in names else next(
        (d["name"] for d in sorted(others, key=lambda d: d["kind"] != "wifi")), None)
    return internet, fleet


# ── The two ways to broadcast ─────────────────────────────────────────────────

_TETHER = r"""
Add-Type -AssemblyName System.Runtime.WindowsRuntime
$ops = [System.WindowsRuntimeSystemExtensions].GetMethods() | Where-Object { $_.Name -eq 'AsTask' -and $_.GetParameters().Count -eq 1 }
function Await($op, $type) {
  $m = ($ops | Where-Object { $_.GetParameters()[0].ParameterType.Name -eq 'IAsyncOperation`1' })[0].MakeGenericMethod($type)
  $t = $m.Invoke($null, @($op)); $t.Wait(-1) | Out-Null; $t.Result }
function AwaitAction($op) {
  $m = ($ops | Where-Object { $_.GetParameters()[0].ParameterType.Name -eq 'IAsyncAction' })[0]
  $t = $m.Invoke($null, @($op)); $t.Wait(-1) | Out-Null }
$NI = [Windows.Networking.Connectivity.NetworkInformation,Windows.Networking.Connectivity,ContentType=WindowsRuntime]
$guid = (Get-NetAdapter -Name '%INTERNET%' -ErrorAction SilentlyContinue).InterfaceGuid
$p = $NI::GetConnectionProfiles() | Where-Object { $_.NetworkAdapter -and ('{' + $_.NetworkAdapter.NetworkAdapterId.ToString() + '}') -eq $guid } | Select-Object -First 1
if (-not $p) { $p = $NI::GetInternetConnectionProfile() }
if (-not $p) { 'the internet device has no connection to share'; exit 2 }
$tm = [Windows.Networking.NetworkOperators.NetworkOperatorTetheringManager,Windows.Networking.NetworkOperators,ContentType=WindowsRuntime]::CreateFromConnectionProfile($p)
$rt = [Windows.Networking.NetworkOperators.NetworkOperatorTetheringOperationResult,Windows.Networking.NetworkOperators,ContentType=WindowsRuntime]
switch ('%ACTION%') {
  'state' { "$($tm.TetheringOperationalState)|$($tm.GetCurrentAccessPointConfiguration().Ssid)|$($tm.ClientCount)" }
  'start' {
    $c = $tm.GetCurrentAccessPointConfiguration(); $c.Ssid = '%SSID%'; $c.Passphrase = '%PW%'
    AwaitAction ($tm.ConfigureAccessPointAsync($c))
    $r = Await ($tm.StartTetheringAsync()) $rt; "$($r.Status) $($r.AdditionalErrorMessage)"
    if ($r.Status -ne 'Success') { exit 1 } }
  'stop' { $r = Await ($tm.StopTetheringAsync()) $rt; "$($r.Status)" }
}
"""

_ICS = r"""
$share = New-Object -ComObject HNetCfg.HNetShare
function Conf($name) { foreach ($c in $share.EnumEveryConnection) { $p = $share.NetConnectionProps.Invoke($c); if ($p.Name -eq $name) { return $share.INetSharingConfigurationForINetConnection.Invoke($c) } } }
$pub = Conf '%INTERNET%'; $priv = Conf '%FLEET%'
if (-not $pub -or -not $priv) { 'a device was not found'; exit 2 }
switch ('%ACTION%') {
  'state' { "$($pub.SharingEnabled -and $priv.SharingEnabled)" }
  'start' {
    foreach ($c in $share.EnumEveryConnection) { $s = $share.INetSharingConfigurationForINetConnection.Invoke($c); if ($s.SharingEnabled) { $s.DisableSharing() } }
    $pub.EnableSharing(0); $priv.EnableSharing(1); 'Success' }
  'stop' { $pub.DisableSharing(); $priv.DisableSharing(); 'Success' }
}
"""


def _q(s):
    return str(s or "").replace("'", "")


def _tether(action, internet):
    script = (_TETHER.replace("%ACTION%", action).replace("%INTERNET%", _q(internet))
              .replace("%SSID%", FLEET_SSID).replace("%PW%", FLEET_PASSWORD))
    return _ps(script)


def _ics(action, internet, fleet):
    return _ps(_ICS.replace("%ACTION%", action).replace("%INTERNET%", _q(internet)).replace("%FLEET%", _q(fleet)))


def _kind(devs, name):
    return next((d["kind"] for d in devs if d["name"] == name), None)


def status():
    """What the page shows: the devices, the choice, and whether the fleet network is up."""
    devs = devices()
    internet, fleet = choice(devs)
    out = {"supported": WINDOWS, "devices": devs, "internet": internet, "fleet": fleet, "auto": auto(),
           "ssid": FLEET_SSID, "broadcasting": False, "clients": 0, "how": None, "note": ""}
    if not WINDOWS or not internet or not fleet:
        return out
    if _kind(devs, fleet) == "wifi":
        out["how"] = "hotspot"
        code, text = _tether("state", internet)
        state, _, rest = text.partition("|")
        ssid, _, clients = rest.partition("|")
        out["broadcasting"] = code == 0 and state.strip() == "On" and ssid == FLEET_SSID
        out["clients"] = int(clients) if clients.strip().isdigit() else 0
    else:
        out["how"] = "router"
        code, text = _ics("state", internet, fleet)
        out["broadcasting"] = code == 0 and text.strip() == "True"
        out["note"] = (f"The router on {fleet} broadcasts: set it to access point mode, WiFi name {FLEET_SSID}, "
                       "the fleet password.")
    return out


def choose(internet, fleet):
    if internet and internet == fleet:
        return False, "the internet and the fleet need two different devices"
    names = [d["name"] for d in devices()]
    for n in (internet, fleet):
        if n not in names:
            return False, f"no device called {n}"
    cfg = load()
    cfg.update({"internet": internet, "fleet": fleet})
    save(cfg)
    return True, "saved"


def broadcast(on, remember=True):
    """Start or stop the fleet network on the chosen devices. (ok, message). remember: the page's
    buttons - stopping keeps it off (no auto broadcast) until it's started again."""
    if remember:
        cfg = load()
        cfg["auto"] = bool(on)
        save(cfg)
    if not WINDOWS:
        return False, "broadcasting from RIFT works on Windows; on Linux the ladder (nmcli) hosts"
    devs = devices()
    internet, fleet = choice(devs)
    if not internet or not fleet:
        return False, "choose an internet device and a fleet device first"
    if _kind(devs, fleet) == "wifi":
        code, text = _tether("start" if on else "stop", internet)
        if code and on:
            return False, f"the Mobile Hotspot didn't start: {text}"
        return True, (f"broadcasting {FLEET_SSID} on {fleet}, sharing {internet}" if on else "stopped")
    code, text = _ics("start" if on else "stop", internet, fleet)
    if code or "Success" not in text:
        need_admin = "denied" in text.lower() or "0x80070005" in text
        return False, ("sharing to the router needs RIFT run as administrator" if need_admin
                       else f"sharing didn't start: {text}")
    return True, (f"sharing {internet} to the router on {fleet}: RIFT is 192.168.137.1 there" if on else "stopped")


KEEP_S = 60   # how often the auto broadcast checks it's still up


def keep_broadcasting(log=print):
    """A daemon thread: broadcast the fleet network when RIFT starts, and bring it back whenever it
    drops (Windows switches an idle hotspot off), unless "Stop broadcasting" was pressed."""
    def run():
        said = None
        while True:
            try:
                if WINDOWS and auto():
                    st = status()
                    if st["internet"] and st["fleet"] and not st["broadcasting"]:
                        ok, msg = broadcast(True, remember=False)
                        if msg != said:
                            log(f"[RIFT] network: {msg}")
                            said = msg
            except Exception as e:
                log(f"[RIFT] network: {e}")
            time.sleep(KEEP_S)

    t = threading.Thread(target=run, daemon=True, name="fleet-broadcast")
    t.start()
    return t
