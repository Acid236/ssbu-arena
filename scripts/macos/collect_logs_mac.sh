#!/usr/bin/env bash
# Collects what is needed to find out why the macOS build or the game failed, into ~/Desktop/ssbu_mac_report_<date>.zip.
# Included: the build logs, the build state, the last 3 game logs, and facts about your Mac (macOS version, chip, memory,
# graphics, Vulkan, Homebrew packages, the version of this project).
# NEVER included: your dump, the game files, keys, build-macos/binaries, build-macos/work.
#
#   scripts/macos/collect_logs_mac.sh
set -uo pipefail

REPO="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
BUILD="$REPO/build-macos"
STAMP="$(date +%Y%m%d_%H%M%S)"
OUT="$HOME/Desktop/ssbu_mac_report_$STAMP.zip"
TMP="$(mktemp -d "${TMPDIR:-/tmp}/ssbu_report.XXXXXX")"
trap 'rm -rf "$TMP"' EXIT
R="$TMP/report"
mkdir -p "$R/logs" "$R/system" "$HOME/Desktop"

# the build and game logs (text files written by scripts/setup.py and scripts/run.py)
if [ -d "$BUILD/logs" ]; then
    for f in "$BUILD"/logs/*.log; do
        [ -f "$f" ] && case "$(basename "$f")" in game_*) ;; *) cp "$f" "$R/logs/" ;; esac
    done
    # the last 3 game logs (names sort by time)
    ls -1 "$BUILD"/logs/game_*.log 2>/dev/null | sort | tail -n 3 | while read -r f; do cp "$f" "$R/logs/"; done
fi
[ -f "$BUILD/state.json" ] && cp "$BUILD/state.json" "$R/state.json"

# facts about the Mac
{
    echo "== sw_vers";                    sw_vers
    echo; echo "== uname -a";             uname -a
    echo; echo "== cpu, memory (bytes)";  sysctl -n machdep.cpu.brand_string hw.memsize
} > "$R/system/mac.txt" 2>&1
system_profiler SPDisplaysDataType > "$R/system/graphics.txt" 2>&1
if command -v vulkaninfo >/dev/null 2>&1; then
    if ! vulkaninfo --summary > "$R/system/vulkaninfo.txt" 2>&1; then
        { echo; echo "== again with MVK_CONFIG_USE_METAL_ARGUMENT_BUFFERS=0"; } >> "$R/system/vulkaninfo.txt"
        MVK_CONFIG_USE_METAL_ARGUMENT_BUFFERS=0 vulkaninfo --summary >> "$R/system/vulkaninfo.txt" 2>&1
    fi
else
    echo "vulkaninfo is not installed (brew install vulkan-tools)" > "$R/system/vulkaninfo.txt"
fi
if command -v brew >/dev/null 2>&1; then
    brew list --versions > "$R/system/brew_versions.txt" 2>&1
fi
git -C "$REPO" log -1 --oneline > "$R/system/project_version.txt" 2>&1

rm -f "$OUT"
(cd "$TMP" && zip -q -r "$OUT" report) || { echo "could not make the zip (is 'zip' available?)" >&2; exit 1; }
echo
echo "Report written: $OUT"
echo "It holds logs and facts about your Mac only: no game files. Please send it with your report."
