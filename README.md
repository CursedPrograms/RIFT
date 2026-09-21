[![Twitter: @NorowaretaGemu](https://img.shields.io/badge/X-@NorowaretaGemu-blue.svg?style=flat)](https://x.com/NorowaretaGemu)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](https://opensource.org/licenses/MIT)

<div align="center">
  <a href="https://ko-fi.com/cursedentertainment">
    <img src="https://ko-fi.com/img/githubbutton_sm.svg" alt="ko-fi" style="width: 20%;"/>
  </a>
</div>

<div align="center">
  <img alt="Python" src="https://img.shields.io/badge/python%20-%23323330.svg?&style=for-the-badge&logo=python&logoColor=white"/>
  <img alt="C++" src="https://img.shields.io/badge/c++%20-%23323330.svg?&style=for-the-badge&logo=c%2B%2B&logoColor=white"/>
  <img alt="C#" src="https://img.shields.io/badge/c%23%20-%23323330.svg?&style=for-the-badge&logo=c-sharp&logoColor=white"/>
  <img alt="Kotlin" src="https://img.shields.io/badge/kotlin-%23323330.svg?&style=for-the-badge&logo=kotlin&logoColor=white"/>
  <img alt="F#" src="https://img.shields.io/badge/f%23-%23323330.svg?&style=for-the-badge&logo=fsharp&logoColor=white"/>
  <img alt="Go" src="https://img.shields.io/badge/go-%23323330.svg?&style=for-the-badge&logo=go&logoColor=white"/>
  <img alt="Rust" src="https://img.shields.io/badge/rust-%23323330.svg?&style=for-the-badge&logo=rust&logoColor=white"/>
  <img alt="Julia" src="https://img.shields.io/badge/julia-%23323330.svg?&style=for-the-badge&logo=julia&logoColor=white"/>
</div>

<div align="center">
  <img alt="Arduino" src="https://img.shields.io/badge/-Arduino-323330?style=for-the-badge&logo=arduino&logoColor=white"/>
  <img alt="ESP32" src="https://img.shields.io/badge/ESP32-%23323330.svg?&style=for-the-badge&logo=espressif&logoColor=white"/>
  <img alt="Raspberry Pi" src="https://img.shields.io/badge/-Raspberry_Pi-323330?style=for-the-badge&logo=raspberry-pi&logoColor=white"/>
  <img alt="Android Studio" src="https://img.shields.io/badge/android%20studio-%23323330.svg?&style=for-the-badge&logo=android-studio&logoColor=white"/>
  <img alt="Unity" src="https://img.shields.io/badge/unity-%23323330.svg?&style=for-the-badge&logo=unity&logoColor=white"/>
</div>

<div align="center">
  <img alt="Git" src="https://img.shields.io/badge/git%20-%23323330.svg?&style=for-the-badge&logo=git&logoColor=white"/>
  <img alt="PowerShell" src="https://img.shields.io/badge/PowerShell-%23323330.svg?&style=for-the-badge&logo=powershell&logoColor=white"/>
  <img alt="Shell" src="https://img.shields.io/badge/Shell-%23323330.svg?&style=for-the-badge&logo=gnu-bash&logoColor=white"/>
  <img alt="Batch" src="https://img.shields.io/badge/Batch-%23323330.svg?&style=for-the-badge&logo=windows&logoColor=white"/>
</div>

---

# RIFT: Real-time Intelligent Fleet Technology

## Related Projects

- [WHIP-Robot-v00](https://github.com/CursedPrograms/WHIP-Robot-v00)
- [KIDA-Robot-v00](https://github.com/CursedPrograms/KIDA-Robot-v00)
- [KIDA-Robot-v01](https://github.com/CursedPrograms/KIDA-Robot-v01)
- [NORA-Robot-v00](https://github.com/CursedPrograms/NORA-Robot-v00)
- [DREAM/ComCentre](https://github.com/CursedPrograms/DREAM)
- [ARM-Robot-v01](https://github.com/CursedPrograms/ARM-Robot-v01)

---

## 📖 Overview

<details>
<summary><b>View Overview</b></summary>

RIFT is the centralized command-and-control backbone of the DREAM robotics ecosystem. Built with Python and Flask, it serves as a high-speed telemetry hub that bridges the gap between various hardware platforms—like WHIP, NORA, and KIDA—and the user interface. By utilizing a unified communication protocol, RIFT allows for seamless fleet management and synchronized multi-agent operations.

Core Features
- [x] Fleet Dashboard: Real-time monitoring and control of multiple robots from a single interface.
- [x] Protocol Bridging: Seamlessly translates commands between PC, Android, and diverse microcontroller platforms.
- [x] Autoconnect Hub: Logic-based routing for local and remote instances (localhost:5000 through 5006).
- [x] Telemetry Visualization: Live data streaming from IMU (MPU6050) and Ultrasonic sensors across the fleet.

#### ESP32/Wi-Fi Network Communications:
This system uses [NORA-Robot-v00](https://github.com/CursedPrograms/NORA-Robot-v00)
 as a central hub, while human devices like phones and PCs act as control interfaces. [Friday](https://github.com/CursedPrograms/ComCentre) can also assist with verbal communication between users and robots.

#### Supported Development & Runtime Environments
- Microcontrollers: ESP32, Arduino IDE
- PC & Mobile Apps: Android Studio, MinGW (Windows/Linux)
- Operating Systems: Raspberry Pi OS, Ubuntu, Windows, Android
</details>

```bash
RIFT: :5000
DREAM: :5001
NORA: :5002
KIDA-00: :5003
KIDA-01: :5004
WHIP: :5005
MILA: :5010
ARM: :5011
```

## How to Run:

<details>
<summary><b>View How to Run</b></summary>

### Environment Setup/Install Dependencies

```bash
sudo snap install android-studio --classic
python3 -m venv venv
source venv/bin/activate
pip install --upgrade pip
pip install -r requirements.txt
```
### Run app.py for the Flask fleet dashboard

Runs the fleet registry, mDNS discovery (including browsing for ComCentre),
and the RIFT/NORA integration threads (fleet-authority heartbeat, internet
share) all in one Python process — no compiling required.

```bash
python app.py
```

This is a full alternative to the native fleet server below: both speak the
same `/robots` + `/register` protocol on port 5000, so run one or the other,
not both, on a given machine.

## ⚙️ Compile (native alternative)

### 🐧 Linux (`PC App/App`)

`network-discovery.cpp` is RIFT's native fleet-registry server: it publishes
itself on the LAN via mDNS/Avahi (`_rift._tcp`), browses for other RIFT
instances, and serves the `/robots` + `/register` endpoints that
`registration.cpp`, `PC App/PyGame/registration.py`, and `Fleet/register.py`
all talk to. `registration.cpp` is the subnet-scanning client that queries
`/robots`.

```bash
./build.sh
```

This installs the required apt dev packages (`libcurl4-openssl-dev`,
`libavahi-client-dev`, `nlohmann-json3-dev`, `libcpp-httplib-dev`) if
missing — you'll be asked for your sudo password — then builds both
binaries into `PC App/App/bin/`.

To start the fleet server once built:

```bash
./run_server.sh
```

Or build manually with the Makefile:

```bash
cd "PC App/App"
make
```

### 🪟 Windows (MinGW)
```bash
g++ registration.cpp -o registration.exe -lcurl
```

</details>

## 🧩 Fleet hub in other languages (Windows + Linux)

`app.py` is the reference fleet hub. `PC App/Go`, `PC App/Rust`, `PC App/FSharp` (.NET 8) and `PC App/Julia` are complete, cross-platform re-implementations of it - the same protocol on the same port `5000`, so run **one** hub per machine, whichever language you prefer. Each one has:

- the fleet registry: `POST /register` (form body, or the JSON that `Android App/Registration.kt` sends), `GET /robots` (entries expire after 20 s without a heartbeat), `GET /ping`
- `GET /peers`, plus mDNS publish/browse of `_rift._tcp` and ComCentre's `_flask-link._tcp`, so hubs (and DREAM) find each other
- `GET`/`POST /mode`: the WiFi/Bluetooth connection mode, and the NORA fleet-authority heartbeat that goes with it (HTTP to `192.168.4.1:5000`, or `H<name>:<caps>` over a Bluetooth serial port)
- the same dashboard: `templates/index.html` and `static/` are served as they are, no template engine needed
- the NetworkManager internet share for NORA's AP (Linux only, like `Fleet/internet_share.py`)
- `--scan`, the subnet scanner (what `registration.cpp` / `registration.py` do): finds every hub or robot answering `/robots` on this machine's /24

| Language | Launch | Needs |
| --- | --- | --- |
| Go | `run_server_go.bat` / `./run_server_go.sh` | [Go](https://go.dev/dl/) |
| Rust | `run_server_rust.bat` / `./run_server_rust.sh` | [Rust](https://rustup.rs/) |
| F# | `run_server_fsharp.bat` / `./run_server_fsharp.sh` | [.NET 8 SDK](https://dotnet.microsoft.com/download) |
| Julia | `run_server_julia.bat` / `./run_server_julia.sh` | [Julia](https://julialang.org/downloads/) (installs its packages on first run) |

```bash
./run_server_go.sh                       # start the hub on :5000
./run_server_rust.sh --scan              # scan this subnet for hubs/robots
./run_server_fsharp.sh --name RIFT2 --port 5010 --no-internet-share   # a second hub for testing
```

Options (all four): `--name`, `--port`, `--nora-host`, `--nora-port`, `--heartbeat-secs`, `--ttl-secs`, `--no-heartbeat`, `--no-mdns`, `--no-internet-share`, `--root`, `--scan`. On Linux, Bluetooth mode needs the serial port bound to the NORA pairing (e.g. `sudo rfcomm bind 0 <NORA_MAC>` → `/dev/rfcomm0`), and the internet share needs NetworkManager (`nmcli`); like `app.py`, the hub tries to join NORA's AP whenever it starts unless `--no-internet-share` is given.

All four were checked against the same protocol test suite and against each other and the original `app.py`: each hub lists the others (and `app.py`) as mDNS peers, and every robot heartbeat - including ARM's real controllers - lands in `/robots`.

### Still incomplete

- `PC App/App` (C++): Linux-only (Avahi), and missing `/peers`, `/mode`, the dashboard and the NORA heartbeat.
- `Unity App/`: a placeholder `HttpListener` that only answers "Hello from Unity".
- `Android App/`: `NetworkDiscovery.kt` only serves `/ping` and a static page; `Registration.kt` posts JSON (which all four hubs above accept, but `app.py` and the C++ hub don't).

<br>
<div align="center">
© Cursed Entertainment 2026
</div>
<br>
<div align="center">
<a href="https://cursed-entertainment.itch.io/" target="_blank">
    <img src="https://github.com/CursedPrograms/cursedentertainment/raw/main/images/logos/logo-wide-grey.png"
        alt="CursedEntertainment Logo" style="width:250px;">
</a>
</div>
 
