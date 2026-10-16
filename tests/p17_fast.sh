#!/bin/sh
# Round 17 (P3 section 16): one FAST run (uncapped, muted, deterministic) through tests/vk13_run.sh with the private cache.
#   sh tests/p17_fast.sh <tag> <exe> <SSBU_DEBUG_MATCH> [NAME=VALUE ...]
# Never starts while tests/OWNER_PLAYING exists (checked here, in the command that starts the game), and a guard
# (tests/p17_guard.ps1) stops the game by process id when that file appears during the run; the run is then started
# again when the file is gone (at most 6 times).
# Log tests/logs/vk13_p17_<tag>.log / .hash; pictures (SSBU_SHOT_FIGHT=...) in tests/p17_shots/<tag>/.
cd "$(dirname "$0")/.." || exit 1
tag="$1"; exe="$2"; match="$3"; shift 3
for kv in "$@"; do export "$kv"; done
mkdir -p "tests/p17_shots/$tag"
[ -n "$match" ] && export SSBU_DEBUG_MATCH="$match"
try=0
while :; do
    while [ -e tests/OWNER_PLAYING ]; do sleep 15; done
    stop="tests/logs/p17_stop_$tag"; rm -f "$stop"
    powershell -NoProfile -ExecutionPolicy Bypass -File tests/p17_guard.ps1 "${exe%.exe}" "$stop" &
    SSBU_RENDERER="${SSBU_RENDERER-vk}" SSBU_VK_CACHE="${SSBU_VK_CACHE-../cache/vk_p17}" SSBU_SHOT_DIR="tests/p17_shots/$tag" \
        SSBU_DEBUG_END="${SSBU_DEBUG_END-1800}" sh tests/vk13_run.sh "p17_$tag" "${P17_SECS:-240}" "$exe" ${P17_SEQ:+"$P17_SEQ"}
    : > "$stop"; wait; rm -f "$stop"
    try=$((try + 1))
    if grep -q "debug end: .* fight frames reached\|exit 0" "tests/logs/vk13_p17_$tag.log" "tests/logs/vk13_p17_$tag.shared" 2>/dev/null; then break; fi
    [ -e tests/OWNER_PLAYING ] || break            # ended for another reason: not started again
    [ "$try" -ge 6 ] && break
done
echo "tries $try" >> "tests/logs/vk13_p17_$tag.shared"
tail -c 300 "tests/logs/vk13_p17_$tag.shared"
