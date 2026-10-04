"""
bt_autopair.py - pair with the fleet's Bluetooth robots automatically.

Looks for unpaired Bluetooth devices whose name is one of the fleet's
(NORA's ESP32 advertises "NORA") and pairs with them, so the Bluetooth
transport (bt_link.py, the controllers' --bt) works without a trip to the
Settings app. NORA uses Secure Simple Pairing ("Just Works"), so no PIN.

  Windows   WinRT DeviceInformation.Pairing, via PowerShell (no extra packages)
  Linux     bluetoothctl (KIDA's Raspberry Pi, a Linux RIFT)
  no radio  says so once and does nothing - nothing without Bluetooth errors

    python Fleet/bt_autopair.py           pair now, print what happened
    start_autopair()                       from RIFT: try now and every 10 min
"""

import os
import shutil
import subprocess
import sys
import threading
import time

FLEET_BT_NAMES = ["NORA", "WHIP", "KIDA00", "KIDA01", "MILA", "IDA", "DREAM"]
EVERY_S = 600

_PS = r"""
$ErrorActionPreference = 'Stop'
$names = @(%NAMES%)
try {
  Add-Type -AssemblyName System.Runtime.WindowsRuntime
  $asTask = ([System.WindowsRuntimeSystemExtensions].GetMethods() | Where-Object {
      $_.Name -eq 'AsTask' -and $_.GetParameters().Count -eq 1 -and $_.GetParameters()[0].ParameterType.Name -eq 'IAsyncOperation`1' })[0]
  function Await($op, [Type]$t) { $task = $asTask.MakeGenericMethod($t).Invoke($null, @($op)); $null = $task.Wait(20000); $task.Result }
  $null = [Windows.Devices.Enumeration.DeviceInformation, Windows.Devices.Enumeration, ContentType = WindowsRuntime]
  $null = [Windows.Devices.Bluetooth.BluetoothAdapter, Windows.Devices.Bluetooth, ContentType = WindowsRuntime]
  $null = [Windows.Devices.Bluetooth.BluetoothDevice, Windows.Devices.Bluetooth, ContentType = WindowsRuntime]
  $adapter = Await ([Windows.Devices.Bluetooth.BluetoothAdapter]::GetDefaultAsync()) ([Windows.Devices.Bluetooth.BluetoothAdapter])
  if ($null -eq $adapter) { 'NO_RADIO'; exit 0 }
  $sel = [Windows.Devices.Bluetooth.BluetoothDevice]::GetDeviceSelectorFromPairingState($false)
  $found = Await ([Windows.Devices.Enumeration.DeviceInformation]::FindAllAsync($sel)) ([Windows.Devices.Enumeration.DeviceInformationCollection])
  foreach ($d in $found) {
    if ($names -contains $d.Name -and $d.Pairing.CanPair) {
      $r = Await ($d.Pairing.PairAsync()) ([Windows.Devices.Enumeration.DevicePairingResult])
      "PAIRED $($d.Name) $($r.Status)"
    }
  }
  'DONE'
} catch { "ERROR $($_.Exception.Message)" }
"""


def pair_windows(names):
    script = _PS.replace("%NAMES%", ",".join(f"'{n}'" for n in names))
    try:
        out = subprocess.run(["powershell", "-NoProfile", "-ExecutionPolicy", "Bypass", "-Command", script],
                             capture_output=True, text=True, timeout=90).stdout
    except (OSError, subprocess.SubprocessError) as e:
        return None, [f"powershell failed: {e}"]
    lines = [l.strip() for l in out.splitlines() if l.strip()]
    if "NO_RADIO" in lines:
        return None, []
    return [l[7:] for l in lines if l.startswith("PAIRED ")], [l for l in lines if l.startswith("ERROR")]


def pair_linux(names):
    ctl = shutil.which("bluetoothctl")
    if not ctl:
        return None, []
    show = subprocess.run([ctl, "show"], capture_output=True, text=True, timeout=10).stdout
    if "Controller" not in show:
        return None, []                                   # no radio
    subprocess.run([ctl, "--timeout", "12", "scan", "on"], capture_output=True, timeout=30)
    devices = subprocess.run([ctl, "devices"], capture_output=True, text=True, timeout=10).stdout
    paired = subprocess.run([ctl, "devices", "Paired"], capture_output=True, text=True, timeout=10).stdout
    done = []
    for line in devices.splitlines():
        parts = line.split(" ", 2)                       # "Device AA:BB:.. NAME"
        if len(parts) == 3 and parts[2] in names and parts[1] not in paired:
            r = subprocess.run([ctl, "pair", parts[1]], capture_output=True, text=True, timeout=40)
            subprocess.run([ctl, "trust", parts[1]], capture_output=True, timeout=10)
            done.append(f"{parts[2]} {'Paired' if r.returncode == 0 else 'Failed'}")
    return done, []


def pair_fleet(names=FLEET_BT_NAMES):
    """Returns (list of "NAME status" for new pairings, or None if there's no Bluetooth), errors."""
    if os.name == "nt":
        return pair_windows(names)
    if sys.platform.startswith("linux"):
        return pair_linux(names)
    return None, []


def start_autopair(log=print):
    def loop():
        told_no_radio = False
        while True:
            done, errors = pair_fleet()
            if done is None:
                if not told_no_radio:
                    log("[RIFT] No Bluetooth on this machine - skipping auto-pairing")
                    told_no_radio = True
            else:
                for d in done:
                    log(f"[RIFT] Bluetooth: {d}")
            for e in errors:
                log(f"[RIFT] Bluetooth auto-pair: {e}")
            time.sleep(EVERY_S)

    t = threading.Thread(target=loop, daemon=True, name="bt-autopair")
    t.start()
    return t


if __name__ == "__main__":
    done, errors = pair_fleet()
    if done is None:
        print("No Bluetooth radio here - nothing to pair.")
    else:
        print("New pairings:", ", ".join(done) if done else "none (nothing new in range)")
    for e in errors:
        print(e)
