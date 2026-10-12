#!/bin/sh
# P3 round 4, final measurements: sh tests/p4_final.sh   (logs tests/logs/p4_final_*.log, summaries *.summary.txt)
cd "$(dirname "$0")/.." || exit 1
one() { # name exe seconds
  sh tests/p3c_run.sh "$2" "$1" "$3" 0 > "tests/logs/$1.summary.txt" 2>&1
  echo "== $1 ($2): pairs.txt $(wc -l < ../cache/shaders/pairs.txt) lines"
  grep "load before\|load after\|presents held\|draw calls over\|loaded ahead\|held its caller\|battle windows\|made ready\|pairs drawn\|GL errors [0-9]*, streamed\|shader workers" "tests/logs/$1.log" "tests/logs/$1.summary.txt" | cut -d: -f2- | sort -u | cut -c1-330
}
one p4_f0 ssbu_p4k.exe 200
one p4_final_i ssbu_p4k.exe 200
cp ssbu_p4k.exe ssbu_p4n.exe
one p4_final_ii ssbu_p4n.exe 200
cp ssbu_p4k.exe ssbu_p4o.exe
rm -rf tests/p4_cache_empty && mkdir tests/p4_cache_empty
SSBU_SHADER_CACHE=tests/p4_cache_empty one p4_final_iii ssbu_p4o.exe 200
echo ALLDONE
