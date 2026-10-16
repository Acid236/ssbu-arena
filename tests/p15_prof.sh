#!/bin/sh
# Round "four players": one PROFILE run (fast mode, uncapped, muted), dump tests/logs/p15_prof_<tag>.txt
#   sh tests/p15_prof.sh <tag> <exe> "<SSBU_DEBUG_MATCH>" [fight seconds before the window] [window seconds]
cd "$(dirname "$0")/.." || exit 1
tag="$1"; exe="$2"; match="$3"
SSBU_RENDERER=vk SSBU_VK_CACHE=../cache/vk_p15 SSBU_PROF15="${4:-5},${5:-20},tests/logs/p15_prof_$tag.txt" SSBU_DEBUG_MATCH="$match" SSBU_DEBUG_END="${P15_END:-3600}" \
    sh tests/vk13_run.sh "p15$tag" 240 "$exe"
