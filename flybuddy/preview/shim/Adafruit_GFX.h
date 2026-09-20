// Just enough Adafruit_GFX to compile text.cpp and bubble.cpp on the Mac.
//
// The real header drags in the whole Adafruit_GFX class, Print, and
// Adafruit_BusIO, none of which this firmware uses: all it wants from that
// library is the two glyph structs and the font tables in Fonts/. On the board
// the real header is included, because that is also what puts Fonts/ on the
// include path. Here it is not available, so the structs are restated -- they
// are the library's own, copied from gfxfont.h, and the static_asserts in
// text.cpp would catch a drift.
#pragma once
#include <cstdint>
#include <cstddef>

#ifndef PROGMEM
#define PROGMEM
#endif

typedef struct {
  uint16_t bitmapOffset;
  uint8_t width, height, xAdvance;
  int8_t xOffset, yOffset;
} GFXglyph;

typedef struct {
  uint8_t* bitmap;
  GFXglyph* glyph;
  uint16_t first, last;
  uint8_t yAdvance;
} GFXfont;
