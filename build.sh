#!/bin/bash
set -e

echo "🔧 Building RIFT C++ apps (network-discovery, registration)..."

# The C++ hub needs only a compiler: mDNS and HTTP are built in, so there are
# no Avahi/curl/nlohmann packages to install any more.
if ! command -v g++ >/dev/null 2>&1 || ! command -v make >/dev/null 2>&1; then
    echo "📦 g++ / make not found. Installing build-essential via apt (you may be asked for your password)..."
    sudo apt-get update
    sudo apt-get install -y build-essential
fi

cd "$(dirname "$0")/PC App/App"
make

echo "✅ Build complete! Binaries in 'PC App/App/bin/'"
