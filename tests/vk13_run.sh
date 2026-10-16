#!/bin/sh
# Track V session 13: one run with a FRESH copy of the save (never ..\userdata), debug FAST mode unless S13_TIMED=1.
#   [NAME=VALUE ...] sh tests/vk13_run.sh <tag> <seconds> <exe> [sequence file]
# Log tests/logs/vk13_<tag>.log, fight hash tests/logs/vk13_<tag>.hash, save copy tests/vk13_ud_<tag> (removed at the end).
# Never starts while tests/QUIET_PLEASE exists unless S13_TIMED=1 (then the caller holds that file).
# The caller sets SSBU_RENDERER, SSBU_VK_DEVICE, SSBU_VK_CACHE, SSBU_DEBUG_MATCH, SSBU_DEBUG_END, SSBU_SHOT_FIGHT, ...
cd "$(dirname "$0")/.." || exit 1
tag="$1"; secs="$2"; exe="$3"; seq="${4:-tests/seq_det_play.txt}"
case "$exe" in ssbu_native.exe|ssbu_user.exe) echo "never the owner's exes"; exit 1;; esac
if [ -z "$S13_TIMED" ]; then
    while [ -e tests/QUIET_PLEASE ]; do sleep 20; done
    export SSBU_SPEED="${SSBU_SPEED-0}" SSBU_SKIP_MOVIES=1 SSBU_AUDIO_MUTE=1
fi
ud="tests/vk13_ud_$tag"
rm -rf "$ud"; mkdir -p "$ud/save" "$ud/cache"
cp -rf ../userdata/save/. "$ud/save/" || exit 1
echo "start $(date +%H:%M:%S) others=[$(tasklist | grep -i '^ssbu' | grep -v -i "^$exe" | awk '{printf "%s ", $1}')]" > "tests/logs/vk13_$tag.shared"
SSBU_GRAPHICS_CONFIG="${SSBU_GRAPHICS_CONFIG-tests/vk13.ini}" SSBU_FIXED_SEED="${SSBU_FIXED_SEED-1}" SSBU_USERDATA="$ud" \
    SSBU_DLC_LIST="${SSBU_DLC_LIST-tests/vk13_nodlc.txt}" SSBU_DETERMINISTIC="${SSBU_DETERMINISTIC-1}" SSBU_FIGHT_HASH="${SSBU_FIGHT_HASH-tests/logs/vk13_$tag.hash}" \
    SSBU_REC="tests/logs/vk13_input_$tag.rec" SSBU_TRACE="tests/logs/vk13_trace_$tag.txt" \
    RUN_LOG="tests/logs/vk13_$tag.log" sh tests/run_battle.sh "$exe" "$secs" "$seq"
rc=$?
echo "exit $rc end $(date +%H:%M:%S) others=[$(tasklist | grep -i '^ssbu' | grep -v -i "^$exe" | awk '{printf "%s ", $1}')]" >> "tests/logs/vk13_$tag.shared"
rm -rf "$ud"
