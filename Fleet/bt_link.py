"""
Bluetooth link to NORA, used by register.py's heartbeat loop when RIFT's dashboard "Connection Mode" is
switched to Bluetooth instead of the default HTTP-over-WiFi path.

It speaks the fleet's one Bluetooth protocol (fleet_bt.py, the same for every robot, NORA included):
RIFT registers in NORA's fleet list exactly as over WiFi, POST /register on her port 5000, carried over
her Bluetooth serial as ">POST :5000/register<TAB>name=RIFT&type=...". Requires the PC be paired with
"NORA"; `port` is the COM port that pairing made (Windows), /dev/rfcommN (Linux), or her address.
"""

from urllib.parse import urlencode

from Fleet import fleet_bt

NORA_WEB_PORT, NORA_FLEET_PORT = 5002, 5000


class BtFleetLink:
    def __init__(self, port, timeout=2):
        self.session = fleet_bt.BtSession(port, timeout=timeout, home_port=NORA_WEB_PORT)

    def register(self, name, capabilities, fleet_type="fleet_manager"):
        r = self.session.post(f"http://nora:{NORA_FLEET_PORT}/register",
                              data=urlencode({"name": name, "type": fleet_type,
                                              "capabilities": ",".join(capabilities)}))
        return r.status_code == 200

    def close(self):
        self.session.close()
