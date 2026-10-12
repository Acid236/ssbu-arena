#!/bin/sh
# P3 round 3: one battle run on a fresh save copy of its own, hitch log + clock line, then the summary.
#   sh tests/p3c_run.sh <exe> <log name> [seconds] [shot every N frames, 0 = none]
# Environment passes through (SSBU_OLD_PACING=1, SSBU_HITCH=<ms>, ...). The save copy is tests/p3c_ud_<log name>.
cd "$(dirname "$0")/.." || exit 1
exe="${1:-ssbu_p3r.exe}"; name="${2:-p3c_run}"; log="tests/logs/$name.log"; secs="${3:-170}"; shot="${4:-0}"
ud="tests/p3c_ud_$name"
rm -rf "$ud" && cp -r ../userdata "$ud"
if [ "$shot" != 0 ]; then mkdir -p "tests/shots_p3c/$name"; export SSBU_SHOT_EVERY="$shot" SSBU_SHOT_DIR="tests/shots_p3c/$name"; fi
echo "load before the run: $(tasklist | grep -c -i -E 'clang|cl\.exe|link\.exe|ninja|lld') compiler processes, $(tasklist | grep -c -i 'ssbu_') game processes, CPU $(powershell -NoProfile -Command "(Get-CimInstance Win32_Processor | Measure-Object -Property LoadPercentage -Average).Average")%"
SSBU_USERDATA="$ud" SSBU_GLSTATS=1 SSBU_CLOCKSTAT=1 SSBU_HITCH="${SSBU_HITCH:-25}" RUN_LOG="$log" SSBU_TRACE="tests/logs/$name.trace.txt" SSBU_REC="tests/logs/$name.rec" sh tests/run_battle.sh "$exe" "$secs" tests/seq_battle_play.txt
echo "load after the run: $(tasklist | grep -c -i -E 'clang|cl\.exe|link\.exe|ninja|lld') compiler processes"
grep "^clock:" "$log"
python tests/p3_summary.py "$log"
