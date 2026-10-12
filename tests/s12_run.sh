#!/bin/sh
# Track V session 12: one run of the scripted path with a FRESH copy of the save, in the debug FAST mode unless S12_TIMED=1.
#   [NAME=VALUE ...] sh tests/s12_run.sh <tag> <seconds> <exe> [sequence file]
# Log tests/logs/vk4_s12<tag>.log, save copy tests/vk4_ud_s12<tag> (never ..\userdata). Never starts while tests/QUIET_PLEASE
# exists unless S12_TIMED=1 (then the caller holds that file). The caller sets SSBU_VK_DEVICE, SSBU_VK_CACHE, ...
cd "$(dirname "$0")/.." || exit 1
tag="$1"; secs="$2"; exe="$3"; seq="${4:-tests/seq_battle_play_fast.txt}"
case "$exe" in ssbu_native.exe|ssbu_user.exe) echo "never the owner's exes"; exit 1;; esac
if [ -z "$S12_TIMED" ]; then
    while [ -e tests/QUIET_PLEASE ]; do sleep 20; done
    export SSBU_SPEED="${SSBU_SPEED-0}" SSBU_SKIP_MOVIES=1 SSBU_AUDIO_MUTE=1
else
    seq="${4:-tests/seq_battle_play.txt}"
fi
ud="tests/vk4_ud_s12$tag"
rm -rf "$ud"; mkdir -p "$ud/save" "$ud/cache"
cp -rf ../userdata/save/. "$ud/save/" || exit 1
echo "start $(date +%H:%M:%S) others=[$(tasklist | grep -i '^ssbu' | grep -v -i "^$exe" | awk '{printf "%s ", $1}')]" > "tests/logs/vk4_s12$tag.shared"
SSBU_GRAPHICS_CONFIG="${SSBU_GRAPHICS_CONFIG-tests/vk7_scale_i100.ini}" SSBU_FIXED_SEED="${SSBU_FIXED_SEED-1}" SSBU_USERDATA="$ud" SSBU_REC="tests/logs/vk4_input_s12$tag.rec" SSBU_TRACE="tests/logs/vk4_trace_s12$tag.txt" \
    RUN_LOG="tests/logs/vk4_s12$tag.log" sh tests/run_battle.sh "$exe" "$secs" "$seq"
echo "exit $? end $(date +%H:%M:%S) others=[$(tasklist | grep -i '^ssbu' | grep -v -i "^$exe" | awk '{printf "%s ", $1}')]" >> "tests/logs/vk4_s12$tag.shared"
