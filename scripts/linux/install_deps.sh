#!/usr/bin/env bash
# Installs what the native Linux build needs (see BUILDING_LINUX.md):
#   1. the system packages: clang, SDL3, FreeType, OpenSSL, FFmpeg, glslang, Vulkan loader, OpenGL, Opus (asks for sudo)
#   2. a Python virtual environment in deps/venv with the build's Python packages
#   3. deps/Vulkan-Headers: the Khronos headers at the tag the port was built with (v1.4.351)
#   4. deps/suyu: a sparse checkout of the Eden emulator source, of which only src/core/hle/service/mii is used
#      (reference data for the self-test, read by tools/lifter/gen_sdktest.py)
#
#   scripts/linux/install_deps.sh              everything
#   scripts/linux/install_deps.sh --no-system  skip step 1 (you install the packages yourself)
#   scripts/linux/install_deps.sh --steamos-host   on a Steam Deck: use pacman on SteamOS itself (see below) instead of
#                                              stopping with the advice to build in a distrobox container
#
# Package lists: Arch-based distributions were used to build and test the port. The Debian/Ubuntu and Fedora lists are
# the equivalent package names and have not been tried; `scripts/setup.py --target linux` checks every library and says
# what is missing.
set -euo pipefail

REPO="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
DEPS="$REPO/deps"
SYSTEM=1
STEAMOS_HOST=0
for arg in "$@"; do
    case "$arg" in
        --no-system) SYSTEM=0 ;;
        --steamos-host) STEAMOS_HOST=1 ;;
        -h|--help) sed -n '2,16p' "$0" | sed 's/^# \{0,1\}//'; exit 0 ;;
        *) echo "unknown option $arg" >&2; exit 2 ;;
    esac
done

say() { printf '\033[1m==> %s\033[0m\n' "$*"; }

# ---------------------------------------------------------------------------------------------- 1. system packages
if [ "$SYSTEM" = 1 ]; then
    . /etc/os-release
    # SteamOS (Steam Deck): the system is read-only, the deck user has no password until one is set, and every SteamOS
    # update puts the system back, removing what pacman installed. A distrobox container (SteamOS 3.5 and newer include
    # distrobox and podman) keeps the tools in your home folder, survives updates, and the game runs from it with the
    # Deck's GPU and sound. Inside the container /etc/os-release is the container's, so this check does not stop there.
    if [ "${ID:-}" = "steamos" ] && [ "$STEAMOS_HOST" = 0 ]; then
        say "SteamOS (Steam Deck): build inside a distrobox container"
        echo "  In Desktop Mode, open Konsole and run, from this folder:"
        echo
        echo "    distrobox create --name ssbu --image docker.io/library/archlinux:latest"
        echo "    distrobox enter ssbu"
        echo "    scripts/linux/install_deps.sh"
        echo "    deps/venv/bin/python scripts/setup.py --target linux --dump <your dump folder>"
        echo
        echo "  Keep this folder in your home folder (the container sees your home folder). Play with ./play.sh from"
        echo "  inside the container too (distrobox enter ssbu first)."
        echo "  To install on SteamOS itself instead (needs a sudo password, 'sudo steamos-readonly disable' and the"
        echo "  pacman keys; a SteamOS update removes the packages again), run this script with --steamos-host."
        exit 1
    fi
    if command -v pacman >/dev/null; then
        say "Arch-based system ($PRETTY_NAME): pacman"
        EXTRA=""
        # a Steam Deck (in a distrobox container a fresh Arch has no GPU driver and no sound client library): the Deck's
        # Vulkan driver (Mesa RADV) and libpulse, which SDL3 loads to play through the Deck's PipeWire
        if [ "$(cat /sys/devices/virtual/dmi/id/board_vendor 2>/dev/null)" = "Valve" ]; then
            EXTRA="vulkan-radeon libpulse"
            echo "  Steam Deck: also $EXTRA"
        fi
        # shellcheck disable=SC2086
        sudo pacman -S --needed clang pkgconf sdl3 freetype2 openssl ffmpeg glslang vulkan-icd-loader \
            libglvnd opus python git $EXTRA
    elif command -v apt-get >/dev/null; then
        say "Debian/Ubuntu-based system ($PRETTY_NAME): apt (SDL3 needs Debian 13 / Ubuntu 25.04 or newer)"
        sudo apt-get install -y clang pkg-config libsdl3-dev libfreetype-dev libssl-dev libavformat-dev libavcodec-dev \
            libswscale-dev libswresample-dev libavutil-dev glslang-dev libvulkan-dev libgl-dev libopus0 python3-venv git
    elif command -v dnf >/dev/null; then
        say "Fedora-based system ($PRETTY_NAME): dnf"
        sudo dnf install -y clang pkgconf-pkg-config SDL3-devel freetype-devel openssl-devel libavformat-free-devel \
            libavcodec-free-devel libswscale-free-devel libswresample-free-devel libavutil-free-devel glslang-devel \
            vulkan-loader-devel libglvnd-devel opus python3 git
    else
        say "Unknown distribution ($PRETTY_NAME): install these yourself, then run again with --no-system"
        echo "  clang, pkg-config, development files of: SDL3, FreeType, OpenSSL, FFmpeg (libavformat libavcodec"
        echo "  libswscale libswresample libavutil), glslang, Vulkan (headers + loader), OpenGL (libGL); the Opus"
        echo "  library; Python 3.10+ with venv; git"
        exit 1
    fi
    echo "  optional: zenity or kdialog (the game's on-screen keyboard, e.g. for naming a Mii, uses a dialog)"
fi

# ---------------------------------------------------------------------------------------------- 2. Python packages
PY="${PYTHON:-python3}"
"$PY" -c 'import sys; sys.exit(sys.version_info < (3, 10))' || { echo "Python 3.10 or newer is needed ($PY)" >&2; exit 1; }
if [ ! -x "$DEPS/venv/bin/python" ]; then
    say "Python virtual environment: deps/venv"
    mkdir -p "$DEPS"
    "$PY" -m venv "$DEPS/venv"
fi
say "Python packages: numpy lz4 zstandard Pillow unicorn capstone pycryptodome"
"$DEPS/venv/bin/python" -m pip install --quiet --upgrade pip
"$DEPS/venv/bin/python" -m pip install --quiet numpy lz4 zstandard Pillow unicorn capstone pycryptodome

# ---------------------------------------------------------------------------------------------- 3. Vulkan headers
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

# ---------------------------------------------------------------------------------------------- 4. reference data
if [ -f "$DEPS/suyu/src/core/hle/service/mii/types/raw_data.cpp" ]; then
    say "deps/suyu: present"
else
    say "deps/suyu: sparse checkout of Eden's Mii service sources (a few MB)"
    rm -rf "$DEPS/suyu"
    git clone --quiet --depth 1 --filter=blob:none --sparse https://git.eden-emu.dev/eden-emu/eden.git "$DEPS/suyu"
    git -C "$DEPS/suyu" sparse-checkout set src/core/hle/service/mii
    [ -f "$DEPS/suyu/src/core/hle/service/mii/types/raw_data.cpp" ] || {
        echo "the checkout lacks src/core/hle/service/mii/types/raw_data.cpp; any yuzu-lineage source tree that has it" >&2
        echo "works: put it at deps/suyu or pass --suyu <folder> to scripts/setup.py" >&2; exit 1; }
fi

say "done. Next:"
echo "  deps/venv/bin/python scripts/setup.py --target linux --dump <your dump folder>"
