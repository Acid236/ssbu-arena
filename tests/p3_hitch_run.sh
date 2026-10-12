#!/bin/sh
# P3: one battle run with the hitch log on a fresh copy of the save, then the summary.
#   sh tests/p3_hitch_run.sh <exe> <log name> [seconds] [module folder]
# Prints the load of the PC before the run (compilers running, CPU load), the battle windows and the hitch table.
cd "$(dirname "$0")/.." || exit 1
exe="${1:-ssbu_p3.exe}"; log="tests/logs/${2:-p3b_run}.log"; secs="${3:-170}"
[ -n "$4" ] && export SSBU_NRO_BIN="$4"
rm -rf tests/p3_userdata && cp -r ../userdata tests/p3_userdata
echo "load before the run: $(tasklist | grep -c -i -E 'clang|cl\.exe|link\.exe') compiler processes, $(tasklist | grep -c -i 'ssbu_') game processes, CPU $(powershell -NoProfile -Command "(Get-CimInstance Win32_Processor | Measure-Object -Property LoadPercentage -Average).Average")%"
SSBU_USERDATA=tests/p3_userdata SSBU_GLSTATS=1 SSBU_HITCH="${SSBU_HITCH:-25}" RUN_LOG="$log" SSBU_TRACE=tests/logs/p3b_trace.txt SSBU_REC=tests/logs/p3b_input.rec sh tests/run_battle.sh "$exe" "$secs" tests/seq_battle_play.txt
python tests/p3_summary.py "$log"
