#!/bin/sh
# Unattended tours. Each tests/tour/<name>.txt is an SSBU_SEQ sequence (%include expands, see tests/paths/expand.py),
# most of them starting from ../paths/_main_menu.txt (boot -> main menu).
#   sh tests/tour/run_tours.sh [-j N] [name ...]        no name = every tests/tour/*.txt except the _* helpers
# Per tour (fresh copy of ..\userdata each time, never the original):
#   tests/tour/out/<name>.log  run log      tests/tour/out/<name>/  distinct frames f<n>.png + sheet_NN.png
#   tests/tour/out/<name>.summary.txt  steps reached, stops/errors, last frame
#   tests/tour/out/ALL.txt  the summaries together
# Env: TOUR_EXE (default ssbu_tour.exe, link once: RECOMP_EXE=ssbu_tour.exe python build.py link), TOUR_SECS (default 240),
#      TOUR_EVERY (shot period in frames, default 45), TOUR_KEEPUD=1 keeps the userdata copies.
cd "$(dirname "$0")/../.." || exit 1
root="$(pwd)"; exe="${TOUR_EXE:-ssbu_tour.exe}"; secs="${TOUR_SECS:-240}"; every="${TOUR_EVERY:-45}"
jobs=1; [ "$1" = "-j" ] && { jobs="$2"; shift 2; }
names="$*"
[ -z "$names" ] && names="$(for f in tests/tour/*.txt; do b=$(basename "$f" .txt); case "$b" in _*) ;; *) echo "$b";; esac; done)"
mkdir -p tests/tour/out
one() {
  name="$1"
  out="tests/tour/out/$name"; rm -rf "$out"; mkdir -p "$out"
  ud="$root/tests/tour/ud_$name"; rm -rf "$ud"; cp -r "$root/../userdata" "$ud"
  seq="$(python tests/paths/expand.py "tests/tour/$name.txt")" || { echo "bad sequence $name"; return; }
  SSBU_USERDATA="$ud" SSBU_PAIR_WARM=0 SSBU_SEQ="$seq" SSBU_SEQ_LOG=60 SSBU_NRO_BIN="${SSBU_NRO_BIN:-nro_bin_eh_o2}" \
  SSBU_REC="tests/tour/out/$name.rec" SSBU_TRACE="tests/tour/out/$name.trace" SSBU_SHOT_EVERY="$every" SSBU_SHOT_DIR="$out" \
    "./$exe" ../binaries/13.0.4/main.elf "$secs" > "tests/tour/out/$name.log" 2>&1 &
  pid=$!
  sleep 1; powershell -NoProfile -Command "(Get-Process -Id $(cat /proc/$pid/winpid)).PriorityClass='AboveNormal'" 2>/dev/null
  wait $pid; echo "exit code $?" >> "tests/tour/out/$name.log"
  python tests/paths/summary.py "tests/tour/out/$name.log" "$out" > "tests/tour/out/$name.summary.txt" 2>&1
  tail -c 3000 "tests/tour/out/$name.log" | grep -v '^nvn_gl: program' | tail -12 | cut -c1-260 > "tests/tour/out/$name.tail.txt"
  [ -n "$TOUR_KEEPUD" ] || rm -rf "$ud"
  echo "== $name"; cat "tests/tour/out/$name.summary.txt"
}
for n in $names; do
  if [ "$jobs" -gt 1 ]; then one "$n" & while [ "$(jobs -r | wc -l)" -ge "$jobs" ]; do sleep 5; done; else one "$n"; fi
done > tests/tour/out/ALL.txt 2>&1
wait
cat tests/tour/out/ALL.txt
