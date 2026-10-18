#!/bin/bash
# setup_hub.sh - make this Linux machine the fleet hub (Kubuntu, Raspberry Pi OS Bookworm on a Pi 3:
# anything with NetworkManager).
#
#   The Ethernet port to the "RIFT" router becomes 192.168.4.1/24 and NetworkManager's "shared"
#   mode hands out addresses (DHCP) and shares internet from whatever uplink there is (a WiFi
#   dongle, another port). With no uplink it still works: the robots get addresses, nothing more.
#   RIFT then runs at 192.168.4.1:5000, the address every robot registers with.
#
#   ./setup_hub.sh               look, say what it would do, ask, then do it
#   ./setup_hub.sh --dry-run     only say what it would do
#   ./setup_hub.sh --yes         don't ask
#   ./setup_hub.sh --iface eth0  this Ethernet port (default: the first one NetworkManager knows)
#   ./setup_hub.sh --service     also install hub/rift.service: RIFT starts at boot
#   ./setup_hub.sh --undo        take it all back
#
# Safe to run again: it changes only what isn't set up yet. The router: Mercusys MW302R in Access
# Point mode, WiFi "RIFT" (WPA2), this machine's Ethernet in its WAN port; in AP mode it has no DHCP
# and no address of its own (this machine hands out the addresses). A WiFi uplink stays on your
# HOME WiFi, never on "RIFT". See RIFT's README ("The fleet network") and the fleet TODO, section 2.
set -euo pipefail

CON="rift-hub"
ADDR="192.168.4.1/24"
PORT=5000
HERE="$(cd "$(dirname "$0")" && pwd)"
RIFT_DIR="$(dirname "$HERE")"
DRY=0 YES=0 SERVICE=0 UNDO=0 IFACE=""

while [ $# -gt 0 ]; do
    case "$1" in
        --dry-run) DRY=1 ;;
        --yes|-y) YES=1 ;;
        --service) SERVICE=1 ;;
        --undo) UNDO=1 ;;
        --iface) IFACE="${2:-}"; shift ;;
        -h|--help) sed -n '2,21p' "$0"; exit 0 ;;
        *) echo "Unknown option: $1 (see --help)"; exit 2 ;;
    esac
    shift
done

say() { echo "[hub] $*"; }
run() {                       # print it; do it unless this is a dry run
    echo "  \$ $*"
    if [ "$DRY" -eq 0 ]; then "$@"; fi
}
SUDO=""
if [ "$(id -u)" -ne 0 ]; then SUDO="sudo"; fi
asroot() { run $SUDO "$@"; }

if ! command -v nmcli >/dev/null 2>&1; then
    say "NetworkManager (nmcli) isn't here. Raspberry Pi OS Bookworm and Kubuntu have it;"
    say "on older Raspberry Pi OS: sudo raspi-config > Advanced Options > Network Config > NetworkManager."
    exit 1
fi

ufw_active() { command -v ufw >/dev/null 2>&1 && $SUDO ufw status 2>/dev/null | grep -q "Status: active"; }

# ---------------------------------------------------------------- undo
if [ "$UNDO" -eq 1 ]; then
    say "Undoing the hub setup."
    if nmcli -t -f NAME con show | grep -qx "$CON"; then asroot nmcli con delete "$CON"; else say "no '$CON' connection"; fi
    if ufw_active; then
        asroot ufw delete allow "$PORT/tcp" || true
    fi
    if [ -f /etc/systemd/system/rift.service ]; then
        asroot systemctl disable --now rift.service
        asroot rm /etc/systemd/system/rift.service
        asroot systemctl daemon-reload
    fi
    say "Done. The Ethernet port goes back to its normal connection (DHCP client)."
    exit 0
fi

# ---------------------------------------------------------------- look
if [ -z "$IFACE" ]; then
    IFACE="$(nmcli -t -f DEVICE,TYPE device status | awk -F: '$2=="ethernet"{print $1; exit}')"
