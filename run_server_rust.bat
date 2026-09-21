@echo off
where cargo >nul 2>nul
if not %errorlevel%==0 (
    echo Rust was not found. Install it from https://rustup.rs/
    pause
    exit /b 1
)
cd /d "%~dp0"
cargo run --release --manifest-path "PC App\Rust\Cargo.toml" -- %*
pause
