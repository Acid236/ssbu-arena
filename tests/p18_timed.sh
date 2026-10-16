#!/bin/sh
# Round 18: a batch of TIMED runs (normal speed, presentation, display lock), as tests/p17_timed.sh, one game at a time.
#   sh tests/p18_timed.sh <batch tag> "<exe> <tag> <SSBU_DEBUG_MATCH> [NAME=VALUE ...]" [...]
# The caller has created tests/QUIET_PLEASE (Write tool) just before; this script waits until no other game exe runs
# (at most 4 minutes, then the batch is marked "shared"), runs, and DELETES tests/QUIET_PLEASE at the end.
# The owner plays = tests/OWNER_PLAYING AND an ssbu_native.exe process: no run is started then and the batch ends.
# Logs: tests/logs/vk13_p18t_<tag>.log / .hash / .shared, tests/logs/p16_sys_p18t_<tag>.txt, tests/logs/p18_batches.txt.
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
echo "batch $batch start $(date +%H:%M:%S) $quiet others=[$(tasklist | grep -i '^ssbu' | awk '{printf "%s ", $1}')]" >> tests/logs/p18_batches.txt
for spec in "$@"; do
    owner && { echo "  batch $batch stopped: the owner plays" >> tests/logs/p18_batches.txt; break; }
    (
        set -- $spec
        exe="$1"; tag="$2"; match="$3"; shift 3
        for kv in "$@"; do export "$kv"; done
        ( sleep 80; powershell -NoProfile -ExecutionPolicy Bypass -File tests/p15_sysstat.ps1 3 > "tests/logs/p16_sys_p18t_$tag.txt" 2>&1 ) &
        S13_TIMED=1 SSBU_SKIP_MOVIES=1 SSBU_GRAPHICS_CONFIG="${P16_INI:-tests/p15_timed.ini}" SSBU_RENDERER=vk SSBU_VK_CACHE=../cache/vk_p17 SSBU_VK_GPUTIME=1 SSBU_VK_PASSTIME=1 SSBU_LATELOG=1 SSBU_HITCH=18 \
            SSBU_DEBUG_MATCH="$match" SSBU_DEBUG_END="${P15_END:-1800}" sh tests/vk13_run.sh "p18t_$tag" 230 "$exe" tests/p18_seq_one.txt
        wait
        echo "  run $tag ($exe $*) done $(date +%H:%M:%S): $(cat tests/logs/vk13_p18t_$tag.shared | tr '\n' ' ')" >> tests/logs/p18_batches.txt
    )
done
rm -f tests/QUIET_PLEASE
echo "batch $batch end $(date +%H:%M:%S)" >> tests/logs/p18_batches.txt
