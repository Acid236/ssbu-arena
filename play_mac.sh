#!/usr/bin/env bash
# Starts the native macOS build (BUILDING_MAC.md). Run it from anywhere:
#
#   ./play_mac.sh                          play; saves in ~/Library/Application Support/ssbu-recomp/userdata
#   ./play_mac.sh --userdata <folder>      another save folder
#   ./play_mac.sh --help                   every option (they are scripts/run.py's)
#
# The game's log is written to build-macos/logs/game_<time>.log (the last 10 are kept): attach the newest one to a report,
# or run scripts/macos/collect_logs_mac.sh. If MoltenVK crashes at start, try:  MVK_CONFIG_USE_METAL_ARGUMENT_BUFFERS=0 ./play_mac.sh
# (any MVK_* variable you export is passed on to the game).
set -uo pipefail

SRC="${BASH_SOURCE[0]}"
while [ -L "$SRC" ]; do                       # follow symlinks (macOS has no readlink -f in old versions)
    DIR="$(cd "$(dirname "$SRC")" && pwd)"
    SRC="$(readlink "$SRC")"
    case "$SRC" in /*) ;; *) SRC="$DIR/$SRC" ;; esac
done
REPO="$(cd "$(dirname "$SRC")" && pwd)"
PY="$REPO/deps/venv/bin/python"

[ -x "$PY" ] || { echo "deps/venv is missing: run scripts/macos/install_mac.sh first" >&2; exit 1; }
[ -x "$REPO/build-macos/work/ssbu_native" ] || {
    echo "no macOS build yet: run" >&2
    echo "  scripts/macos/install_mac.sh --dump <your dump folder>" >&2
    exit 1; }

# Homebrew's Vulkan loader finds MoltenVK (the Vulkan driver on top of Metal) through its driver file: name it explicitly,
# unless you set your own.
if [ -z "${VK_DRIVER_FILES:-}" ] && [ -z "${VK_ICD_FILENAMES:-}" ]; then
    for p in /opt/homebrew/etc/vulkan/icd.d/MoltenVK_icd.json /opt/homebrew/share/vulkan/icd.d/MoltenVK_icd.json \
             /usr/local/etc/vulkan/icd.d/MoltenVK_icd.json /usr/local/share/vulkan/icd.d/MoltenVK_icd.json; do
        if [ -f "$p" ]; then export VK_DRIVER_FILES="$p"; break; fi
    done
fi

# macOS gives a Terminal 256 open files by default; the game with its libraries, shader cache and Vulkan driver can need more
ulimit -n 4096 2>/dev/null || true

exec "$PY" "$REPO/scripts/run.py" --mac --play "$@"
