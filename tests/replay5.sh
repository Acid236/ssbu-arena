#!/bin/sh
# N runs of a recording / sequence to the battle; a run passes when the script coroutines' L2CExceptionShutdown was thrown
# and caught and the process was still running at the time limit.   sh tests/replay5.sh [exe] [input] [seconds] [runs] [parallel]
cd "$(dirname "$0")/.."
exe="${1:-ssbu_native.exe}"; in="${2:-tests/user_mario_kirby_anchored.rec}"; secs="${3:-135}"; n="${4:-5}"; par="${5:-2}"; pass=0
mkdir -p tests/logs
i=1
while [ "$i" -le "$n" ]; do
  j=0
  while [ "$j" -lt "$par" ] && [ $((i + j)) -le "$n" ]; do
    k=$((i + j))
    RUN_LOG="tests/logs/replay_$k.log" SSBU_REC="tests/logs/replay_$k.rec" SSBU_TRACE="tests/logs/replay_trace_$k.txt" sh tests/run_battle.sh "$exe" "$secs" "$in" &
    j=$((j + 1))
  done
  wait
  j=0
  while [ "$j" -lt "$par" ] && [ $((i + j)) -le "$n" ]; do
    k=$((i + j)); log="tests/logs/replay_$k.log"
    throws=$(grep -a -c "^unwind: throw #" "$log"); alive=$(grep -a -c "still running after" "$log"); bad=$(grep -a -c "HOST EXCEPTION\|std::terminate\|C++ RUNTIME\|guest trap" "$log")
    mods=$(grep -a "LoadModule: lua2cpp_[a-z]* at" "$log" | sed 's/.*lua2cpp_\([a-z]*\) at.*/\1/' | tail -2 | tr '\n' ' ')
    last=$(grep -a "input anchor" "$log" | tail -1 | sed 's/input anchor \([0-9]*\).*: \(.*\)/\1 \2/')
    r=FAIL; if [ "$throws" -gt 0 ] && [ "$alive" = 1 ] && [ "$bad" = 0 ]; then r=ok; pass=$((pass + 1)); fi
    echo "run $k: throws caught (first 3 logged)=$throws still running=$alive errors=$bad fighters: $mods last anchor: $last $r"
    j=$((j + 1))
  done
  i=$((i + par))
done
echo "passed $pass of $n"
