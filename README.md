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

---

## 📖 Overview

<details>
<summary><b>View Overview</b></summary>

RIFT is the centralized command-and-control backbone of the Cursed Entertainment robotics ecosystem. Built with Python and Flask, it serves as a high-speed telemetry hub that bridges the gap between various hardware platforms—like WHIP, NORA, and KIDA—and the user interface. By utilizing a unified communication protocol, RIFT allows for seamless fleet management and synchronized multi-agent operations.

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
RIFT: localhost:5000
DREAM: localhost:5001
NORA: localhost:5002
KIDA-00: localhost:5003
KIDA-01: localhost:5004
WHIP: localhost:5005
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
### Run main.py for terminal interactivity

```bash
python main.py
```
### Run app.py for flask web server

```bash
python app.py
```

## ⚙️ Compile
### 🐧 Linux
```bash
g++ kinet_scanner.cpp -o kinet_scanner -lcurl
```
### 🪟 Windows (MinGW)
```bash
g++ kinet_scanner.cpp -o kinet_scanner.exe -lcurl
```

</details>

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
 
