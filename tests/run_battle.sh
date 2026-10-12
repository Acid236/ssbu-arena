#!/bin/sh
# Boot to a battle with scripted input.   sh tests/run_battle.sh [exe] [seconds] [input file]      (defaults: ssbu_native.exe 150 tests/user_mario_kirby_anchored.rec)
#   *.rec = a recording replayed with SSBU_PLAY (tests/user_mario_kirby_anchored.rec: the path the user played, P1 Kirby vs a random CPU, about 100 s to the battle)
#   *.txt = an SSBU_SEQ sequence (tests/seq_battle.txt: same path with the movie skipped at once and screens recognised by draw count, about 45 s)
# Output: run_battle.log (RUN_LOG), trace_battle.txt (SSBU_TRACE); SSBU_SHOT_EVERY=<k> [SSBU_SHOT_DIR, SSBU_SHOT_FROM] saves frame_<n>.bmp.
cd "$(dirname "$0")/.." && in="${3:-tests/user_mario_kirby_anchored.rec}" && case "$in" in *.rec) export SSBU_PLAY="$in";; *) export SSBU_SEQ="$(grep -v '^#' "$in" | tr '\n' ' ')";; esac && SSBU_REC="${SSBU_REC:-tests/logs/input_last.rec}" SSBU_TRACE="${SSBU_TRACE:-trace_battle.txt}" "./${1:-ssbu_native.exe}" ../binaries/13.0.4/main.elf "${2:-150}" > "${RUN_LOG:-run_battle.log}" 2>&1
