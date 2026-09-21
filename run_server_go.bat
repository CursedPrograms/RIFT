@echo off
where go >nul 2>nul
if not %errorlevel%==0 (
    echo Go was not found. Install it from https://go.dev/dl/
    pause
    exit /b 1
)
cd /d "%~dp0PC App\Go"
go run . %*
pause
