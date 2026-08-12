"""
Bluetooth-serial link to NORA, used by register.py's heartbeat loop when
RIFT's dashboard "Connection Mode" is switched to Bluetooth instead of the
default HTTP-over-WiFi path.

Speaks the fleet-registration half of NORA's Bluetooth protocol
(NORA-Robot-v00's scripts/esp32/esp32.ino, handleBluetooth() 'H' command)
rather than her drive commands: send "H<name>:<cap1,cap2>\n", she replies
"OK\n" or "ERR\n". Requires the PC be paired with "NORA" and have a serial
port bound to that pairing (Linux: sudo rfcomm bind 0 <NORA_MAC>; Windows:
the paired device's outgoing COM port).
"""

DEFAULT_BAUD = 115200


class BtFleetLink:
    def __init__(self, port, baud=DEFAULT_BAUD, timeout=2):
        import serial   # only needed for Bluetooth; pip install pyserial
        self.ser = serial.Serial(port, baud, timeout=timeout)

    def register(self, name, capabilities):
        line = f"H{name}:{','.join(capabilities)}\n"
        self.ser.reset_input_buffer()
        self.ser.write(line.encode())
        reply = self.ser.readline().decode(errors="ignore").strip()
        return reply == "OK"

    def close(self):
        try:
            self.ser.close()
        except Exception:
            pass
