#!/bin/bash
# S21 step 1: work_s20item as is: decompile (today's generator), build, offline gate 3 passes. DLL -> fighters_bin_s20item
cd "<project>/recomp-study/fighter_sdk/tools"
export SSBU_FIGHTERS_ROOT=work_s20item SSBU_FIGHTER_BIN=fighters_bin_s20item S2_JOBS=4 SSBU_BUILD_JOBS=8
python fighter_status.py decompile item
cd ../..
python tests/s18_build.py tests/s19_item.txt
python tests/s18_gate.py tests/s19_item.txt
echo STEP1 DONE
