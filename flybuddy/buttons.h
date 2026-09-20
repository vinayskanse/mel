// The two side buttons, debounced down to edges.
//
// `+` (GPIO 40) and `-` (GPIO 39), both active LOW with the internal pull-up
// holding them high at rest. The middle key (GPIO 3) is left alone: it is the
// power key and the board does its own thing with it.
#pragma once

namespace buttons {

void begin();
void update();              // call once a frame

bool pressedPlus();         // true for the one frame the button goes down
bool pressedMinus();
bool heldPlus();            // still down, for anything that wants to repeat

// True on the frame the second press of a double-click lands. The two presses
// also each raise pressedMinus(), so don't wire both to the same thing.
bool doublePressedMinus();

}  // namespace buttons
