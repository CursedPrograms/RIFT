#!/bin/bash
# Builds RIFT's Unity hub app (Unity App/RIFT) without opening the editor.
#   ./build_unity.sh            Linux   (Unity App/RIFT/Builds/Linux/RIFT.x86_64)
#   ./build_unity.sh Windows    Windows (Builds/Windows/RIFT.exe; needs Windows Build Support)
#   ./build_unity.sh Android    Android (Builds/Android/RIFT.apk; needs Android Build Support)
# The project is Unity 6000.6.2f1: set UNITY to another Unity binary if yours is elsewhere.
cd "$(dirname "$(readlink -f "$0")")" || exit 1
TARGET="${1:-Linux}"
UNITY="${UNITY:-$HOME/Unity/Hub/Editor/6000.6.2f1/Editor/Unity}"
if [ ! -x "$UNITY" ]; then
  echo "Unity not found at $UNITY. Install 6000.6.2f1 with Unity Hub, or: UNITY=/path/to/Unity ./build_unity.sh"
  exit 1
fi
mkdir -p "Unity App/RIFT/Builds"
LOG="Unity App/RIFT/Builds/build_$TARGET.log"
echo "Building RIFT for $TARGET ... (the log: $LOG)"
"$UNITY" -batchmode -quit -projectPath "Unity App/RIFT" -executeMethod "BuildRift.$TARGET" -logFile "$LOG" \
  && echo "Done: Unity App/RIFT/Builds/$TARGET" || { echo "Build failed: see $LOG"; exit 1; }
