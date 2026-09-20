// Renders the fly on the Mac so the look and the motion can be checked
// without reflashing. Writes PPMs; sheet.py turns them into a PNG.
#include <Arduino.h>
#include "board_config.h"
#include "gfx.h"
#include "fly.h"
#include "motion.h"
#include <string>
namespace motion { void sim(float, float, float); }
unsigned long g_millis = 0;

static uint16_t fb[LCD_W * LCD_H];
static std::string out = "out";

static void renderWhole() {
  memset(fb, 0, sizeof(fb));
  gfx::Band b{fb, 0, 0, (int16_t)LCD_W, (int16_t)LCD_H};
  fly::draw(b);
}
static void shot(const std::string& name) {
  renderWhole();
  FILE* f = fopen((out + "_" + name + ".ppm").c_str(), "wb");
  fprintf(f, "P6\n%d %d\n255\n", LCD_W, LCD_H);
  for (int i = 0; i < LCD_W * LCD_H; i++) {
    uint16_t c = fb[i];
    unsigned char p[3] = {(unsigned char)(((c >> 11) & 0x1F) * 255 / 31),
                          (unsigned char)(((c >> 5) & 0x3F) * 255 / 63),
                          (unsigned char)((c & 0x1F) * 255 / 31)};
    fwrite(p, 1, 3, f);
  }
  fclose(f);
}
static void run(float angle, float spin, float jolt, int ms) {
  motion::sim(angle, spin, jolt);
  for (int t = 0; t < ms; t += 22) { g_millis += 22; fly::update(0.022f); }
}

int main(int argc, char** argv) {
  gfx::begin();
  randomSeed(11);
  fly::begin();
  if (argc > 1) out = argv[1];

  // The ten faces from the design sheet, each held long enough for the pose to
  // arrive and the symbol to fade in.
  static const char* MOODS[] = {"idle", "happy", "excited", "eating", "sleeping",
                                "dancing", "curious", "angry", "letmeout", "lowbatt"};
  for (int m = 0; m < fly::MOOD_N; m++) {
    fly::setMood((fly::Mood)m);
    run(0, 0, 0, 2600);
    shot(std::string("mood_") + MOODS[m]);
  }
  fly::autoMood();

  run(0, 0, 0, 3000);              shot("portrait");
  run((float)HALF_PI, 0, 0, 5000); shot("landscape");
  run((float)PI, 0, 0, 5000);      shot("upsidedown");

  // A turn, frame by frame: sitting, then rotated a quarter turn, then held
  // still. This is the whole point of the thing, so look at every step.
  run(0, 0, 0, 3000);
  for (int i = 0; i < 12; i++) {
    float a = (float)HALF_PI * (i < 6 ? i / 5.0f : 1.0f);
    float sp = i < 6 ? 2.6f : 0.0f;
    motion::sim(a, sp, i < 6 ? 0.35f : 0.0f);
    for (int t = 0; t < 130; t += 22) { g_millis += 22; fly::update(0.022f); }
    shot("turn" + std::to_string(i));
    printf("turn %2d  angle %.2f  %s\n", i, a, fly::stateName());
  }
  // Let it finish landing.
  for (int i = 0; i < 6; i++) {
    motion::sim((float)HALF_PI, 0, 0);
    for (int t = 0; t < 130; t += 22) { g_millis += 22; fly::update(0.022f); }
    shot("land" + std::to_string(i));
    printf("land %2d  %s\n", i, fly::stateName());
  }

  // Take-off and landing, frame by frame, the way the animation sheet lays
  // them out: ready, wings up, lift, airborne - then approach, touch down,
  // settle, sitting again.
  run(0, 0, 0, 2500);
  shot("takeoff0");
  motion::sim(0.9f, 2.4f, 0.4f);
  for (int i = 1; i < 5; i++) {
    for (int t = 0; t < 110; t += 22) { g_millis += 22; fly::update(0.022f); }
    shot("takeoff" + std::to_string(i));
  }
  run(0, 0, 0, 900);
  for (int i = 0; i < 4; i++) {
    for (int t = 0; t < 180; t += 22) { g_millis += 22; fly::update(0.022f); }
    shot("touch" + std::to_string(i));
  }

  // Idle, sampled every 900 ms: head turns, antenna flicks, grooming.
  run(0, 0, 0, 4000);
  for (int i = 0; i < 12; i++) {
    for (int t = 0; t < 900; t += 22) { g_millis += 22; fly::update(0.022f); }
    shot("idle" + std::to_string(i));
  }
  return 0;
}
