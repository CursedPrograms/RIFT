@echo off
where dotnet >nul 2>nul
if not %errorlevel%==0 (
    echo The .NET 8 SDK was not found. Install it from https://dotnet.microsoft.com/download
    pause
    exit /b 1
)
cd /d "%~dp0"
dotnet run --project "PC App\FSharp" -c Release -- %*
pause
