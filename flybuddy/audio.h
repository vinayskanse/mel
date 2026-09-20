// ES8311 codec -> NS4150B amp -> 4 ohm speaker, playback only.
//
// Unlike the deskbuddy firmware this came from, nothing here is a clip. The
// fly's voice is synthesised continuously by song::, and this file only owns
// the codec, the I2S clocks and the amp: it pulls samples in real time on its
// own task, so the draw loop on the other core never waits for audio.
#pragma once
#include <stdint.h>

namespace audio {

bool begin();          // false if the codec doesn't answer
bool ready();

void setVolume(float v);   // 0..1, applied to the synthesiser's output
float level();             // 0..1 loudness of what is coming out right now

// Mute drops the gain to zero *and* holds the amp off. Gain alone is not
// enough: the amp is gated on the synthesiser's own level, so it would stay
// powered up with nothing to carry, which is exactly when it hisses.
void setMute(bool m);
bool muted();

}  // namespace audio
