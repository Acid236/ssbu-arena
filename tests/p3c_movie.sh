#!/bin/sh
# P3 round 3: N boots of S seconds on save copies; pass = movie left (Extractor destroyed), menus reached (frame 1800 > 100 draws), no frame over 2000 ms after frame 60 (the game's own 1.25 s pre-roll wait stays).
#   sh tests/p3c_movie.sh <exe> <runs> <seconds> <tag>      (environment passes through)
cd "$(dirname "$0")/.."
exe="${1:-ssbu_p3r.exe}"; n="${2:-20}"; secs="${3:-60}"; tag="${4:-p3c_movie}"; pass=0
for i in $(seq 1 "$n"); do
  log="tests/logs/${tag}_$i.log"; ud="tests/p3c_ud_${tag}"
  rm -rf "$ud" && cp -r ../userdata "$ud"
  SSBU_USERDATA="$ud" SSBU_HITCH=25 SSBU_CLOCKSTAT=1 RUN_LOG="$log" SSBU_TRACE="tests/logs/${tag}.trace.txt" SSBU_REC="tests/logs/${tag}.rec" SSBU_MOVIE_LOG=1 sh tests/run_battle.sh "$exe" "$secs" tests/seq_title.txt
  draws=$(grep -a "nvn_gl: frame 1800:" "$log" | sed 's/.*frame 1800: \([0-9]*\) draws.*/\1/')
  seeks=$(grep -a -c "movie: SeekTo" "$log")
  vframes=$(grep -a -c "\] V ReleaseOutput" "$log")
  left=$(grep -a -c "Extractor destroyed" "$log")
  worst=$(grep -a "^hitch: frame" "$log" | awk '$3>60 {if ($4+0>m) m=$4+0} END {print m+0}')
  ok=FAIL; if [ "$left" = 1 ] && [ -n "$draws" ] && [ "$draws" -gt 100 ] && [ "${worst%.*}" -lt 2000 ]; then ok=ok; pass=$((pass + 1)); fi
  echo "run $i: video frames shown=$vframes SeekTo=$seeks movie closed=$left frame 1800 draws=${draws:-none} longest frame after frame 60: $worst ms $ok"
done
echo "passed $pass of $n ($(tasklist | grep -c -i -E 'clang|cl\.exe|link\.exe|ninja|lld') compiler processes at the end)"
