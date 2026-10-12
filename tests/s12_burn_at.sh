#!/bin/sh
# Track V session 12: start the CPU load (tests/s12_burn.py) when a line appears in a log.
#   sh tests/s12_burn_at.sh <log> <text to wait for> <processes> <seconds>
cd "$(dirname "$0")/.." || exit 1
n=0
while ! grep -a -q "$2" "$1" 2>/dev/null; do sleep 1; n=$((n + 1)); [ $n -gt 400 ] && exit 1; done
python tests/s12_burn.py "$3" "$4"
