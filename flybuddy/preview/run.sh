#!/bin/sh
# Build and run the fly on this Mac, so the look and the motion can be checked
# without reflashing the board. Writes out_*.ppm here, then PNGs to look at.
set -e
cd "$(dirname "$0")"
CXX="${CXX:-clang++}"
FLAGS="-std=c++17 -O2 -Ishim -I.."
$CXX $FLAGS -o preview preview.cpp motion_stub.cpp ../gfx.cpp ../fly.cpp
$CXX $FLAGS -o spin    spin.cpp    motion_stub.cpp ../gfx.cpp ../fly.cpp
./preview
./spin
python3 sheet.py moods.png   grid 5 1 mood_idle mood_happy mood_excited mood_eating mood_sleeping \
                                      mood_dancing mood_curious mood_angry mood_letmeout mood_lowbatt
python3 sheet.py flight.png  grid 5 1 takeoff0 takeoff1 takeoff2 takeoff3 takeoff4 \
                                      touch0 touch1 touch2 touch3 portrait
python3 sheet.py poses.png   grid 6 1 portrait landscape upsidedown turn3 turn5 land5
python3 sheet.py idle.png    grid 6 1 idle0 idle2 idle4 idle6 idle8 idle10
python3 sheet.py face.png    crop 40 120 160 150 3 portrait mood_happy mood_angry
echo "wrote moods.png flight.png poses.png idle.png face.png"
