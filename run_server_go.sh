#!/bin/bash
# RIFT fleet hub, Go edition (same protocol/port as app.py - run one or the other).
set -e
command -v go >/dev/null || { echo "Go was not found. Install it from https://go.dev/dl/"; exit 1; }
cd "$(dirname "$0")/PC App/Go"
exec go run . "$@"
