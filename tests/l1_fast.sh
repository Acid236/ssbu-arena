#!/bin/sh
# Track L1: one FAST deterministic run (uncapped) through tests/vk13_run.sh.  sh tests/l1_fast.sh <tag> <exe> <seq file> [NAME=VALUE ...]
# Log tests/logs/vk13_l1_<tag>.log / .hash; pictures (SSBU_SHOT_FIGHT) in tests/l1_shots/<tag>/. Waits while the owner plays.
cd "$(dirname "$0")/.." || exit 1
tag="$1"; exe="$2"; seq="$3"; shift 3
for kv in "$@"; do export "$kv"; done
mkdir -p "tests/l1_shots/$tag"
while [ -e tests/OWNER_PLAYING ] && tasklist | grep -qi '^ssbu_native.exe'; do sleep 15; done
SSBU_L1=1 SSBU_RENDERER=vk SSBU_VK_CACHE="${SSBU_VK_CACHE-../cache/vk_l1}" SSBU_SHOT_DIR="tests/l1_shots/$tag" \
  SSBU_DEBUG_MATCH="${SSBU_DEBUG_MATCH-p1=mario,p2=donkey,stage=battle_field,form=normal,cpu=3,stock=3,items=off}" \
  SSBU_DEBUG_END="${SSBU_DEBUG_END-700}" sh tests/vk13_run.sh "l1_$tag" "${L1_SECS:-200}" "$exe" "$seq"
