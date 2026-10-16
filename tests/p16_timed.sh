#!/bin/sh
# Round 16 (P3 section 15): a batch of TIMED runs, as tests/p15_timed.sh (normal speed, presentation, display lock).
#   sh tests/p16_timed.sh <batch tag> "<exe> <tag> <SSBU_DEBUG_MATCH> [NAME=VALUE ...]" ["<exe> <tag> <match> ..." ...]
# The NAME=VALUE words of a run apply to that run only. Private cache: ../cache/vk_p16 (a copy of ../cache/vk).
# The caller has created tests/QUIET_PLEASE (Write tool) just before; this script waits until no other game exe runs
# (at most 5 minutes, then the batch is marked "shared"), runs, and DELETES tests/QUIET_PLEASE at the end.
# Logs: tests/logs/vk13_p16t_<tag>.log / .hash / .shared, tests/logs/p16_sys_<tag>.txt, tests/logs/p16_batches.txt.
cd "$(dirname "$0")/.." || exit 1
batch="$1"; shift
[ -e tests/QUIET_PLEASE ] || { echo "tests/QUIET_PLEASE is not there: create it first"; exit 1; }
n=0; quiet=quiet
while tasklist | grep -i '^ssbu' > /dev/null; do
    n=$((n + 1)); [ "$n" -gt 12 ] && { quiet=shared; break; }
    sleep 25
done
echo "batch $batch start $(date +%H:%M:%S) $quiet" >> tests/logs/p16_batches.txt
for spec in "$@"; do
    (
        set -- $spec
        exe="$1"; tag="$2"; match="$3"; shift 3
        for kv in "$@"; do export "$kv"; done
        while [ -e tests/OWNER_PLAYING ]; do sleep 20; done      # the owner is playing: no game is started (rule of 2026-10-13 12:20)
        ( sleep 75; powershell -NoProfile -ExecutionPolicy Bypass -File tests/p15_sysstat.ps1 3 > "tests/logs/p16_sys_$tag.txt" 2>&1
          sleep 20; powershell -NoProfile -ExecutionPolicy Bypass -File tests/p15_sysstat.ps1 3 >> "tests/logs/p16_sys_$tag.txt" 2>&1 ) &
        S13_TIMED=1 SSBU_SKIP_MOVIES=1 SSBU_GRAPHICS_CONFIG="${P16_INI:-tests/p15_timed.ini}" SSBU_RENDERER=vk SSBU_VK_CACHE=../cache/vk_p16 SSBU_VK_GPUTIME=1 SSBU_HITCH=18 \
            SSBU_DEBUG_MATCH="$match" SSBU_DEBUG_END="${P15_END:-1800}" sh tests/vk13_run.sh "p16t_$tag" 230 "$exe"
        wait
        echo "  run $tag ($exe $*) done $(date +%H:%M:%S): $(cat tests/logs/vk13_p16t_$tag.shared | tr '\n' ' ')" >> tests/logs/p16_batches.txt
    )
done
rm -f tests/QUIET_PLEASE
echo "batch $batch end $(date +%H:%M:%S)" >> tests/logs/p16_batches.txt
