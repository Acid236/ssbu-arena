#!/bin/sh
# Round 17, after the owner's correction (OpenGL is not the reference): frame-to-frame stability of the static stage
# meshes in a deterministic run (four consecutive fight frames on NVIDIA), and the same fights on the Intel device.
#   sh tests/p17_chainE.sh <Intel device number for SSBU_VK_DEVICE>
cd "$(dirname "$0")/.." || exit 1
while [ -e tests/OWNER_PLAYING ] || ! grep -q "^linked ssbu_p17b.exe" tests/logs/p17b_link.txt 2>/dev/null; do sleep 15; done
ZT="p1=mario,p2=donkey,p2=cpu,cpu=3,stage=zelda_temple"
YC="p1=mario,p2=donkey,p2=cpu,cpu=3,stage=yoshi_cartboard"
sh tests/p17_fast.sh yseq ssbu_p17b.exe "$YC" SSBU_SHOT_FIGHT=700,701,702,703,704,705 SSBU_DEBUG_END=800
sh tests/p17_fast.sh zseq ssbu_p17b.exe "$ZT" SSBU_SHOT_FIGHT=700,701,702,703 SSBU_DEBUG_END=800
sh tests/p17_fast.sh yint ssbu_p17b.exe "$YC" SSBU_SHOT_FIGHT=100,700,1200 SSBU_DEBUG_END=1300 SSBU_DRAWTAG=1 SSBU_VK_DEVICE="$1" SSBU_VK_PREPARE=off P17_SECS=500
sh tests/p17_fast.sh zint ssbu_p17b.exe "$ZT" SSBU_SHOT_FIGHT=100,700,1200 SSBU_DEBUG_END=1300 SSBU_DRAWTAG=1 SSBU_VK_DEVICE="$1" SSBU_VK_PREPARE=off P17_SECS=500
echo "chain E done"
