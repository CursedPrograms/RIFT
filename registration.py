import pygame
import requests
import socket
from concurrent.futures import ThreadPoolExecutor

pygame.init()

WIDTH, HEIGHT = 800, 600
screen = pygame.display.set_mode((WIDTH, HEIGHT))
pygame.display.set_caption("KINET Scanner")

font = pygame.font.SysFont("Arial", 20)

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
            data = r.json()
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
    screen.fill((20, 20, 30))

    for event in pygame.event.get():
        if event.type == pygame.QUIT:
            running = False

        if event.type == pygame.KEYDOWN:
            if event.key == pygame.K_s:
                scan_network()

    # Title
    title = font.render("KINET Robot Scanner (Press S to scan)", True, (255, 255, 255))
    screen.blit(title, (20, 20))

    # Status
    status_text = "Scanning..." if scanning else "Idle"
    status = font.render(f"Status: {status_text}", True, (200, 200, 200))
    screen.blit(status, (20, 60))

    # Robot list
    y = 100
    for ip, r in robots:
        text = f"{r['name']} ({r['type']}) @ {ip}"
        label = font.render(text, True, (100, 255, 100))
        screen.blit(label, (20, y))
        y += 30

        # Capabilities
        caps = ", ".join(r.get("capabilities", []))
        cap_label = font.render(f"  -> {caps}", True, (180, 180, 180))
        screen.blit(cap_label, (40, y))
        y += 25

    pygame.display.flip()

pygame.quit()
