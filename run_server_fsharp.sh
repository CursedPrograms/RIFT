#!/bin/bash
# RIFT fleet hub, F# (.NET 8) edition (same protocol/port as app.py - run one or the other).
set -e
command -v dotnet >/dev/null || { echo "The .NET 8 SDK was not found. Install it from https://dotnet.microsoft.com/download"; exit 1; }
cd "$(dirname "$0")"
exec dotnet run --project "PC App/FSharp" -c Release -- "$@"
