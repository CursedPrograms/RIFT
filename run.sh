#!/bin/bash
# run.sh - RIFT on Linux (Kubuntu, Raspberry Pi OS): sets up ./venv the first time (and again
# whenever requirements.txt changes), then starts RIFT. hub/rift.service runs this at boot.
#   RIFT_NORA_HUB=1 ./run.sh     the old setup: NORA hosts the network, RIFT announces to her
set -e
cd "$(dirname "$0")"
VENV_DIR="venv"
PY="${PYTHON:-python3}"

if [ ! -x "$VENV_DIR/bin/python" ]; then
    echo "Creating $VENV_DIR ..."
    "$PY" -m venv "$VENV_DIR"
fi
if ! cmp -s requirements.txt "$VENV_DIR/requirements.installed"; then
    echo "Installing requirements ..."
    "$VENV_DIR/bin/python" -m pip install --upgrade pip
    "$VENV_DIR/bin/python" -m pip install -r requirements.txt
    cp requirements.txt "$VENV_DIR/requirements.installed"
fi

exec "$VENV_DIR/bin/python" app.py
