#include "text.h"
#include <string.h>

namespace text {
namespace {

// The glyph for a character, or nullptr for anything outside the font. Space
// is inside every font here, so a missing glyph really is a character the font
// does not have, and skipping it entirely is better than a box.
const GFXglyph* glyphOf(const GFXfont* font, unsigned char ch) {
  if (ch < font->first || ch > font->last) return nullptr;
  return &font->glyph[ch - font->first];
}

}  // namespace

int width(const GFXfont* font, const char* s) {
  int w = 0;
  for (; *s; s++) {
    const GFXglyph* g = glyphOf(font, (unsigned char)*s);
    if (g) w += g->xAdvance;
  }
  return w;
}

void draw(gfx::Band& b, const GFXfont* font, const char* s,
          int x, int y, uint16_t colour, int alpha) {
  if (alpha <= 0) return;
  if (alpha > 255) alpha = 255;
  const int cov = alpha + (alpha >> 7);          // 0..255 -> 0..256, gfx::blend's range

  for (; *s; s++) {
    const GFXglyph* g = glyphOf(font, (unsigned char)*s);
    if (!g) continue;
    const uint8_t* bits = font->bitmap + g->bitmapOffset;
    const int gx = x + g->xOffset, gy = y + g->yOffset;

    // The glyph bitmap is one bit per pixel, packed across rows with no
    // per-row padding, so the bit index runs straight through.
    uint32_t bit = 0;
    for (int row = 0; row < g->height; row++) {
      const int Y = gy + row;
      // The band is a strip of the screen; most glyph rows of most glyphs are
      // not in it. Skipping the row still has to advance the bit cursor.
      if (Y < b.y0 || Y >= b.y0 + b.h) { bit += g->width; continue; }
      uint16_t* line = b.row(Y);
      for (int col = 0; col < g->width; col++, bit++) {
        if (!(bits[bit >> 3] & (0x80 >> (bit & 7)))) continue;
        const int X = gx + col;
        if (X < b.x0 || X >= b.x0 + b.w) continue;
        uint16_t* p = line + (X - b.x0);
        *p = gfx::blend(*p, colour, cov);
      }
    }
    x += g->xAdvance;
  }
}

void fit(const GFXfont* font, const char* s, char* out, size_t outSize, int maxW) {
  strlcpy(out, s, outSize);
  if (width(font, out) <= maxW) return;
  for (size_t n = strlen(out); n > 3; n--) {
    strcpy(out + n - 3, "...");
    if (width(font, out) <= maxW) return;
  }
  out[0] = 0;               // not even "..." fits; better nothing than a stub
}

}  // namespace text
