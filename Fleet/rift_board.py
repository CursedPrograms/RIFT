"""
rift_board.py - RIFT's own Arduino (arduino/rift_link): IR transmitter, IR
receiver and buzzer on the hub PC.

It finds the board by the fleet handshake (WHO -> "I am Rift"), but only
after RIFT has been up for a while and only on ports nobody else has open:
opening a port resets the Arduino on it, and ARM and DREAM look for their own
boards the same way when run_all.bat starts everything together. Until it's
found (or if pyserial isn't installed) everything here is a quiet no-op.

    board.link("ida", "fw")       drive a robot over IR, like NORA's /link
    board.say("mila", 0)          beep a phrase, then send it to a robot
    board.talk(7)                 beep a Brainfuck utterance on the buzzer
    board.heard(20)               the last IR frames it picked up
"""

import re
import threading
import time
from collections import deque

try:
    import serial
    from serial.tools import list_ports
except ImportError:
    serial = None

BAUD = 115200
FIRST_LOOK_S = 25        # let ARM and DREAM claim their boards first
RETRY_S = 60
_IAM = re.compile(r"I am (\w+)", re.I)


class RiftBoard:
    def __init__(self, on_ir=None):
        self.port = None
        self._ser = None
        self._lock = threading.Lock()
        self._heard = deque(maxlen=50)
        self._on_ir = on_ir

    @property
    def connected(self):
        return self._ser is not None

    def start(self):
        if serial is None:
            print("[RIFT] pyserial missing - RIFT's own board (IR + buzzer) disabled")
            return
        threading.Thread(target=self._run, daemon=True, name="rift-board").start()

    # -- finding it
    def _probe(self, dev):
        try:
            ser = serial.Serial(dev, BAUD, timeout=0.3)
        except (serial.SerialException, OSError):
            return None                          # busy: someone else's board
        time.sleep(2.0)                          # the UNO resets when the port opens
        ser.reset_input_buffer()
        ser.write(b"WHO\n")
        deadline = time.time() + 1.5
        while time.time() < deadline:
            m = _IAM.search(ser.readline().decode(errors="ignore"))
            if m:
                if m.group(1).lower() == "rift":
                    return ser
                break
        ser.close()
        return None

    def _run(self):
        time.sleep(FIRST_LOOK_S)
        while True:
            if self._ser is None:
                for p in list_ports.comports():
                    ser = self._probe(p.device)
                    if ser:
                        self._ser, self.port = ser, p.device
                        print(f"[RIFT] Own board found on {p.device} (IR + buzzer)")
                        break
                if self._ser is None:
                    time.sleep(RETRY_S)
                    continue
            try:
                line = self._ser.readline().decode(errors="ignore").strip()
            except (serial.SerialException, OSError):
                print("[RIFT] Own board unplugged")
                self._ser, self.port = None, None
                continue
            if line.startswith("IR:"):
                parts = line.split(":")
                frame = {"t": time.time(), "protocol": parts[1] if len(parts) > 1 else "?",
                         "address": parts[2] if len(parts) > 2 else "", "command": parts[3] if len(parts) > 3 else "",
                         "repeat": len(parts) > 4}
                self._heard.append(frame)
                if self._on_ir:
                    try:
                        self._on_ir(frame)
                    except Exception:
                        pass

    # -- using it
    def _send(self, line):
        with self._lock:
            if self._ser is None:
                return False
            try:
                self._ser.write((line + "\n").encode("ascii"))
                return True
            except (serial.SerialException, OSError):
                return False

    def link(self, robot, command):
        return self._send(f"LINK:{robot}:{command}")

    def say(self, robot, phrase):
        return self._send(f"SAY:{robot}:{int(phrase)}")

    def talk(self, utterance):
        return self._send(f"TALK:{int(utterance)}")

    def heard(self, n=20):
        return list(self._heard)[-n:]

    def status(self):
        return {"connected": self.connected, "port": self.port, "heard": self.heard(10)}
