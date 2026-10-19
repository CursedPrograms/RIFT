@echo off
REM Builds RIFT's Unity hub app (Unity App/RIFT) without opening the editor.
REM   build_unity.bat            Windows (Unity App\RIFT\Builds\Windows\RIFT.exe)
REM   build_unity.bat Android    Android (Builds\Android\RIFT.apk; needs Android Build Support)
REM   build_unity.bat Linux      Linux   (Builds\Linux\RIFT.x86_64; needs Linux Build Support)
REM The project is Unity 6000.6.2f1: set UNITY to another Unity.exe if yours is elsewhere.
setlocal
set TARGET=%1
if "%TARGET%"=="" set TARGET=Windows
if "%UNITY%"=="" set UNITY=C:\Program Files\Unity\Hub\Editor\6000.6.2f1\Editor\Unity.exe
if not exist "%UNITY%" (
  echo Unity not found at "%UNITY%". Install 6000.6.2f1 with Unity Hub, or set UNITY=path\to\Unity.exe
  exit /b 1
)
echo Building RIFT for %TARGET% ... (the log: Unity App\RIFT\Builds\build_%TARGET%.log)
if not exist "%~dp0Unity App\RIFT\Builds" mkdir "%~dp0Unity App\RIFT\Builds"
"%UNITY%" -batchmode -quit -projectPath "%~dp0Unity App\RIFT" -executeMethod BuildRift.%TARGET% -logFile "%~dp0Unity App\RIFT\Builds\build_%TARGET%.log"
if errorlevel 1 (
  echo Build failed: see the log above.
  exit /b 1
)
echo Done: Unity App\RIFT\Builds\%TARGET%
