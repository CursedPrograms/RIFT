@echo off
where g++ >nul 2>nul
if not %errorlevel%==0 (
    echo g++ was not found. Install MinGW-w64: winget install BrechtSanders.WinLibs.POSIX.UCRT
    pause
    exit /b 1
)
cd /d "%~dp0PC App\App"
if not exist bin mkdir bin
g++ -std=c++17 -O2 -Wall -Ithird_party -static -o bin\network-discovery.exe network-discovery.cpp -lws2_32 -liphlpapi -lpthread || goto :fail
g++ -std=c++17 -O2 -Wall -Ithird_party -static -o bin\registration.exe registration.cpp -lws2_32 -liphlpapi -lpthread || goto :fail
echo Built PC App\App\bin\network-discovery.exe and registration.exe
pause
exit /b 0
:fail
echo Build failed - see errors above.
pause
exit /b 1
