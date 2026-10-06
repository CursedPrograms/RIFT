#!/usr/bin/env python3
"""camera_node.py - publish a webcam to the RIFT fleet camera wall.

Run this on any machine with a camera (this PC, a laptop, a Pi on a robot).
It serves an MJPEG stream and registers itself with the fleet, so it shows up
live on RIFT's /cameras page without any manual wiring.

    python Fleet/camera_node.py --name CAM-LIVINGROOM --camera 0

Endpoints (on --port, default 8090):
    /stream     multipart MJPEG (what the wall embeds)
    /snapshot   single JPEG
    /           a tiny viewer page

Registration: every few seconds it POSTs to the fleet authority (default
127.0.0.1:5000, i.e. the local RIFT/NORA registry) advertising capability
    camera:http://<this-lan-ip>:<port>/stream
which cameras.js turns straight into the tile's <img> source.

Graceful by design:
  * no OpenCV or no camera  -> streams a moving test pattern, so the wall still
    lights up and you can prove the whole path end to end.
  * no `requests`           -> skips registration; add the source on the wall
    with the gear button instead.
"""

import argparse
import socket
import struct
import threading
import time

try:
    import cv2
    _HAVE_CV2 = True
except Exception:
    _HAVE_CV2 = False

try:
    import requests
    _HAVE_REQUESTS = True
except Exception:
    _HAVE_REQUESTS = False

from flask import Flask, Response

app = Flask(__name__)

_cfg = {}            # filled in main()
_cap = None          # cv2.VideoCapture or None
_cap_lock = threading.Lock()


# ── frame sources ────────────────────────────────────────────────────────────

def _lan_ip():
    """Best-effort LAN IP (not 127.0.0.1), so the tile works from other devices."""
    s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        s.connect(("8.8.8.8", 80))
        return s.getsockname()[0]
    except Exception:
        return "127.0.0.1"
    finally:
        s.close()


def _jpeg_from_camera():
    global _cap
    with _cap_lock:
        if _cap is None:
            _cap = cv2.VideoCapture(_cfg["camera"])
            _cap.set(cv2.CAP_PROP_FRAME_WIDTH, _cfg["width"])
            _cap.set(cv2.CAP_PROP_FRAME_HEIGHT, _cfg["height"])
        ok, frame = _cap.read()
    if not ok:
        return None
    ok, buf = cv2.imencode(".jpg", frame, [int(cv2.IMWRITE_JPEG_QUALITY), 80])
    return buf.tobytes() if ok else None


