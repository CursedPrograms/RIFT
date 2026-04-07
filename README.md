[![Twitter: @NorowaretaGemu](https://img.shields.io/badge/X-@NorowaretaGemu-blue.svg?style=flat)](https://x.com/NorowaretaGemu)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](https://opensource.org/licenses/MIT)
  
  <br>
<div align="center">
  <a href="https://ko-fi.com/cursedentertainment">
    <img src="https://ko-fi.com/img/githubbutton_sm.svg" alt="ko-fi" style="width: 20%;"/>
  </a>
</div>
  <br>

<div align="center">
  <img alt="Python" src="https://img.shields.io/badge/python%20-%23323330.svg?&style=for-the-badge&logo=python&logoColor=white"/>
</div>
<div align="center">
    <img alt="Git" src="https://img.shields.io/badge/git%20-%23323330.svg?&style=for-the-badge&logo=git&logoColor=white"/>
  <img alt="PowerShell" src="https://img.shields.io/badge/PowerShell-%23323330.svg?&style=for-the-badge&logo=powershell&logoColor=white"/>
  <img alt="Shell" src="https://img.shields.io/badge/Shell-%23323330.svg?&style=for-the-badge&logo=gnu-bash&logoColor=white"/>
  <img alt="Batch" src="https://img.shields.io/badge/Batch-%23323330.svg?&style=for-the-badge&logo=windows&logoColor=white"/>
  </div>
  <br>

# RIFT: Real-time Intelligent Fleet Technology

## Related Projects

- [WHIP-Robot-v00](https://github.com/CursedPrograms/WHIP-Robot-v00)
- [KIDA-Robot-v00](https://github.com/CursedPrograms/KIDA-Robot-v00)
- [KIDA-Robot-v01](https://github.com/CursedPrograms/KIDA-Robot-v01)
- [NORA-Robot-v00](https://github.com/CursedPrograms/NORA-Robot-v00)
- [Friday/ComCentre](https://github.com/CursedPrograms/ComCentre)

dependencies {
    implementation 'org.nanohttpd:nanohttpd:2.3.1'
}

RIFT: Real-time Intelligent Fleet Technology

- Unified Interface – Control all your robots from a single app.
- Real-time Monitoring – Track robot status, camera feeds, and sensors instantly.
- Fleet Management – Deploy and manage multiple robots effortlessly.
- Cross-Platform – Works on Linux, Windows, Android, and microcontroller platforms without network restrictions.

#### ESP32/Wi-Fi Network Communications:
This system uses [NORA-Robot-v00](https://github.com/CursedPrograms/NORA-Robot-v00)
 as a central hub, while human devices like phones and PCs act as control interfaces. [Friday](https://github.com/CursedPrograms/ComCentre) can also assist with verbal communication between users and robots.

#### Supported Development & Runtime Environments
- Microcontrollers: ESP32, Arduino IDE
- PC & Mobile Apps: Android Studio, MinGW (Windows/Linux)
- Operating Systems: Raspberry Pi OS, Ubuntu, Windows, Android

## How to Run:

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
 
