// What the fly sounds like, moment to moment.
//
// This watches fly:: and picks a voice for song:: to sing. It deliberately
// only *reads* the fly - state name and mood - so the animal and its voice can
// be worked on independently, and so nothing in fly.cpp has to know that sound
// exists at all.
#pragma once

namespace voice {

void begin();
void update(float dt);      // call once a frame, after fly::update()
const char* name();         // what it is singing, for the serial line

}  // namespace voice
