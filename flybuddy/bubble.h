// The band under the fly's face: what it appears to be saying.
//
// The fly does not speak. Its voice is song.cpp -- wingbeats and the pulse
// train of a real D. melanogaster courtship song -- and interrupting that with
// a synthesised English sentence would be a shame. So the name of the song is
// shown, the way a comic panel puts words on an animal that has never spoken in
// its life, and the speaker keeps buzzing throughout.
//
// Two lines: what it says, and the artist under it in a smaller, dimmer font.
// Both arrive over the link already cut to length by the host, which cuts at
// the same place says.fit() does, so the log shows what the screen shows.
#pragma once
#include "gfx.h"

namespace bubble {

// Either line may be nullptr, which leaves that line as it was: the host
// changes the title and the artist in separate messages and should not have to
// resend one to keep the other.
void set(const char* text, const char* sub);
void clear();                                   // both lines, and the band goes
bool showing();

void update(float dt);                          // the fade in and out
void draw(gfx::Band& b);
void bbox(int& x0, int& y0, int& x1, int& y1);  // what it covers this frame, if anything

}  // namespace bubble
