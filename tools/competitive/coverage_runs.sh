#!/bin/bash
# Coverage campaign for the reduced competitive build: CPU matches with every fighter on the 6 stages, competitive mode
# on, SSBU_COVERAGE adding the lifted functions each run executes to one file (runtime/coverage.c).
#   bash tools/competitive/coverage_runs.sh <userdata folder with a save> <coverage file> [seconds per fight, default 45]
# Uses the debug match (tests/DEBUG_MODE.md): p1 human (stands), p2..p4 CPU level 9. One process per match, 200 s
# of wall time (the fights restart until then). The save must have seen the DLC notices (a copy of your own
# saves\save); the menus are walked by tools/competitive/seq_real_save.txt (timed steps, title to fight).
set -u
SAVE="$1"; COV="$2"; SECS="${3:-45}"
cd "$(dirname "$0")/../.." || exit 1
FIGHTERS=(mario donkey link samus samusd yoshi kirby fox pikachu luigi ness captain purin peach daisy koopa popo sheik zelda
  mariod pichu falco marth lucina younglink ganon mewtwo roy chrom gamewatch metaknight pit pitb szerosuit wario snake ike
  pzenigame pfushigisou plizardon diddy lucas sonic dedede pikmin lucario robot toonlink wolf murabito rockman wiifit rosetta
  littlemac gekkouga palutena pacman reflet shulk koopajr duckhunt ryu ken cloud kamui bayonetta inkling ridley simon richter
  krool shizue gaogaen packun jack brave buddy dolly master tantan pickel edge eflame elight demon trail miifighter
  miiswordsman miigunner)
STAGES=(battle_field battle_field_s end poke_stadium2 animal_village animal_city)
WCOV=$(cygpath -w "$COV"); WSAVE=$(cygpath -w "$SAVE")
n=${#FIGHTERS[@]}; k=0
for ((i = 0; i < n; i += 4)); do
  f1=${FIGHTERS[i]}; f2=${FIGHTERS[(i + 1) % n]}; f3=${FIGHTERS[(i + 2) % n]}; f4=${FIGHTERS[(i + 3) % n]}
  st=${STAGES[k % 6]}; k=$((k + 1))
  echo "=== $k: $f1 $f2 $f3 $f4 on $st"
  timeout 600 python -u scripts/run.py --userdata "$SAVE" --exe ssbu_cov.exe --refresh --log "../coverage/run_$k.log" \
    --seq tools/competitive/seq_real_save.txt --seconds 200 \
    --env SSBU_SPEED=0 --env SSBU_SKIP_MOVIES=1 --env SSBU_AUDIO_MUTE=1 --env SSBU_PAIR_WARM=0 \
    --env SSBU_LOOSE_FILES=1 --env SSBU_COMPETITIVE=1 --env "SSBU_COVERAGE=$WCOV" \
    --env "SSBU_DEBUG_MATCH=p1=$f1,p2=$f2,p3=$f3,p4=$f4,stage=$st,cpu=9,p2=cpu,stock=3" --env "SSBU_DEBUG_END=${SECS}s" \
    > "../coverage/run_$k.out" 2>&1
  echo "    $(tail -1 "../coverage/run_$k.out")  $(grep -c "" "$COV" 2>/dev/null) functions"
done
