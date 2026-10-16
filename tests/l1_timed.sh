#!/bin/sh
# Track L1 (copy of p18_timed.sh): a batch of TIMED runs (normal speed, presentation, display lock), as tests/p17_timed.sh, one game at a time.
#   sh tests/p18_timed.sh <batch tag> "<exe> <tag> <SSBU_DEBUG_MATCH> [NAME=VALUE ...]" [...]
# The caller has created tests/QUIET_PLEASE (Write tool) just before; this script waits until no other game exe runs
# (at most 4 minutes, then the batch is marked "shared"), runs, and DELETES tests/QUIET_PLEASE at the end.
# The owner plays = tests/OWNER_PLAYING AND an ssbu_native.exe process: no run is started then and the batch ends.
# Logs: tests/logs/vk13_l1t_<tag>.log / .hash / .shared, tests/logs/p16_sys_l1t_<tag>.txt, tests/logs/l1_batches.txt.
cd "$(dirname "$0")/.." || exit 1
batch="$1"; shift
[ -e tests/QUIET_PLEASE ] || { echo "tests/QUIET_PLEASE is not there: create it first"; exit 1; }
owner() { [ -e tests/OWNER_PLAYING ] && tasklist | grep -qi '^ssbu_native.exe'; }
n=0; quiet=quiet
while tasklist | grep -i '^ssbu' > /dev/null; do
    owner && break
    n=$((n + 1)); [ "$n" -gt 9 ] && { quiet=shared; break; }
    sleep 25
done
echo "batch $batch start $(date +%H:%M:%S) $quiet others=[$(tasklist | grep -i '^ssbu' | awk '{printf "%s ", $1}')]" >> tests/logs/l1_batches.txt
for spec in "$@"; do
    owner && { echo "  batch $batch stopped: the owner plays" >> tests/logs/l1_batches.txt; break; }
    (
        set -- $spec
        exe="$1"; tag="$2"; match="$3"; shift 3
        for kv in "$@"; do export "$kv"; done
        ( sleep 80; powershell -NoProfile -ExecutionPolicy Bypass -File tests/p15_sysstat.ps1 3 > "tests/logs/p16_sys_l1t_$tag.txt" 2>&1 ) &
        S13_TIMED=1 SSBU_SKIP_MOVIES=1 SSBU_GRAPHICS_CONFIG="${P16_INI:-tests/p15_timed.ini}" SSBU_RENDERER=vk SSBU_VK_CACHE=../cache/vk_l1 SSBU_LATELOG=1 SSBU_HITCH=18 SSBU_L1=1 \
            SSBU_DEBUG_MATCH="$match" SSBU_DEBUG_END="${P15_END:-1300}" sh tests/vk13_run.sh "l1t_$tag" 230 "$exe" "${L1_SEQ:-tests/l1_seq_press.txt}"
        wait
        echo "  run $tag ($exe $*) done $(date +%H:%M:%S): $(cat tests/logs/vk13_l1t_$tag.shared | tr '\n' ' ')" >> tests/logs/l1_batches.txt
    )
done
rm -f tests/QUIET_PLEASE
echo "batch $batch end $(date +%H:%M:%S)" >> tests/logs/l1_batches.txt
