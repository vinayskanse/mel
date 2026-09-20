#include "bubble.h"
#include <Arduino.h>
#include <string.h>
#include "board_config.h"
// text.h first: it is what includes Adafruit_GFX.h, and the Fonts/ headers
// below cannot be found until that has put the library on the include path.
#include "text.h"
#include <Fonts/FreeSans9pt7b.h>
#include <Fonts/TomThumb.h>

namespace bubble {
namespace {

// The band, in screen rows. It sits under the fly, which sits on the floor of
// the screen at around y=230 in portrait; 244..282 is below the legs and above
// the bottom edge, which is where the deskbuddy put the same thing.
const int TOP = 244, BOTTOM = 284;
const int SAY_BASELINE = 262;     // baseline, not top: a font is positioned by its baseline
const int SUB_BASELINE = 276;
const int MARGIN = 12;

const uint16_t COL_SAY = 0xFD23;  // the face's amber
const uint16_t COL_SUB = 0x9CD3;  // the same hue, lighter and duller, for the artist

const float FADE = 4.0f;          // fade in and out over a quarter of a second

char sayText[48] = "";
char subText[48] = "";
float alpha = 0.0f;               // 0..1, what is actually on screen
bool wanted = false;              // what set()/clear() last asked for

// True while anything of the band is drawn. The fade means "showing" and
// "there is ink in the band" are not the same instant, and the dirty rect has
// to follow the ink, not the intent -- otherwise the last frame of the fade is
// never cleared and a ghost of the title stays on the panel.
bool inked() { return alpha > 0.002f; }

}  // namespace

void set(const char* t, const char* s) {
  if (t) strlcpy(sayText, t, sizeof(sayText));
  if (s) strlcpy(subText, s, sizeof(subText));
  wanted = sayText[0] != 0;
}

void clear() {
  sayText[0] = subText[0] = 0;
  wanted = false;
}

bool showing() { return wanted; }

void update(float dt) {
  const float target = wanted ? 1.0f : 0.0f;
  const float step = FADE * dt;
  if (alpha < target) alpha = min(target, alpha + step);
  else if (alpha > target) alpha = max(target, alpha - step);
}

void draw(gfx::Band& b) {
  if (!inked()) return;
  const int a = (int)(alpha * 255.0f);

  if (sayText[0]) {
    char line[48];
    text::fit(&FreeSans9pt7b, sayText, line, sizeof(line), LCD_W - 2 * MARGIN);
    text::draw(b, &FreeSans9pt7b, line,
               (LCD_W - text::width(&FreeSans9pt7b, line)) / 2,
               SAY_BASELINE, COL_SAY, a);
  }
  if (subText[0]) {
    char line[48];
    text::fit(&TomThumb, subText, line, sizeof(line), LCD_W - 2 * MARGIN);
    // TomThumb is 3x5 and sits small under the title, which is what the
    // deskbuddy's built-in 5x7 artist line did: the title is the thing being
    // said, the artist is a footnote to it.
    text::draw(b, &TomThumb, line,
               (LCD_W - text::width(&TomThumb, line)) / 2,
               SUB_BASELINE, COL_SUB, (a * 3) / 4);
  }
}

void bbox(int& x0, int& y0, int& x1, int& y1) {
  if (!inked()) { x0 = y0 = 0; x1 = y1 = -1; return; }   // empty: caller skips it
  x0 = 0; x1 = LCD_W - 1;
  y0 = TOP; y1 = BOTTOM - 1;
}

}  // namespace bubble
