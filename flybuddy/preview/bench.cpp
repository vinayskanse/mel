// How long the fly takes to draw, in the same band-at-a-time shape the board
// uses: only the dirty rectangle, 32 rows at a time.
//
// This is a Mac, so the absolute number means nothing. What it is for is
// comparing one version of the fly against another, and catching a change that
// quietly doubles the cost.
#include <Arduino.h>
#include "board_config.h"
#include "gfx.h"
#include "fly.h"
#include "motion.h"
#include <chrono>
#include <cstdio>
namespace motion { void sim(float, float, float); }
unsigned long g_millis = 0;

static uint16_t band[BAND_PIXELS];

// One frame the way flybuddy.ino draws it: the fly's bounding box, in bands.
static long drawFrame() {
  int x0, y0, x1, y1;
  fly::bbox(x0, y0, x1, y1);
  x0 = x0 < 0 ? 0 : x0; y0 = y0 < 0 ? 0 : y0;
  x1 = x1 > LCD_W - 1 ? LCD_W - 1 : x1; y1 = y1 > LCD_H - 1 ? LCD_H - 1 : y1;
  if (x1 < x0 || y1 < y0) return 0;
  const int w = x1 - x0 + 1;
  int rows = BAND_PIXELS / w; if (rows < 1) rows = 1;
  long px = 0;
  for (int y = y0; y <= y1; y += rows) {
    const int h = (rows < y1 - y + 1) ? rows : (y1 - y + 1);
    memset(band, 0, (size_t)w * h * 2);
    gfx::Band b{band, (int16_t)x0, (int16_t)y, (int16_t)w, (int16_t)h};
    fly::draw(b);
    px += (long)w * h;
  }
  return px;
}

static void bench(const char* tag, int moodOrNeg, float angle, float spin, float jolt) {
  motion::sim(angle, spin, jolt);
  if (moodOrNeg >= 0) fly::setMood((fly::Mood)moodOrNeg); else fly::autoMood();
  for (int i = 0; i < 120; i++) { g_millis += 33; fly::update(0.033f); }   // settle

  const int N = 400;
  long px = 0;
  auto t0 = std::chrono::steady_clock::now();
  for (int i = 0; i < N; i++) {
    g_millis += 33;
    fly::update(0.033f);
    px += drawFrame();
  }
  auto t1 = std::chrono::steady_clock::now();
  double ms = std::chrono::duration<double, std::milli>(t1 - t0).count() / N;
  printf("%-22s %6.3f ms/frame   %5ld px/frame\n", tag, ms, px / N);
}

int main() {
  gfx::begin();
  randomSeed(11);
  fly::begin();
  printf("band %u B   dirty-rect draw, 400 frames each\n\n", (unsigned)sizeof(band));
  bench("sitting, idle",      fly::IDLE,     0.0f, 0, 0);
  bench("sitting, sleeping",  fly::SLEEPING, 0.0f, 0, 0);
  bench("sitting, dancing",   fly::DANCING,  0.0f, 0, 0);
  bench("landscape (bigger)", fly::IDLE,     (float)HALF_PI, 0, 0);
  bench("flying",             -1,            0.8f, 2.6f, 0.45f);
  return 0;
}
