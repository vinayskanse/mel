#include "buttons.h"
#include <Arduino.h>
#include "board_config.h"

namespace buttons {
namespace {

// A press has to read the same way for this long before it counts. Mechanical
// contacts chatter for a millisecond or two; 25 ms is well past that and still
// far too quick for anyone to notice.
const unsigned long DEBOUNCE_MS = 25;

// Two presses inside this count as one double-click. 400 ms is the usual
// figure and is comfortably longer than the debounce.
const unsigned long DOUBLE_MS = 400;

struct Btn {
  uint8_t pin;
  bool    down;             // the settled state
  bool    edge;             // went down this frame
  bool    dbl;              // and it was the second of a pair
  bool    raw;              // what the pin said last time we looked
  unsigned long since;      // when it last changed
  unsigned long lastPress;  // 0 once a double has been claimed
};

Btn plus{BTN_VOL_UP, false, false, false, false, 0, 0};
Btn minus{BTN_VOL_DOWN, false, false, false, false, 0, 0};

void step(Btn& b, unsigned long now) {
  const bool raw = (digitalRead(b.pin) == LOW);     // active LOW
  b.edge = false;
  b.dbl  = false;
  if (raw != b.raw) { b.raw = raw; b.since = now; return; }
  if (now - b.since < DEBOUNCE_MS) return;
  if (raw != b.down) {
    b.down = raw;
    b.edge = raw;                                   // report the press, not the release
    if (raw) {
      // Claiming the pair clears the timer, so three presses are one double
      // and a single rather than two overlapping doubles.
      b.dbl = (b.lastPress != 0 && now - b.lastPress <= DOUBLE_MS);
      b.lastPress = b.dbl ? 0 : now;
    }
  }
}

}  // namespace

void begin() {
  pinMode(BTN_VOL_UP, INPUT_PULLUP);
  pinMode(BTN_VOL_DOWN, INPUT_PULLUP);
  const unsigned long now = millis();
  plus.since = minus.since = now;
}

void update() {
  const unsigned long now = millis();
  step(plus, now);
  step(minus, now);
}

bool pressedPlus()        { return plus.edge; }
bool pressedMinus()       { return minus.edge; }
bool heldPlus()           { return plus.down; }
bool doublePressedMinus() { return minus.dbl; }

}  // namespace buttons
