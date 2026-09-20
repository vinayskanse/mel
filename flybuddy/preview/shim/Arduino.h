// Just enough Arduino to compile the renderer on the Mac and look at it.
#pragma once
#include <cstdint>
#include <cstdlib>
#include <cstring>
#include <cmath>
#include <cstdio>
#include <chrono>
#ifndef PI
#define PI 3.1415926535897932384626433832795
#endif
#define TWO_PI 6.283185307179586476925286766559
#define HALF_PI 1.5707963267948966192313216916398
extern unsigned long g_millis;
inline unsigned long millis() { return g_millis; }
inline long random(long a, long b) { return a + (long)(std::rand() % (b - a)); }
inline void randomSeed(unsigned s) { std::srand(s); }
template <class T> inline T mmin(T a, T b) { return a < b ? a : b; }
#define min(a,b) ((a)<(b)?(a):(b))
#define max(a,b) ((a)>(b)?(a):(b))
#define constrain(x,l,h) ((x)<(l)?(l):((x)>(h)?(h):(x)))
