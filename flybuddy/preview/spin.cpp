#include <Arduino.h>
#include "board_config.h"
#include "gfx.h"
#include "fly.h"
#include "motion.h"
namespace motion { void sim(float, float, float); }
unsigned long g_millis = 0;

// Turn the board smoothly to `to` over `ms`, then hold still, and report what
// the fly does. Angles are absolute and unwrapped, so 2*PI really is a full
// turn rather than "back where we started".
static void turn(const char* label, float from, float to, int ms, int holdMs) {
  int steps = ms / 22; if (steps < 1) steps = 1;
  float rate = (to - from) / (ms / 1000.0f);
  const char* seen = "";
  for (int i = 1; i <= steps; i++) {
    float a = from + (to - from) * i / steps;
    motion::sim(a, rate, 0.30f);
    g_millis += 22; fly::update(0.022f);
    if (fly::stateName() != seen) { seen = fly::stateName(); printf("  %5lu ms  angle %6.2f  -> %s\n", g_millis, a, seen); }
  }
  for (int t = 0; t < holdMs; t += 22) {
    motion::sim(to, 0.0f, 0.0f);
    g_millis += 22; fly::update(0.022f);
    if (fly::stateName() != seen) { seen = fly::stateName(); printf("  %5lu ms  held still  -> %s\n", g_millis, seen); }
  }
  int x0, y0, x1, y1; fly::bbox(x0, y0, x1, y1);
  printf("%s: settled %s, centred at (%d,%d)\n\n", label, fly::stateName(), (x0 + x1) / 2, (y0 + y1) / 2);
}

int main() {
  gfx::begin(); randomSeed(3); fly::begin();
  motion::sim(0, 0, 0);
  for (int t = 0; t < 2000; t += 22) { g_millis += 22; fly::update(0.022f); }
  { int x0,y0,x1,y1; fly::bbox(x0,y0,x1,y1); printf("start: %s at (%d,%d)\n\n", fly::stateName(), (x0+x1)/2, (y0+y1)/2); }

  turn("quarter turn (landscape)", 0.0f,            (float)HALF_PI,  900, 2500);
  turn("half turn (upside down)", (float)HALF_PI,   (float)PI,       900, 2500);
  turn("back to portrait",        (float)PI,        (float)TWO_PI,   900, 2500);
  turn("one full 360 in one go",  (float)TWO_PI,    (float)(TWO_PI*2), 1400, 2500);
  return 0;
}
