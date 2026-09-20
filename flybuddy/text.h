// Words on the screen, in the band renderer's own terms.
//
// The rest of this firmware draws analytic shapes: a rotated ellipse solves the
// conic for its own span on each row and every edge is antialiased from the
// real distance to the curve. Text is the one thing that cannot work that way,
// because letterforms are not conics, so this is the one place with a bitmap in
// it.
//
// The bitmaps are Adafruit_GFX's, not ours. FreeSans9pt7b is the font the
// deskbuddy's music_id.cpp drew song titles in, and reusing it means the band
// under the fly's face holds exactly what that one held. What is not reused is
// the renderer: Adafruit_GFX wants a canvas it owns, and there is no canvas
// here -- 240x296 would be 142 KB against the 15 KB band that is the whole
// point. So the glyph walk is thirty lines of our own, writing through the same
// gfx::blend as everything else.
#pragma once
#include <Adafruit_GFX.h>        // for the GFXfont/GFXglyph structs and the fonts
#include "gfx.h"

namespace text {

// Pixels this string occupies, for centring it.
int width(const GFXfont* font, const char* s);

// Draw at a baseline, the way a font expects to be positioned: `x` is the left
// edge of the first glyph's advance and `y` is the baseline, not the top.
// `alpha` is 0..255 over whatever is already in the band.
void draw(gfx::Band& b, const GFXfont* font, const char* s,
          int x, int y, uint16_t colour, int alpha = 255);

// Shorten until it fits maxW pixels, ending in an ellipsis if it was cut. The
// same idea as fit() in the deskbuddy's music_id.cpp, and as says.fit() on the
// host, so all three cut in the same place.
void fit(const GFXfont* font, const char* s, char* out, size_t outSize, int maxW);

}  // namespace text
