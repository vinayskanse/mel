// Render the band under the fly's face on this Mac, so the song titles can be
// read before anything is flashed. Writes out_bubble*.ppm here.
//
// It draws through the same band split the board uses -- 32 rows at a time,
// out of order in the sense that each band knows nothing about its neighbours
// -- because a glyph that straddles a band boundary is exactly the thing that
// would be wrong and invisible on a single full-size canvas.
#include <cstdio>
#include <cstring>
#include "../board_config.h"
#include "../bubble.h"
#include "../gfx.h"

unsigned long g_millis = 0;

static uint16_t screen[LCD_W * LCD_H];

static void render() {
  memset(screen, 0, sizeof(screen));
  const int ROWS = BAND_PIXELS / LCD_W;
  static uint16_t band[BAND_PIXELS];
  for (int y = 0; y < LCD_H; y += ROWS) {
    const int h = (y + ROWS <= LCD_H) ? ROWS : LCD_H - y;
    memset(band, 0, (size_t)LCD_W * h * 2);
    gfx::Band b{band, 0, (int16_t)y, (int16_t)LCD_W, (int16_t)h};
    bubble::draw(b);
    memcpy(screen + (size_t)y * LCD_W, band, (size_t)LCD_W * h * 2);
  }
}

static void write(const char* name) {
  char path[128];
  snprintf(path, sizeof(path), "out_bubble_%s.ppm", name);
  FILE* f = fopen(path, "wb");
  fprintf(f, "P6\n%d %d\n255\n", LCD_W, LCD_H);
  for (int i = 0; i < LCD_W * LCD_H; i++) {
    const uint16_t c = screen[i];
    const unsigned char rgb[3] = {
      (unsigned char)(((c >> 11) & 0x1F) * 255 / 31),
      (unsigned char)(((c >> 5) & 0x3F) * 255 / 63),
      (unsigned char)((c & 0x1F) * 255 / 31)};
    fwrite(rgb, 1, 3, f);
  }
  fclose(f);
  printf("  out_bubble_%s.ppm\n", name);
}

static void settle() {                 // run the fade to the end
  for (int i = 0; i < 40; i++) bubble::update(1.0f / 30.0f);
}

int main() {
  gfx::begin();
  struct { const char* name; const char* say; const char* sub; } cases[] = {
    {"known",   "that's Perfect", "Ed Sheeran"},
    {"learned", "ooh! Levitating", "Dua Lipa"},
    {"stumped", "no idea what this is", ""},
    {"listen",  "ooh, what's this", ""},
    {"long",    "pretty sure that's Bohemian Rhapsody", "Queen"},
    {"punct",   "I know this one... no I don't", "Various Artists (1975)"},
  };
  for (auto& c : cases) {
    bubble::set(c.say, c.sub);
    settle();
    render();
    write(c.name);
  }
  // And the fade-out, which is what the dirty rect has to keep up with.
  bubble::clear();
  for (int i = 0; i < 4; i++) bubble::update(1.0f / 30.0f);
  render();
  write("fading");
  int x0, y0, x1, y1;
  bubble::bbox(x0, y0, x1, y1);
  printf("  mid-fade bbox: %d,%d..%d,%d (must still cover the band)\n", x0, y0, x1, y1);
  settle();
  bubble::bbox(x0, y0, x1, y1);
  printf("  faded-out bbox: %d,%d..%d,%d (must be empty: x1 < x0)\n", x0, y0, x1, y1);
  return 0;
}
