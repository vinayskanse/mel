// The line to the laptop: the fly's brain, and its ears, are over there.
//
// Everything this adds to the board is one socket. The board makes no requests,
// polls nothing and holds no address; it joins the WiFi, waits to be told where
// the laptop is, opens one connection and listens. When it is not connected --
// no WiFi, laptop closed, guest network blocking broadcast -- the fly carries
// on exactly as it did before any of this existed, choosing its own moods from
// the accelerometer and its own whim. Nothing here is on the path of a frame.
#pragma once

// `uplink` rather than `link`: POSIX declares a function called link() in
// unistd.h, which every Arduino sketch pulls in, and a namespace cannot share
// the name.
namespace uplink {

void begin();
void update();          // call once a frame; never blocks

bool joined();          // on the WiFi
bool connected();       // and talking to the laptop
const char* status();   // one short word for the serial log

}  // namespace uplink
