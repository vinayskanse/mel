#!/bin/sh
# Build the sound engine on this Mac and render every voice to a .wav, so the
# fly can be listened to without reflashing the board. Same idea as preview/.
set -e
cd "$(dirname "$0")"
CXX="${CXX:-clang++}"
$CXX -std=c++17 -O2 -I.. -o test_song ../song.cpp test_main.cpp
$CXX -std=c++17 -O2 -I.. -o bench     ../song.cpp bench.cpp
./test_song --nopitch     # c_*_raw.wav : the true fly, 145/215 Hz, for headphones
./test_song               # c_*.wav     : pitch x3, what the board's speaker can play
./bench
