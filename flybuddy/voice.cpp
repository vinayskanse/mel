// Mapping the fly onto its voice.
//
// A real male fruit fly is silent most of the time and then sings for a second
// or two, so most of the moods map to QUIET and the courtship song arrives as
// an occasional bout rather than a constant drone. The rule that matters: the
// sound follows the animal, never the other way round.
#include "voice.h"
#include <Arduino.h>
#include "fly.h"
#include "motion.h"
#include "song.h"

namespace voice {
namespace {

song::Voice cur = song::QUIET;
const char* lastState = "";
float  takeoffLeft = 0.0f;     // seconds of TAKEOFF before it settles to FLIGHT
float  singLeft    = 0.0f;     // seconds left of a courtship bout
float  nextSing    = 6.0f;     // seconds until it feels like singing again

inline float randf(float a, float b) { return a + (b - a) * (random(0, 10001) * 0.0001f); }

// Flying is a state, not a mood: it wins over whatever the face is doing.
song::Voice pick(float dt) {
  const char* st = fly::stateName();
  const bool airborne = (st[0] != 's');          // "fly" or "land", not "sit"

  if (airborne) {
    if (lastState[0] == 's' || lastState[0] == '\0') takeoffLeft = 0.35f;
    if (takeoffLeft > 0.0f) { takeoffLeft -= dt; return song::TAKEOFF; }
    return song::FLIGHT;
  }
  takeoffLeft = 0.0f;

  switch (fly::mood()) {
    case fly::EATING:   return song::EAT;

    // Angry and trying to get out are the only times it comes at you.
    case fly::ANGRY:
    case fly::LETMEOUT: return song::LOOM;

    // Dancing *is* courtship - that is what the song is for - and an excited
    // fly sings too. Both get the real thing, continuously.
    case fly::DANCING:
    case fly::EXCITED:  return song::COURT;

    case fly::SLEEPING:
    case fly::LOWBATT:  return song::QUIET;

    // Idle, happy, curious: quiet, but every so often it strikes up a bout.
    default:
      if (singLeft > 0.0f) { singLeft -= dt; return song::COURT; }
      nextSing -= dt;
      if (nextSing <= 0.0f) {
        singLeft = randf(1.2f, 3.5f);
        nextSing = randf(7.0f, 20.0f);
        return song::COURT;
      }
      return song::QUIET;
  }
}

}  // namespace

void begin() {
  cur = song::QUIET;
  lastState = fly::stateName();
  nextSing = randf(4.0f, 10.0f);
}

void update(float dt) {
  const song::Voice want = pick(dt);
  if (want != cur) { cur = want; song::play(cur); }
  lastState = fly::stateName();

  // The speaker vibrates the accelerometer hard enough to read as a shake
  // (../context/hardware.md). Left alone that closes a loop: the buzz reads as
  // rough handling, rough handling keeps the fly in the air, and the fly in the
  // air keeps the buzz going. So while there is sound, the jolt channel is told
  // to coast. The gravity angle is unaffected - it is DC - which is why turning
  // the board still works normally in flight.
  if (cur != song::QUIET) motion::deafen(120);
}

const char* name() {
  switch (cur) {
    case song::COURT:   return "court";
    case song::FLIGHT:  return "flight";
    case song::TAKEOFF: return "takeoff";
    case song::LOOM:    return "loom";
    case song::EAT:     return "eat";
    default:            return "quiet";
  }
}

}  // namespace voice
