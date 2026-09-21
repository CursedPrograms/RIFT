#!/bin/bash
# RIFT fleet hub, Rust edition (same protocol/port as app.py - run one or the other).
set -e
command -v cargo >/dev/null || { echo "Rust was not found. Install it from https://rustup.rs/"; exit 1; }
cd "$(dirname "$0")"
exec cargo run --release --manifest-path "PC App/Rust/Cargo.toml" -- "$@"
