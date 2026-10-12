#!/bin/sh
# Start-up determinism check: N runs of S seconds; a run passes when the movie showed at least 30 frames, the game never
# called SeekTo, the movie was closed (title left) and frame 1800 has more than 100 draws (a menu; frame 1200 can fall on a fade).
#   sh tests/movie20.sh [exe] [runs] [seconds]
cd "$(dirname "$0")/.."
exe="${1:-ssbu_native.exe}"; n="${2:-20}"; secs="${3:-70}"; pass=0
mkdir -p tests/logs
for i in $(seq 1 "$n"); do
  log="tests/logs/movie_$i.log"
  RUN_LOG="$log" SSBU_TRACE="tests/logs/movie_trace.txt" SSBU_MOVIE_LOG=1 sh tests/run_battle.sh "$exe" "$secs" tests/seq_title.txt
  draws=$(grep -a "nvn_gl: frame 1800:" "$log" | sed 's/.*frame 1800: \([0-9]*\) draws.*/\1/')
  seeks=$(grep -a -c "movie: SeekTo" "$log")
  vframes=$(grep -a -c "\] V ReleaseOutput" "$log")
  left=$(grep -a -c "Extractor destroyed" "$log")
  ok=FAIL; if [ "$seeks" = 0 ] && [ "$vframes" -ge 30 ] && [ "$left" = 1 ] && [ -n "$draws" ] && [ "$draws" -gt 100 ]; then ok=ok; pass=$((pass + 1)); fi
  echo "run $i: video frames shown=$vframes SeekTo=$seeks movie closed=$left frame 1800 draws=${draws:-none} $ok"
done
echo "passed $pass of $n"
