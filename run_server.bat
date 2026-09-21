@echo off
set BIN=%~dp0PC App\App\bin\network-discovery.exe
if not exist "%BIN%" (
    echo Server binary not found, building first...
    call "%~dp0build.bat"
)
"%BIN%" %*
pause
