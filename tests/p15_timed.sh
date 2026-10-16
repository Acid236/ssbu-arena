#!/bin/sh
# Round "four players": a batch of TIMED runs (normal speed, presentation, display lock, movie skipped at the title).
#   sh tests/p15_timed.sh <batch tag> "<exe> <tag> <SSBU_DEBUG_MATCH>" ["<exe> <tag> <match>" ...]
# The caller has created tests/QUIET_PLEASE (Write tool) just before; this script waits until no other game exe runs
# (at most 5 minutes, then the batch is marked "shared"), runs, and DELETES tests/QUIET_PLEASE at the end.
# Next to every run: tests/logs/p15_sys_<tag>.txt = CPU frequency of the busiest cores, GPU state, other game exes
# (tests/p15_sysstat.ps1), sampled 40 s and 75 s after the start (in the fight).
cd "$(dirname "$0")/.." || exit 1
batch="$1"; shift
[ -e tests/QUIET_PLEASE ] || { echo "tests/QUIET_PLEASE is not there: create it first"; exit 1; }
n=0; quiet=quiet
while tasklist | grep -i '^ssbu' > /dev/null; do
    n=$((n + 1)); [ "$n" -gt 12 ] && { quiet=shared; break; }
    sleep 25
done
echo "batch $batch start $(date +%H:%M:%S) $quiet" >> tests/logs/p15_batches.txt
for spec in "$@"; do
    set -- $spec
    exe="$1"; tag="$2"; match="$3"
    [ -n "$4" ] && export "$4"                     # optional NAME=VALUE for this run and the ones after it
    ( sleep 75; powershell -NoProfile -ExecutionPolicy Bypass -File tests/p15_sysstat.ps1 3 > "tests/logs/p15_sys_$tag.txt" 2>&1
      sleep 20; powershell -NoProfile -ExecutionPolicy Bypass -File tests/p15_sysstat.ps1 3 >> "tests/logs/p15_sys_$tag.txt" 2>&1 ) &
    S13_TIMED=1 SSBU_SKIP_MOVIES=1 SSBU_GRAPHICS_CONFIG=tests/p15_timed.ini SSBU_RENDERER=vk SSBU_VK_CACHE=../cache/vk_p15 SSBU_VK_GPUTIME=1 SSBU_HITCH=18 \
        SSBU_DEBUG_MATCH="$match" SSBU_DEBUG_END="${P15_END:-1800}" sh tests/vk13_run.sh "p15t_$tag" 230 "$exe"
    wait
    echo "  run $tag ($exe) done $(date +%H:%M:%S): $(cat tests/logs/vk13_p15t_$tag.shared | tr '\n' ' ')" >> tests/logs/p15_batches.txt
done
rm -f tests/QUIET_PLEASE
echo "batch $batch end $(date +%H:%M:%S)" >> tests/logs/p15_batches.txt
