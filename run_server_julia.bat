@echo off
where julia >nul 2>nul
if not %errorlevel%==0 (
    echo Julia was not found. Install it from https://julialang.org/downloads/
    pause
    exit /b 1
)
cd /d "%~dp0"
set PROJECT=PC App\Julia
if not exist "%PROJECT%\Manifest.toml" (
    echo First run - installing Julia package dependencies ^(this can take a few minutes^)...
    julia --project="%PROJECT%" -e "import Pkg; Pkg.instantiate()"
)
julia --project="%PROJECT%" "%PROJECT%\rift.jl" %*
pause
