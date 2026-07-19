#!/bin/bash
set -e

echo "🔧 Building RIFT C++ apps (network-discovery, registration)..."

REQUIRED_PKGS=(build-essential pkg-config libcurl4-openssl-dev libavahi-client-dev nlohmann-json3-dev)
MISSING=()
for pkg in "${REQUIRED_PKGS[@]}"; do
    if ! dpkg -s "$pkg" >/dev/null 2>&1; then
        MISSING+=("$pkg")
    fi
done

if [ ${#MISSING[@]} -ne 0 ]; then
    echo "📦 Missing dependencies: ${MISSING[*]}"
    echo "   Installing via apt (you may be asked for your password)..."
    sudo apt-get update
    sudo apt-get install -y "${MISSING[@]}"
fi

cd "$(dirname "$0")/PC App/App"
make

echo "✅ Build complete! Binaries in 'PC App/App/bin/'"
