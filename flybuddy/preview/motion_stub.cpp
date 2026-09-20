#include <Arduino.h>
#include "motion.h"
#include <cmath>
namespace motion {
static float A = 0, S = 0, J = 0;
void sim(float a, float s, float j) { A = a; S = s; J = j; }
bool begin() { return true; } bool present() { return true; } void update() {}
float uprightAngle() { return A; }
float spin() { return S; }
int orientation() { return (int)lroundf(A / (float)HALF_PI) & 3; }
float orientationAngle() { float s = orientation() * (float)HALF_PI; float d = s - A;
  while (d > (float)PI) d -= (float)TWO_PI; while (d < -(float)PI) d += (float)TWO_PI; return A + d; }
float jolt() { return J; }
bool flat() { return false; }
unsigned long stillFor() { return 10000; }
}
