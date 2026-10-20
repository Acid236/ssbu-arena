#!/usr/bin/env bash
# Installs everything the native macOS build needs, and (with --dump) builds the game. See BUILDING_MAC.md.
#
#   scripts/macos/install_mac.sh                       the tools only
#   scripts/macos/install_mac.sh --dump <folder>       the tools, then the build from YOUR dump (hours the first time)
#   scripts/macos/install_mac.sh --dump <folder> --jobs 4
#
# Run the same command again after any stop: finished work is skipped.
# Steps: 1. checks (Apple Silicon, macOS 14.4+, Xcode Command Line Tools, Homebrew, disk)
#        2. Homebrew packages  3. Python venv in deps/venv  4. deps/Vulkan-Headers  5. deps/suyu
#        6. the build (only with --dump)  7. play_mac.sh made executable
# Written for the macOS system bash (3.2): no newer bash features.
set -euo pipefail

REPO="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
DEPS="$REPO/deps"
DUMP=""
JOBS=""
while [ $# -gt 0 ]; do
    case "$1" in
        --dump)   [ $# -ge 2 ] || { echo "--dump needs a folder" >&2; exit 2; }; DUMP="$2"; shift 2 ;;
        --dump=*) DUMP="${1#--dump=}"; shift ;;
        --jobs)   [ $# -ge 2 ] || { echo "--jobs needs a number" >&2; exit 2; }; JOBS="$2"; shift 2 ;;
        --jobs=*) JOBS="${1#--jobs=}"; shift ;;
        -h|--help) sed -n '2,12p' "$0" | sed 's/^# \{0,1\}//'; exit 0 ;;
        *) echo "unknown option $1 (see --help)" >&2; exit 2 ;;
    esac
done

say() { printf '\033[1m==> %s\033[0m\n' "$*"; }
die() { printf '\n%s\n' "$*" >&2; exit 1; }

# ---------------------------------------------------------------------------------------------- 1. checks
say "Checking your Mac"
if [ "$(uname -s)" != "Darwin" ]; then
    die "This script is for macOS. On Linux use scripts/linux/install_deps.sh."
fi
if [ "$(uname -m)" != "arm64" ]; then
    # an Apple Silicon Mac whose Terminal runs as Intel code (Rosetta) also says x86_64 here
    if [ "$(sysctl -n hw.optional.arm64 2>/dev/null)" = "1" ]; then
        die "This Mac has Apple Silicon, but this Terminal runs under Rosetta (as an Intel program), so the build would be made
for Intel. Fix: quit Terminal; in Finder > Applications > Utilities, select Terminal, File > Get Info, untick
'Open using Rosetta'; open Terminal again and run this script again. (Or run: arch -arm64 bash $0 $*)"
    fi
    die "This Mac has an Intel processor ($(uname -m)). Intel Macs are not supported: only Apple Silicon (M1 or newer)."
fi
OSV="$(sw_vers -productVersion)"
OS_MAJOR="${OSV%%.*}"
OS_REST="${OSV#*.}"
OS_MINOR="${OS_REST%%.*}"
[ "$OS_REST" = "$OSV" ] && OS_MINOR=0
if [ "$OS_MAJOR" -lt 14 ] || { [ "$OS_MAJOR" -eq 14 ] && [ "$OS_MINOR" -lt 4 ]; }; then
    die "macOS $OSV is too old. macOS 14.4 or newer is needed (System Settings > General > Software Update)."
fi
echo "  macOS $OSV, Apple Silicon: ok"

if ! xcode-select -p >/dev/null 2>&1; then
    echo "  The Xcode Command Line Tools (the compiler) are not installed."
    echo "  Starting their installer now. A window opens: click Install and wait until it ends."
    xcode-select --install || true
    die "When the installer has finished, run this script again."
fi
echo "  Xcode Command Line Tools: ok"

# Apple Silicon's Homebrew lives in /opt/homebrew. Use it even when the PATH names another brew first: a Homebrew in
# /usr/local is the Intel one (moved over from an Intel Mac, or installed from a Rosetta Terminal) and has Intel libraries.
if [ -x /opt/homebrew/bin/brew ]; then
    eval "$(/opt/homebrew/bin/brew shellenv)"
elif command -v brew >/dev/null 2>&1 && [ "$(brew --prefix 2>/dev/null)" = "/usr/local" ]; then
    echo "  The Homebrew found ($(command -v brew)) is the Intel Homebrew in /usr/local: its libraries are Intel code."
    echo "  Install the Apple Silicon Homebrew too (it goes to /opt/homebrew and does not disturb the other one):"
    echo
    echo '    /bin/bash -c "$(curl -fsSL https://raw.githubusercontent.com/Homebrew/install/HEAD/install.sh)"'
    echo
    die "Then open a new Terminal window and run this script again."
fi
if ! command -v brew >/dev/null 2>&1; then
    echo "  Homebrew (the package manager) is not installed."
    echo "  Install it from https://brew.sh : open the Terminal and paste the one-line command shown there."
    echo "  At the time of writing it is:"
    echo
    echo '    /bin/bash -c "$(curl -fsSL https://raw.githubusercontent.com/Homebrew/install/HEAD/install.sh)"'
    echo
    die "When Homebrew is installed (follow the 'Next steps' it prints), open a new Terminal window and run this script again."
fi
echo "  Homebrew: $(brew --prefix)"

