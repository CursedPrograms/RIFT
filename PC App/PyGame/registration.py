import os
import pygame
import requests
import socket
from concurrent.futures import ThreadPoolExecutor

import colour_scheme

pygame.init()

WIDTH, HEIGHT = 800, 600
screen = pygame.display.set_mode((WIDTH, HEIGHT))
pygame.display.set_caption("KINET Scanner")
try:  # window icon: the robot's avatar
    pygame.display.set_icon(pygame.image.load(os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "..", "images", "rift-icon.png")))
except (pygame.error, OSError):
    pass

font = pygame.font.SysFont("Arial", 20)

# Colours from colour_scheme.xml (repo root), same as the fleet dashboard.
_c = colour_scheme.load()
BG = colour_scheme.rgb(_c["background"])
TITLE = colour_scheme.rgb(_c["accent"])
TEXT_SEC = colour_scheme.rgb(_c["text_sec"])
ROBOT = colour_scheme.rgb(_c["text"])
CAPS = colour_scheme.rgb(_c["text_dim"])

robots = []
scanning = False


# 🔍 Get local IP range
def get_local_ip_range():
    hostname = socket.gethostname()
    local_ip = socket.gethostbyname(hostname)
    base = ".".join(local_ip.split(".")[:-1])
    return base


# 🔍 Scan a single IP for NORA hub
def scan_ip(ip):
    try:
        url = f"http://{ip}:5000/robots"
        r = requests.get(url, timeout=0.5)
        if r.status_code == 200:
            # RIFT and NORA both serve {"authority": "...", "robots": [...]},
            # not a bare array.
            data = r.json().get("robots", [])
            return (ip, data)
    except:
        return None


# 🔍 Full network scan
def scan_network():
    global robots, scanning
    scanning = True
    robots = []

    base = get_local_ip_range()

    with ThreadPoolExecutor(max_workers=50) as executor:
        futures = []
        for i in range(1, 255):
            ip = f"{base}.{i}"
            futures.append(executor.submit(scan_ip, ip))

        for f in futures:
            result = f.result()
            if result:
                ip, data = result
                for r in data:
                    robots.append((ip, r))

    scanning = False


# 🎮 Main loop
running = True

while running:
    screen.fill(BG)

    for event in pygame.event.get():
        if event.type == pygame.QUIT:
            running = False

        if event.type == pygame.KEYDOWN:
            if event.key == pygame.K_s:
                scan_network()

    # Title
    title = font.render("KINET Robot Scanner (Press S to scan)", True, TITLE)
    screen.blit(title, (20, 20))

    # Status
    status_text = "Scanning..." if scanning else "Idle"
    status = font.render(f"Status: {status_text}", True, TEXT_SEC)
    screen.blit(status, (20, 60))

    # Robot list
    y = 100
    for ip, r in robots:
        text = f"{r['name']} ({r['type']}) @ {ip}"
        label = font.render(text, True, ROBOT)
        screen.blit(label, (20, y))
        y += 30

        # Capabilities
        caps = ", ".join(r.get("capabilities", []))
        cap_label = font.render(f"  -> {caps}", True, CAPS)
        screen.blit(cap_label, (40, y))
        y += 25

    pygame.display.flip()

pygame.quit()
