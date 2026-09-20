// Minimal JD9853 driver. The init table was extracted from the factory
// firmware (hwinfo/jd9853_init_table.txt in the deskbuddy project).
//
// This version blits rectangles rather than whole frames: open a window once,
// then push it band by band. Nothing here allocates.
#pragma once
#include <Arduino.h>
#include "board_config.h"

namespace lcd {

void begin();
void backlight(bool on);

// Open a rectangle for writing. Every pushRows() after this continues where
// the last one stopped, so a tall rectangle can be sent a band at a time.
void beginBlit(int x0, int y0, int x1, int y1);
// Pixels must already be big-endian (the panel's byte order).
void pushPixels(const uint16_t* be, size_t count);
void endBlit();

// Paint the whole panel one colour. Used once at boot.
void fillScreen(uint16_t color);

}  // namespace lcd
