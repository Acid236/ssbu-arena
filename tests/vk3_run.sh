#!/bin/sh
# Track V (Vulkan), session 3: one scripted fight with a FRESH copy of the save, so that milestone notices of earlier runs
# ("Traguardi: 10 incontri") cannot stop the input sequence.
#   sh tests/vk3_run.sh <tag> <seconds> [exe]         environment: SSBU_RENDERER, SSBU_VK_DEVICE, SSBU_SHOT_*, SSBU_HITCH ...
# Writes tests/logs/vk3_<tag>.log; save copy: tests/vk3_ud_<tag> (never ..\userdata itself).
cd "$(dirname "$0")/.." || exit 1
tag="${1:-x}"; secs="${2:-240}"; exe="${3:-ssbu_vk1.exe}"
ud="tests/vk3_ud_$tag"
mkdir -p "$ud/save" "$ud/cache"
cp -rf ../userdata/save/. "$ud/save/" || exit 1
SSBU_USERDATA="$ud" SSBU_REC="tests/logs/vk3_input_$tag.rec" SSBU_TRACE="tests/logs/vk3_trace_$tag.txt" RUN_LOG="tests/logs/vk3_$tag.log" \
    sh tests/run_battle.sh "$exe" "$secs" tests/seq_battle_play.txt
echo "exit $?"
