#!/usr/bin/env bash
# Collects what is needed to find out why the Linux build or the game failed, into ~/ssbu_linux_report_<date>.zip
# (.tar.gz when zip is not installed).
# Included: the build logs, the build state, the last 3 game logs, and facts about your PC (distribution, kernel, CPU,
# memory, graphics card and driver, Vulkan, OpenGL, library versions, the version of this project).
# NEVER included: your dump, the game files, keys, build-linux/binaries, build-linux/work.
#
#   scripts/linux/collect_logs_linux.sh
set -uo pipefail

REPO="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
BUILD="$REPO/build-linux"
STAMP="$(date +%Y%m%d_%H%M%S)"
NAME="ssbu_linux_report_$STAMP"
TMP="$(mktemp -d "${TMPDIR:-/tmp}/ssbu_report.XXXXXX")"
trap 'rm -rf "$TMP"' EXIT
R="$TMP/report"
mkdir -p "$R/logs" "$R/system"

# the build and game logs (text files written by scripts/setup.py and scripts/run.py)
if [ -d "$BUILD/logs" ]; then
    for f in "$BUILD"/logs/*.log; do
        [ -f "$f" ] && case "$(basename "$f")" in game_*) ;; *) cp "$f" "$R/logs/" ;; esac
    done
    ls -1 "$BUILD"/logs/game_*.log 2>/dev/null | sort | tail -n 3 | while read -r f; do cp "$f" "$R/logs/"; done
fi
[ -f "$BUILD/state.json" ] && cp "$BUILD/state.json" "$R/state.json"
# what ./play.sh keeps of the last start, and the freeze watchdog's report (when no frame was shown for 5 s)
SHARE="${XDG_DATA_HOME:-$HOME/.local/share}/ssbu-recomp"
[ -f "$SHARE/last_run.log" ] && cp "$SHARE/last_run.log" "$R/logs/last_run.log"
[ -f "$BUILD/work/ssbu_native_freeze.txt" ] && cp "$BUILD/work/ssbu_native_freeze.txt" "$R/logs/"

# facts about the PC
{
    echo "== /etc/os-release";  cat /etc/os-release
    echo; echo "== uname -a";   uname -a
    echo; echo "== session";    echo "XDG_SESSION_TYPE=${XDG_SESSION_TYPE:-} WAYLAND_DISPLAY=${WAYLAND_DISPLAY:-} DISPLAY=${DISPLAY:-} XDG_CURRENT_DESKTOP=${XDG_CURRENT_DESKTOP:-}"
    echo; echo "== CPU";        grep -m1 'model name' /proc/cpuinfo; nproc
    echo; echo "== memory";     free -h
    echo; echo "== disk (repo)"; df -h "$REPO"
} > "$R/system/pc.txt" 2>&1
{
    echo "== lspci (graphics)"; command -v lspci >/dev/null && lspci -k | grep -A3 -Ei 'vga|3d|display'
    echo; echo "== glxinfo -B"; command -v glxinfo >/dev/null && glxinfo -B || echo "glxinfo not installed (mesa-utils / mesa-demos)"
} > "$R/system/graphics.txt" 2>&1
if command -v vulkaninfo >/dev/null 2>&1; then
    vulkaninfo --summary > "$R/system/vulkaninfo.txt" 2>&1
else
    echo "vulkaninfo is not installed (vulkan-tools)" > "$R/system/vulkaninfo.txt"
fi
{
    echo "== clang"; clang --version 2>&1 | head -1
    echo; echo "== pkg-config"
    for p in sdl3 freetype2 openssl libavformat libavcodec libswscale libswresample libavutil vulkan opus; do
        printf '%-14s %s\n' "$p" "$(pkg-config --modversion "$p" 2>/dev/null || echo '-')"
    done
    echo; echo "== python"; "$REPO/deps/venv/bin/python" --version 2>&1 || python3 --version
} > "$R/system/versions.txt" 2>&1
git -C "$REPO" log -1 --oneline > "$R/system/project_version.txt" 2>&1

if command -v zip >/dev/null 2>&1; then
    OUT="$HOME/$NAME.zip"
    (cd "$TMP" && zip -q -r "$OUT" report) || { echo "could not make the zip" >&2; exit 1; }
else
    OUT="$HOME/$NAME.tar.gz"
    tar -czf "$OUT" -C "$TMP" report || { echo "could not make the archive" >&2; exit 1; }
fi
echo
echo "Report written: $OUT"
echo "It holds logs and facts about your PC only: no game files. Please send it with your report."
