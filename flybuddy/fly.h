// The fly. One fruit fly that sits on the screen, keeps itself busy, has
// moods about it, and takes off when the board is turned.
#pragma once
#include "gfx.h"

namespace fly {

// The ten faces on the design sheet. The same fly in all of them: only the
// mouth, the antennae, the wings, where the body sits and a small symbol
// change, which is what makes them cheap.
enum Mood {
  IDLE, HAPPY, EXCITED, EATING, SLEEPING,
  DANCING, CURIOUS, ANGRY, LETMEOUT, LOWBATT,
  MOOD_N
};

void begin();
void update(float dt);                       // reads motion:: itself
void draw(gfx::Band& b);                     // called once per band
void bbox(int& x0, int& y0, int& x1, int& y1);   // what it covers this frame
const char* stateName();

// Left alone it picks its own mood from what the board is doing and from whim.
// `setMood` overrides that, including in flight: `holdSec` is how long to keep
// it, and 0 holds it until something asks otherwise. `autoMood` hands the
// choice back.
void setMood(Mood m, float holdSec = 0.0f);
void autoMood();

// Put a crumb down. It eats it as soon as it is on the ground - offer food to
// a fly in the air and it finishes its flight first - and is pleased with
// itself afterwards. Feeding it again while it is still eating tops the crumb
// back up. The offer goes stale after a few seconds if it never lands.
void feed();
bool eating();
Mood mood();
const char* moodName();

}  // namespace fly
