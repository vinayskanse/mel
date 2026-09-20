// The fly's voice. A synthesiser, not a sample bank: every sound is built from
// one sine table and a handful of oscillators, so the whole animal's repertoire
// costs 512 bytes of ROM and no heap at all.
//
// The numbers come from measuring a real recording of a male D. melanogaster
// courting a female (see ../../research/song/README.md). They are not invented.
#pragma once
#include <stdint.h>

namespace song {

enum Voice {
  QUIET,     // nothing
  COURT,     // the courtship song: pulse trains and sine song, in bouts
  FLIGHT,    // wingbeat buzz, steady
  TAKEOFF,   // a burst of pulses, then the buzz
  LOOM,      // a buzz that rises and swells, as if coming at you
  EAT,       // legs rubbing at the mouth
};

void  begin(float sample_rate);   // sets up the oscillators
void  play(Voice v);              // takes effect at the next block
Voice playing();

// Fills `n` mono samples. Call it from whatever feeds the codec.
// Cheap enough to run inside the I2S callback: ~30 float ops per sample.
void  render(int16_t* out, int n);

// Everything the song is made of, in one place so it can be tuned by ear
// without hunting through the code. Defaults are the measured values.
struct Params {
  float pulse_f, pulse_f_sd, pulse_tau;   // the click: damped sine
  float ipi, ipi_sd, ipi_min;             // gap between clicks
  float sine_f, sine_f_sd, sine_h2;       // the hum
  float wing_f;                           // wingbeat
  float pitch;                            // multiply every frequency by this
  float gain;
};
extern Params P;

}  // namespace song
