#!/bin/bash
# RIFT fleet hub, Julia edition (same protocol/port as app.py - run one or the other).
set -e
command -v julia >/dev/null || { echo "Julia was not found. Install it from https://julialang.org/downloads/"; exit 1; }
cd "$(dirname "$0")"
PROJECT="PC App/Julia"
if [ ! -f "$PROJECT/Manifest.toml" ]; then
    echo "First run - installing Julia package dependencies (this can take a few minutes)..."
    julia --project="$PROJECT" -e 'import Pkg; Pkg.instantiate()'
fi
exec julia --project="$PROJECT" "$PROJECT/rift.jl" "$@"
