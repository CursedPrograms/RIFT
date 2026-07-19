#!/bin/bash
set -e

DIR="$(cd "$(dirname "$0")" && pwd)"
BIN="$DIR/PC App/App/bin/network-discovery"

if [ ! -x "$BIN" ]; then
    echo "⚙️  Server binary not found, building first..."
    "$DIR/build.sh"
fi

echo "🚀 Starting RIFT fleet server on port 5000..."
exec "$BIN"