# A minimal self-contained JPEG test pattern (no deps): a plain colour block
# with a moving bar, encoded by hand so it needs neither OpenCV nor Pillow.
def _test_pattern(w, h, t):
    # Build a tiny baseline JPEG via a crafted PPM->JPEG is overkill; instead we
    # draw into a raw RGB buffer and wrap it as a BMP, which browsers render in
    # <img>. MJPEG parts can be any image type the browser decodes; we use BMP.
    bar = int((t * 60) % w)
    row_pad = (-w * 3) % 4
    rows = bytearray()
    for y in range(h):
        line = bytearray()
        for x in range(w):
            if abs(x - bar) < 6:
                r, g, b = 163, 230, 53          # accent lime bar
            else:
                r = 10 + (x * 40 // w)
                g = 12 + (y * 30 // h)
                b = 16
            line += bytes((b, g, r))            # BMP is BGR
        line += b"\x00" * row_pad
        rows = line + rows                       # BMP rows are bottom-up
    pixel = bytes(rows)
    size = 54 + len(pixel)
    header = b"BM" + struct.pack("<IHHI", size, 0, 0, 54)
    dib = struct.pack("<IiiHHIIiiII", 40, w, h, 1, 24, 0, len(pixel), 2835, 2835, 0, 0)
    return header + dib + pixel


def _next_frame(t):
    if _HAVE_CV2:
        jpg = _jpeg_from_camera()
        if jpg is not None:
            return jpg, "image/jpeg"
    return _test_pattern(_cfg["width"], _cfg["height"], t), "image/bmp"


# ── HTTP ─────────────────────────────────────────────────────────────────────

@app.route("/stream")
def stream():
    def gen():
        t0 = time.time()
        boundary = b"--frame"
        while True:
            data, ctype = _next_frame(time.time() - t0)
            yield (boundary + b"\r\nContent-Type: " + ctype.encode() +
                   b"\r\nContent-Length: " + str(len(data)).encode() +
                   b"\r\n\r\n" + data + b"\r\n")
            time.sleep(1.0 / _cfg["fps"])
    return Response(gen(), mimetype="multipart/x-mixed-replace; boundary=frame")


@app.route("/snapshot")
def snapshot():
    data, ctype = _next_frame(time.time())
    return Response(data, mimetype=ctype)


@app.route("/")
def index():
    src = "live camera" if (_HAVE_CV2) else "test pattern (no OpenCV/camera)"
    return (
        "<!doctype html><meta name=viewport content='width=device-width,initial-scale=1'>"
        "<body style='margin:0;background:#0A0B07;color:#F1F5E6;font-family:sans-serif;text-align:center'>"
        "<p style='padding:10px'>%s &middot; %s</p>"
        "<img src='/stream' style='max-width:100%%;height:auto'>"
        "</body>" % (_cfg["name"], src)
    )


# ── fleet registration ───────────────────────────────────────────────────────

def _register_loop():
    url = "http://%s:%d/register" % (_cfg["authority_host"], _cfg["authority_port"])
    cam = "camera:http://%s:%d/stream" % (_cfg["advertise_ip"], _cfg["port"])
    payload = {"name": _cfg["name"], "type": "camera", "capabilities": cam}
    while True:
        try:
            requests.post(url, data=payload, timeout=2)
        except Exception:
            pass
        time.sleep(_cfg["heartbeat"])


def main():
    ap = argparse.ArgumentParser(description="Publish a webcam to the RIFT fleet camera wall.")
    ap.add_argument("--name", default="CAM-" + socket.gethostname()[:12])
    ap.add_argument("--camera", type=int, default=0, help="OpenCV camera index")
    ap.add_argument("--port", type=int, default=8090, help="port to serve the stream on")
    ap.add_argument("--fps", type=float, default=15.0)
    ap.add_argument("--width", type=int, default=640)
    ap.add_argument("--height", type=int, default=480)
    ap.add_argument("--authority-host", default="127.0.0.1", help="fleet registry host (RIFT/NORA)")
    ap.add_argument("--authority-port", type=int, default=5000)
    ap.add_argument("--heartbeat", type=float, default=8.0)
    ap.add_argument("--advertise-ip", default=None, help="IP to advertise (default: auto-detected LAN IP)")
    ap.add_argument("--no-register", action="store_true", help="serve only; do not register with the fleet")
    args = ap.parse_args()

    _cfg.update(vars(args))
    _cfg["advertise_ip"] = args.advertise_ip or _lan_ip()

    print("camera_node: %s" % _cfg["name"])
    print("  source     : %s" % ("OpenCV camera %d" % args.camera if _HAVE_CV2 else "TEST PATTERN (no OpenCV)"))
    print("  stream     : http://%s:%d/stream" % (_cfg["advertise_ip"], args.port))
    if args.no_register or not _HAVE_REQUESTS:
        why = "disabled" if args.no_register else "no 'requests' module"
        print("  register   : off (%s) - add the source on the wall with the gear button" % why)
    else:
        print("  register   : %s:%d every %.0fs as a 'camera'" % (args.authority_host, args.authority_port, args.heartbeat))
        threading.Thread(target=_register_loop, daemon=True).start()

    app.run(host="0.0.0.0", port=args.port, threaded=True, use_reloader=False)


if __name__ == "__main__":
    main()
