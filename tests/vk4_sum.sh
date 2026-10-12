#!/bin/sh
# Track V session 4: the short summary of one vk4 run.   sh tests/vk4_sum.sh <tag>
cd "$(dirname "$0")/.." || exit 1
L="tests/logs/vk4_$1.log"
cat "tests/logs/vk4_$1.load" 2>/dev/null
grep -a "nvn_vk: device\|nvn_vk: using\|pipelines made ahead\|FATAL\|HOST EXC\|validation messages\|Validation Error" "$L" | cut -c1-330 | tail -5
grep -a "nvn_vk_m4" "$L" | tail -2 | cut -c1-520
python tests/vk4_windows.py "$L" | grep -a "fight windows\|not clean" | cut -c1-175
grep -a "hitch: frame" "$L" | awk '{print $3, $4}' | sort -k2 -n -r | head -6 | tr '\n' ';'
echo
grep -a "input sequence" "$L" | tail -1 | cut -c1-90
grep -a "LoadModule: [a-z0-9_]* at" "$L" | cut -c29-38 | tr '\n' ' '
echo "| stage records: $(ls ../cache/vk/stage 2>/dev/null | grep -c '\.st$'), pipes.bin $(wc -c < ../cache/vk/pipes.bin 2>/dev/null) bytes"
