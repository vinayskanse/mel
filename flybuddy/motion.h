// LIS2DH12 (LIS3DH-compatible) at I2C 0x19, running at 400 Hz into its FIFO.
// Everything the fly knows about the world comes from here.
#pragma once
#include <stdint.h>

namespace motion {

bool begin();               // false if the sensor doesn't answer
bool present();
void update();              // call every frame; it rate-limits itself to 50 Hz

// Which way is down, as an angle across the screen. Rotating the fly by this
// makes it stand upright however the board is held.
float uprightAngle();       // radians, continuous, held when the board lies flat
float spin();               // radians/second the board is being turned at
int   orientation();        // 0..3, the nearest quarter turn, with hysteresis
float orientationAngle();   // that quadrant in radians

float jolt();               // 0..1-ish, how roughly the board is being handled

// Our own speaker shakes this sensor (see ../context/hardware.md). While sound
// is playing, jolt() is told to coast rather than believe what it is reading,
// for `ms` from now. The angle is DC and stays trustworthy throughout.
void  deafen(unsigned long ms);
bool  flat();               // lying face up or down: no meaningful rotation
unsigned long stillFor();   // ms since the board last really moved

}  // namespace motion
