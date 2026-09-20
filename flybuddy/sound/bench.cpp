#include "song.h"
#include <stdio.h>
#include <chrono>
#include <vector>
int main(){
  const int sr=16000; song::begin(sr);
  std::vector<int16_t> b(256);
  for (auto v : {song::COURT, song::FLIGHT, song::LOOM, song::EAT}) {
    song::play(v); song::render(b.data(), b.size());   // settle
    auto t0=std::chrono::high_resolution_clock::now();
    const int N=20000;
    for(int i=0;i<N;i++) song::render(b.data(), b.size());
    auto t1=std::chrono::high_resolution_clock::now();
    double sec=std::chrono::duration<double>(t1-t0).count();
    double samples=(double)N*b.size();
    printf("voice %d: %.1f ns/sample, %.0fx realtime on this Mac\n",
           (int)v, sec/samples*1e9, samples/sr/sec);
  }
}
