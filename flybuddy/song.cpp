#include "song.h"
#include <math.h>

namespace song {

// ---------------------------------------------------------------- parameters
Params P = {
  /* pulse_f   */ 215.0f,  /* pulse_f_sd */ 18.0f,  /* pulse_tau */ 0.0032f,
  /* ipi       */ 0.0350f, /* ipi_sd     */ 0.0070f,/* ipi_min   */ 0.018f,
  /* sine_f    */ 145.0f,  /* sine_f_sd  */ 9.0f,   /* sine_h2   */ 0.14f,
  /* wing_f    */ 200.0f,
  /* pitch     */ 3.0f,    // the speaker cannot do 145 Hz; see the README
  /* gain      */ 0.85f,
};

static float SR = 16000.0f;

// ------------------------------------------------------------------ plumbing
// 256-entry quarter-symmetric sine, built once. Linear interpolation between
// entries is below the noise floor of a 4 ohm toy speaker.
static float sineTab[257];

static inline float osc(float phase) {          // phase in turns, [0,1)
  phase -= floorf(phase);
  const float x = phase * 256.0f;
  const int   i = (int)x;
  const float f = x - i;
  return sineTab[i] + (sineTab[i + 1] - sineTab[i]) * f;
}

// xorshift: the jitter matters more than its quality, and rand() is not
// safe to call from an audio task.
static uint32_t rngState = 0x1234567u;
static inline uint32_t rnd() {
  rngState ^= rngState << 13; rngState ^= rngState >> 17; rngState ^= rngState << 5;
  return rngState;
}
static inline float uni()          { return (rnd() >> 8) * (1.0f / 16777216.0f); }
static inline float uni(float a, float b) { return a + (b - a) * uni(); }
static inline float gauss()        { return (uni() + uni() + uni() - 1.5f) * 2.0f; }

// -------------------------------------------------------------------- voices
static Voice voice = QUIET, pending = QUIET;

// one damped-sine click, retriggered by the sequencer
struct Pulse {
  float phase, dphase, amp, decay;
  bool  live;
  void trig() {
    const float f = (P.pulse_f + gauss() * P.pulse_f_sd) * P.pitch;
    dphase = f / SR;
    phase  = 0.0f;
    amp    = uni(0.6f, 1.0f);
    decay  = expf(-1.0f / (P.pulse_tau * SR));
    live   = true;
  }
  float next() {
    if (!live) return 0.0f;
    const float s = osc(phase) * amp;
    phase += dphase;
    amp   *= decay;
    if (amp < 0.0005f) live = false;
    return s;
  }
};

static Pulse   pulse;
static float   sinePhase, winPhase, lfoPhase, modPhase;
static float   sineF      = 145.0f;      // drifts
static int32_t nextPulse  = 0;           // samples until the next click
static int32_t boutLeft   = 0;           // samples left in this bout
static int     bout       = 0;           // 0 pulse train, 1 sine song, 2 silence
static float   loomT      = 0.0f;
static int32_t tickLeft   = 0;
static float   tickAmp    = 0.0f, tickState = 0.0f;
static float   env        = 0.0f;        // global fade, kills clicks on switch

static void nextBout() {
  const float r = uni();
  bout     = (r < 0.44f) ? 0 : (r < 0.87f ? 1 : 2);
  boutLeft = (int32_t)(SR * (bout == 0 ? uni(0.15f, 1.5f)
                          :  bout == 1 ? uni(0.20f, 1.9f)
                                       : uni(0.15f, 0.8f)));
}

// -------------------------------------------------------------------- public
void begin(float sample_rate) {
  SR = sample_rate;
  for (int i = 0; i <= 256; i++) sineTab[i] = sinf(6.2831853f * i / 256.0f);
  sinePhase = winPhase = lfoPhase = modPhase = 0.0f;
  nextBout();
}

void  play(Voice v) { pending = v; }
Voice playing()     { return voice; }

void render(int16_t* out, int n) {
  for (int k = 0; k < n; k++) {
    // Cross-fade through zero when the voice changes, so nothing ever clicks.
    if (pending != voice) {
      env -= 1.0f / (0.004f * SR);
      if (env <= 0.0f) { env = 0.0f; voice = pending; loomT = 0.0f; }
    } else if (env < 1.0f) {
      env += 1.0f / (0.004f * SR);
      if (env > 1.0f) env = 1.0f;
    }

    float s = 0.0f;
    switch (voice) {

      case COURT:
        if (--boutLeft <= 0) nextBout();
        if (bout == 0) {                                   // pulse train
          if (--nextPulse <= 0) {
            pulse.trig();
            float ipi = P.ipi + gauss() * P.ipi_sd;
            if (ipi < P.ipi_min) ipi = P.ipi_min;
            nextPulse = (int32_t)(ipi * SR);
          }
          s = pulse.next() * 0.55f;
        } else if (bout == 1) {                            // sine song
          sineF += gauss() * 0.6f;                         // slow random walk
          if (sineF > P.sine_f + P.sine_f_sd) sineF = P.sine_f + P.sine_f_sd;
          if (sineF < P.sine_f - P.sine_f_sd) sineF = P.sine_f - P.sine_f_sd;
          sinePhase += sineF * P.pitch / SR;
          lfoPhase  += 3.3f / SR;
          s = (osc(sinePhase) + P.sine_h2 * osc(2.0f * sinePhase))
              * (0.85f + 0.15f * osc(lfoPhase)) * 0.17f;
        }
        break;

      case TAKEOFF:
      case FLIGHT:
      case LOOM: {
        float f    = P.wing_f;
        float a    = 0.30f;
        if (voice == LOOM) {
          loomT += 1.0f / SR;
          if (loomT > 1.6f) loomT = 1.6f;
          f = 175.0f + 80.0f * (loomT / 1.6f);             // pitch rises
          a = 0.04f * expf(2.2f * loomT / 1.6f) * 0.30f;   // and it swells
        }
        modPhase += 17.0f / SR;                            // wing jitter
        lfoPhase += 6.3f / SR;
        const float fm = 1.0f + 0.02f * osc(modPhase) + 0.015f * osc(lfoPhase);
        winPhase += f * fm * P.pitch / SR;
        s = (osc(winPhase) + 0.55f * osc(2.0f * winPhase)
                           + 0.30f * osc(3.0f * winPhase)
                           + 0.15f * osc(4.0f * winPhase)) * a;
        if (voice == TAKEOFF) {                            // clicks over the buzz
          if (--nextPulse <= 0) { pulse.trig(); nextPulse = (int32_t)(0.030f * SR); }
          s += pulse.next() * 0.45f;
        }
        break;
      }

      case EAT:                                            // legs rubbing
        if (--tickLeft <= 0) {
          tickLeft = (int32_t)(uni(0.07f, 0.10f) * SR);
          tickAmp  = 0.5f;
        }
        tickAmp *= expf(-1.0f / (0.0035f * SR));
        tickState = 0.7f * tickState + 0.3f * (uni() * 2.0f - 1.0f);   // shaped noise
        s = tickState * tickAmp * 0.5f;
        break;

      case QUIET:
      default: break;
    }

    s *= env * P.gain;
    if (s >  1.0f) s =  1.0f;
    if (s < -1.0f) s = -1.0f;
    out[k] = (int16_t)(s * 32767.0f);
  }
}

}  // namespace song
