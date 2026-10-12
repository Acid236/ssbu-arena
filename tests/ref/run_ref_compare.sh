#!/bin/sh
# One-command regression against the reference emulator.      sh tests/ref/run_ref_compare.sh [exe]      (default ssbu_ref.exe)
#   1. reference side: cached. tests/ref/golden/ holds the emulator's checkpoint frames; they are captured only when
#      missing, or when REF_RECAPTURE=1 (starts the emulator copy under Documents/SSBU/ref-emu minimised, ~4 minutes).
#   2. port side: relinked from the current host sources under its own exe name (REF_NOLINK=1 to skip) and run
#      through the same scripted path every time; frames go to Documents/SSBU/ref-emu/work/port.
#   3. comparison: tests/ref/out/report.md (+ report.json, sheets/, crops/).
# Details: plan/phases/T1_reference.md
cd "$(dirname "$0")/../.." || exit 1
exe="${1:-ssbu_ref.exe}"
if [ ! -f tests/ref/golden/title.png ] || [ ! -f tests/ref/golden/burst/b_0000.png ] || [ "$REF_RECAPTURE" = 1 ]; then
  echo "== reference: capturing the golden frames on the emulator"
  python tests/ref/ref_capture.py --save "${REF_SAVE:-port}" --golden || { echo "reference capture FAILED (see ref-emu/work/emu/ref_capture.log)"; exit 1; }
else
  echo "== reference: using the cached golden frames (REF_RECAPTURE=1 to capture again)"
fi
if [ "$REF_NOLINK" != 1 ]; then
  echo "== port: linking $exe"
  RECOMP_EXE="$exe" python build.py link | tail -2 || true
fi
[ -f "$exe" ] || { echo "no $exe"; exit 1; }
echo "== port: running the scripted path"
python tests/ref/port_capture.py --exe "$exe" || exit 1
echo "== comparison"
python tests/ref/compare.py