fi
if [ -z "$IFACE" ]; then
    say "No Ethernet port found (nmcli device status). Plug the router in, or name it: --iface eth0"
    exit 1
fi
UPLINK="$(nmcli -t -f DEVICE,TYPE,STATE device status | awk -F: -v e="$IFACE" '$1!=e && $3=="connected" && ($2=="wifi" || $2=="ethernet") {print $1" ("$2")"; exit}')"

say "Ethernet port to the router: $IFACE -> $ADDR, sharing (DHCP + NAT) via NetworkManager"
say "Internet uplink: ${UPLINK:-none right now (fine: the robots still get addresses)}"
if nmcli -t -f ACTIVE,SSID dev wifi 2>/dev/null | grep -qx "yes:RIFT"; then
    say "WARNING: a WiFi adapter is joined to 'RIFT'. The uplink must stay on your HOME WiFi: this machine"
    say "         is on RIFT through the Ethernet cable. Join it to your home WiFi, then run this again."
fi
EXISTS=0
if nmcli -t -f NAME con show | grep -qx "$CON"; then
    EXISTS=1
    CUR="$(nmcli -g ipv4.method,ipv4.addresses,connection.interface-name con show "$CON" | tr '\n' ' ')"
    say "'$CON' already exists: $CUR"
fi
if ufw_active; then say "ufw is active: :$PORT/tcp, DHCP and DNS on $IFACE will be allowed"; fi
if [ "$SERVICE" -eq 1 ]; then say "RIFT will start at boot: /etc/systemd/system/rift.service (runs $RIFT_DIR/run.sh as $(id -un))"; fi

if [ "$DRY" -eq 1 ]; then say "Dry run: the commands it would run:"; fi
if [ "$DRY" -eq 0 ] && [ "$YES" -eq 0 ]; then
    read -r -p "[hub] Go ahead? [y/N] " ans
    case "$ans" in y|Y|yes|YES) ;; *) say "Nothing changed."; exit 0 ;; esac
fi

# ---------------------------------------------------------------- do
if [ "$EXISTS" -eq 1 ]; then
    asroot nmcli con modify "$CON" connection.interface-name "$IFACE" ipv4.method shared \
        ipv4.addresses "$ADDR" ipv6.method disabled connection.autoconnect yes connection.autoconnect-priority 100
else
    asroot nmcli con add type ethernet ifname "$IFACE" con-name "$CON" ipv4.method shared \
        ipv4.addresses "$ADDR" ipv6.method disabled connection.autoconnect yes connection.autoconnect-priority 100
fi
asroot nmcli con up "$CON"

if ufw_active; then
    asroot ufw allow "$PORT/tcp"
    asroot ufw allow in on "$IFACE" to any port 67 proto udp     # DHCP for the robots
    asroot ufw allow in on "$IFACE" to any port 53               # DNS (NetworkManager's dnsmasq)
fi

if [ "$SERVICE" -eq 1 ]; then
    UNIT="$(sed -e "s#@RIFT_DIR@#$RIFT_DIR#g" -e "s#@USER@#$(id -un)#g" "$HERE/rift.service")"
    echo "  \$ (write /etc/systemd/system/rift.service)"
    if [ "$DRY" -eq 0 ]; then echo "$UNIT" | $SUDO tee /etc/systemd/system/rift.service >/dev/null; fi
    run chmod +x "$RIFT_DIR/run.sh"
    asroot systemctl daemon-reload
    asroot systemctl enable --now rift.service
fi

if [ "$DRY" -eq 1 ]; then say "Dry run: nothing changed."; exit 0; fi
say "Done. This machine is 192.168.4.1 on $IFACE; RIFT runs at http://192.168.4.1:$PORT/"
say "Undo: $0 --undo   (or: sudo nmcli con delete $CON$(ufw_active && echo "; sudo ufw delete allow $PORT/tcp"))"