FREE_GB="$(df -g "$REPO" | awk 'NR==2 {print $4}')"
case "$FREE_GB" in
    ''|*[!0-9]*) ;;
    *) if [ "$FREE_GB" -lt 60 ]; then
           echo "  WARNING: only $FREE_GB GB free on this disk. About 60 GB are needed (the build, the shader cache and your dump). The build may stop when the disk is full."
       else
           echo "  Free disk space: $FREE_GB GB: ok"
       fi ;;
esac

if [ -n "$DUMP" ]; then
    [ -d "$DUMP/exefs" ] && [ -d "$DUMP/romfs" ] || die "The dump folder '$DUMP' must hold the folders exefs/ and romfs/ (see BUILDING.md, 'What you dump from your own console')."
    DUMP="$(cd "$DUMP" && pwd)"
fi

# ---------------------------------------------------------------------------------------------- 2. Homebrew packages
say "Homebrew packages (this can take a while the first time)"
brew install pkgconf sdl3 freetype openssl@3 ffmpeg glslang molten-vk vulkan-loader vulkan-tools opus python@3.12 git

# ---------------------------------------------------------------------------------------------- 3. Python packages
PY="$(brew --prefix python@3.12)/bin/python3.12"
[ -x "$PY" ] || PY="$(command -v python3.12 || command -v python3)"
[ -x "$PY" ] || die "Python was not found after the Homebrew install."
# a venv made earlier by an Intel (Rosetta) Python, or whose Python was removed, is made again
if [ -e "$DEPS/venv" ] && ! "$DEPS/venv/bin/python" -c 'import platform, sys; sys.exit(platform.machine() != "arm64")' >/dev/null 2>&1; then
    say "deps/venv does not run as Apple Silicon code (or its Python is gone): making it again"
    rm -rf "$DEPS/venv"
fi
if [ ! -x "$DEPS/venv/bin/python" ]; then
    say "Python virtual environment: deps/venv"
    mkdir -p "$DEPS"
    "$PY" -m venv "$DEPS/venv"
fi
say "Python packages: numpy lz4 zstandard Pillow unicorn capstone pycryptodome"
"$DEPS/venv/bin/python" -m pip install --quiet --upgrade pip
"$DEPS/venv/bin/python" -m pip install --quiet numpy lz4 zstandard Pillow unicorn capstone pycryptodome

# ---------------------------------------------------------------------------------------------- 4. Vulkan headers
VK_TAG=v1.4.351
if [ -f "$DEPS/Vulkan-Headers/include/vulkan/vulkan.h" ]; then
    say "deps/Vulkan-Headers: present"
else
    say "deps/Vulkan-Headers: Khronos headers $VK_TAG"
    rm -rf "$DEPS/Vulkan-Headers"
    git -c advice.detachedHead=false clone --quiet --depth 1 --branch "$VK_TAG" https://github.com/KhronosGroup/Vulkan-Headers.git "$DEPS/Vulkan-Headers"
fi

# ---------------------------------------------------------------------------------------------- Dear ImGui (the F1 settings menu)
IMGUI_TAG=v1.91.9b                 # MIT; the version the Windows build pins (scripts/install.py). Optional: without it no menu
if [ -f "$DEPS/imgui/imgui.h" ] && [ -f "$DEPS/imgui/imgui.cpp" ]; then
    say "deps/imgui: present"
else
    say "deps/imgui: Dear ImGui $IMGUI_TAG (the in-game settings menu, F1)"
    rm -rf "$DEPS/imgui"
    git -c advice.detachedHead=false clone --quiet --depth 1 --branch "$IMGUI_TAG" https://github.com/ocornut/imgui.git "$DEPS/imgui" || \
        say "WARNING: Dear ImGui could not be fetched: the game builds without the settings menu (F1)"
fi

# ---------------------------------------------------------------------------------------------- 5. reference data
if [ -f "$DEPS/suyu/src/core/hle/service/mii/types/raw_data.cpp" ]; then
    say "deps/suyu: present"
else
    say "deps/suyu: sparse checkout of Eden's Mii service sources (a few MB)"
    rm -rf "$DEPS/suyu"
    git clone --quiet --depth 1 --filter=blob:none --sparse https://git.eden-emu.dev/eden-emu/eden.git "$DEPS/suyu"
    git -C "$DEPS/suyu" sparse-checkout set src/core/hle/service/mii
    [ -f "$DEPS/suyu/src/core/hle/service/mii/types/raw_data.cpp" ] || \
        die "The checkout lacks src/core/hle/service/mii/types/raw_data.cpp. Any yuzu-family source tree that has it works: put it at deps/suyu."
fi

chmod +x "$REPO/play_mac.sh" "$REPO/scripts/macos/collect_logs_mac.sh" 2>/dev/null || true

# ---------------------------------------------------------------------------------------------- 6. the build
if [ -z "$DUMP" ]; then
    say "The tools are installed. Next, build the game from your own dump:"
    echo "  scripts/macos/install_mac.sh --dump <your dump folder>"
    exit 0
fi
say "Building the game from your dump (hours the first time; it can be stopped and started again)"
ARGS=(--target macos --dump "$DUMP")
if [ -n "$JOBS" ]; then
    ARGS+=(--jobs "$JOBS")
fi
"$DEPS/venv/bin/python" "$REPO/scripts/setup.py" "${ARGS[@]}" || {
    echo >&2
    echo "The build stopped. Run the same command again: it continues where it stopped." >&2
    echo "If it stops again at the same place, run scripts/macos/collect_logs_mac.sh and send the zip it makes." >&2
    exit 1; }

# ---------------------------------------------------------------------------------------------- 7. done
say "Done. Start the game with:"
echo "  ./play_mac.sh"
