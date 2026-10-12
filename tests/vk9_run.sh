#!/bin/sh
# Track V/O session 9: one scripted match per line of the list, one after the other, each on a PC with no other game exe.
#   sh tests/vk9_run.sh <exe> <seconds> <tag>:<device>:<scale>[:<extra env as NAME=VALUE,NAME=VALUE>] ...
# The caller makes tests/QUIET_PLEASE before and deletes it after (the other agent starts no game while it exists).
# Per run: waits (up to 5 min) until no other ssbu*.exe runs; tests/logs/vk4_<tag>.shared says what ran at start and end.
# Options file: tests/vk7_scale_i100.ini (1280x720 window, vsync = clock); SSBU_VK_DEVICE and SSBU_VK_SCALE win over it.
cd "$(dirname "$0")/.." || exit 1
exe="$1"; secs="$2"; shift 2
others() { tasklist | grep -i '^ssbu' | grep -v -i "^$exe" | awk '{printf "%s ", $1}'; }
for spec in "$@"; do
    tag=$(echo "$spec" | cut -d: -f1); dev=$(echo "$spec" | cut -d: -f2); scale=$(echo "$spec" | cut -d: -f3); extra=$(echo "$spec" | cut -d: -f4 | tr ',' ' ')
    waited=0
    while [ -n "$(others)" ] && [ $waited -lt 300 ]; do sleep 20; waited=$((waited + 20)); done
    echo "start $(date +%H:%M:%S) waited=${waited}s others_at_start=[$(others)]" > "tests/logs/vk4_$tag.shared"
    env SSBU_GRAPHICS_CONFIG=tests/vk7_scale_i100.ini SSBU_VK_DEVICE="$dev" SSBU_VK_SCALE="$scale" SSBU_VK_GPUTIME=1 SSBU_VK_CACHE="${VK9_CACHE:-cache/vk_s7_first}" SSBU_HITCH=30 $extra \
        sh tests/vk4_run.sh "$tag" "$secs" "$exe" > /dev/null 2>&1
    echo "end $(date +%H:%M:%S) others_at_end=[$(others)]" >> "tests/logs/vk4_$tag.shared"
    echo "== $tag ($dev, $scale): $(cat tests/logs/vk4_$tag.shared | tr '\n' ' ')"
    grep -a -E "^nvn_vk_gpu_fight|^nvn_vk: [0-9]+ frames presented|^nvn_vk_scale: resolution|picture of battle" "tests/logs/vk4_$tag.log" | cut -c1-520
done
