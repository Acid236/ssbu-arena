#!/bin/sh
# Track V (Vulkan), session 4: one scripted fight on REPEATABLE content, with a FRESH copy of the save.
#   sh tests/vk4_run.sh <tag> <seconds> [exe]         environment: SSBU_RENDERER, SSBU_VK_DEVICE, SSBU_SHOT_*, SSBU_HITCH ...
# SSBU_FIXED_SEED=1 (default here; SSBU_FIXED_SEED= turns it off) makes the clock reads the game seeds its random numbers
# from return a constant (nnsdk.c host_fixed_clock), so every run plays the same stage and the same CPU fighters
# (13.0.4, seq_battle_play.txt: script modules pichu, peach, miifighter, marth, mario, donkey).
# Writes tests/logs/vk4_<tag>.log; save copy: tests/vk4_ud_<tag> (never ..\userdata itself).
# The line "load:" in tests/logs/vk4_<tag>.load is what else was running on the PC when the run started.
cd "$(dirname "$0")/.." || exit 1
tag="${1:-x}"; secs="${2:-240}"; exe="${3:-ssbu_vk1.exe}"
ud="tests/vk4_ud_$tag"
mkdir -p "$ud/save" "$ud/cache"
cp -rf ../userdata/save/. "$ud/save/" || exit 1
echo "load: $(tasklist | grep -i -E '^(ssbu|yuzu|suyu|ryujinx|eden|citron)' | awk '{printf "%s(%s K) ", $1, $5}')" > "tests/logs/vk4_$tag.load"
SSBU_FIXED_SEED="${SSBU_FIXED_SEED-1}" SSBU_USERDATA="$ud" SSBU_REC="tests/logs/vk4_input_$tag.rec" SSBU_TRACE="tests/logs/vk4_trace_$tag.txt" RUN_LOG="tests/logs/vk4_$tag.log" \
    sh tests/run_battle.sh "$exe" "$secs" tests/seq_battle_play.txt
echo "exit $?"
