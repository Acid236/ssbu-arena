#!/bin/sh
# Round 18: one FAST run (uncapped, muted, deterministic) through tests/vk13_run.sh with a private cache.
#   sh tests/p18_fast.sh <tag> <exe> <SSBU_DEBUG_MATCH or ""> [NAME=VALUE ...]      (P18_SEQ=<sequence file>, P18_SECS=<s>)
# Does not start while the owner plays (tests/OWNER_PLAYING AND an ssbu_native.exe process; the file alone is stale).
# Log tests/logs/vk13_p18_<tag>.log / .hash; pictures in tests/p18_shots/<tag>/.
cd "$(dirname "$0")/.." || exit 1
tag="$1"; exe="$2"; match="$3"; shift 3
for kv in "$@"; do export "$kv"; done
mkdir -p "tests/p18_shots/$tag"
[ -n "$match" ] && export SSBU_DEBUG_MATCH="$match"
while [ -e tests/OWNER_PLAYING ] && tasklist | grep -qi '^ssbu_native.exe'; do sleep 15; done
[ -e tests/OWNER_PLAYING ] && echo "OWNER_PLAYING without ssbu_native.exe: stale, run started" > "tests/logs/vk13_p18_$tag.note"
SSBU_RENDERER="${SSBU_RENDERER-vk}" SSBU_VK_CACHE="${SSBU_VK_CACHE-../cache/vk_p17}" SSBU_SHOT_DIR="tests/p18_shots/$tag" \
    SSBU_DEBUG_END="${SSBU_DEBUG_END-1500}" sh tests/vk13_run.sh "p18_$tag" "${P18_SECS:-300}" "$exe" ${P18_SEQ:+"$P18_SEQ"}
tail -c 300 "tests/logs/vk13_p18_$tag.shared"
