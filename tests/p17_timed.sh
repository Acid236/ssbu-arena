#!/bin/sh
# Round 17 (P3 section 16): a batch of TIMED runs, as tests/p16_timed.sh (normal speed, presentation, display lock), with the
# private cache ../cache/vk_p17, the per-pass GPU timers and the late-frame log.
#   sh tests/p17_timed.sh <batch tag> "<exe> <tag> <SSBU_DEBUG_MATCH> [NAME=VALUE ...]" ["<exe> <tag> <match> ..." ...]
# The caller has created tests/QUIET_PLEASE (Write tool) just before; this script waits until no other game exe runs
# (at most 5 minutes, then the batch is marked "shared"), runs, and DELETES tests/QUIET_PLEASE at the end.
# tests/OWNER_PLAYING: no run is started while it exists; when it appears DURING a run the guard (tests/p17_guard.ps1)
# stops that run by process id, the run is marked "owner" and the batch ENDS (QUIET_PLEASE is deleted).
# Logs: tests/logs/vk13_p17t_<tag>.log / .hash / .shared, tests/logs/p17_sys_<tag>.txt, tests/logs/p17_batches.txt.
cd "$(dirname "$0")/.." || exit 1
batch="$1"; shift
[ -e tests/QUIET_PLEASE ] || { echo "tests/QUIET_PLEASE is not there: create it first"; exit 1; }
n=0; quiet=quiet
while tasklist | grep -i '^ssbu' > /dev/null; do
    [ -e tests/OWNER_PLAYING ] && break
    n=$((n + 1)); [ "$n" -gt 12 ] && { quiet=shared; break; }
    sleep 25
done
echo "batch $batch start $(date +%H:%M:%S) $quiet" >> tests/logs/p17_batches.txt
for spec in "$@"; do
    [ -e tests/OWNER_PLAYING ] && { echo "  batch $batch stopped: OWNER_PLAYING" >> tests/logs/p17_batches.txt; break; }
    (
        set -- $spec
        exe="$1"; tag="$2"; match="$3"; shift 3
        for kv in "$@"; do export "$kv"; done
        stop="tests/logs/p17_stop_t_$tag"; rm -f "$stop"
        powershell -NoProfile -ExecutionPolicy Bypass -File tests/p17_guard.ps1 "${exe%.exe}" "$stop" &
        ( sleep 75; powershell -NoProfile -ExecutionPolicy Bypass -File tests/p15_sysstat.ps1 3 > "tests/logs/p17_sys_$tag.txt" 2>&1
          sleep 20; powershell -NoProfile -ExecutionPolicy Bypass -File tests/p15_sysstat.ps1 3 >> "tests/logs/p17_sys_$tag.txt" 2>&1 ) &
        S13_TIMED=1 SSBU_SKIP_MOVIES=1 SSBU_GRAPHICS_CONFIG="${P16_INI:-tests/p15_timed.ini}" SSBU_RENDERER=vk SSBU_VK_CACHE=../cache/vk_p17 SSBU_VK_GPUTIME=1 SSBU_VK_PASSTIME=1 SSBU_LATELOG=1 SSBU_HITCH=18 \
            SSBU_DEBUG_MATCH="$match" SSBU_DEBUG_END="${P15_END:-1800}" sh tests/vk13_run.sh "p17t_$tag" 230 "$exe"
        : > "$stop"; wait; rm -f "$stop"
        echo "  run $tag ($exe $*) done $(date +%H:%M:%S): $(cat tests/logs/vk13_p17t_$tag.shared | tr '\n' ' ')" >> tests/logs/p17_batches.txt
    )
done
rm -f tests/QUIET_PLEASE
echo "batch $batch end $(date +%H:%M:%S)" >> tests/logs/p17_batches.txt
