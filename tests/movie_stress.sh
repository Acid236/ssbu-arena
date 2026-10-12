#!/bin/sh
# Start-up under load: batches of P parallel runs of S seconds with the movie call log, no input (the movie just plays).
# A run is bad when the game called SeekTo or no video frame reached it.   sh tests/movie_stress.sh [exe] [batches] [parallel] [seconds]
cd "$(dirname "$0")/.."
exe="${1:-ssbu_native.exe}"; batches="${2:-4}"; par="${3:-3}"; secs="${4:-45}"; bad=0; total=0
mkdir -p tests/logs
for b in $(seq 1 "$batches"); do
  for p in $(seq 1 "$par"); do
    SSBU_MOVIE_LOG=1 SSBU_REC=tests/logs/stress.rec SSBU_TRACE="tests/logs/stress_trace_$p.txt" "./$exe" ../binaries/13.0.4/main.elf "$secs" > "tests/logs/stress_${b}_$p.log" 2>&1 &
  done
  wait
  for p in $(seq 1 "$par"); do
    log="tests/logs/stress_${b}_$p.log"; total=$((total + 1))
    seeks=$(grep -a -c "movie: SeekTo" "$log"); frames=$(grep -a -c "first frame copied to the game" "$log"); rel=$(grep -a -c "\] V ReleaseOutput" "$log")
    r=ok; if [ "$seeks" != 0 ] || [ "$frames" = 0 ] || [ "$rel" -lt 100 ]; then r=BAD; bad=$((bad + 1)); fi
    echo "batch $b run $p: SeekTo=$seeks first-frame lines=$frames video frames released=$rel $r"
  done
done
echo "bad $bad of $total"
