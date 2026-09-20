#include "motion.h"
#include <Arduino.h>
#include <Wire.h>
#include <math.h>
#include "board_config.h"

namespace motion {
namespace {

const uint8_t ADDR = 0x19;
const uint8_t REG_WHOAMI = 0x0F, REG_CTRL1 = 0x20, REG_CTRL4 = 0x23, REG_CTRL5 = 0x24;
const uint8_t REG_OUT = 0x28, REG_FIFO_CTRL = 0x2E, REG_FIFO_SRC = 0x2F;

bool ok = false;
float ax = 0, ay = 0, az = 1;      // g, smoothed
float shakeLevel = 0;
float upright = 0;                 // last trustworthy gravity angle, unwrapped
float spinRate = 0;                // rad/s, smoothed
int   quadrant = 0;
unsigned long lastRead = 0, lastMove = 0;
unsigned long deafUntil = 0;    // our own speaker is shaking us; don't believe jolt()

void writeReg(uint8_t reg, uint8_t val) {
  Wire.beginTransmission(ADDR);
  Wire.write(reg);
  Wire.write(val);
  Wire.endTransmission();
}

int readReg(uint8_t reg) {
  Wire.beginTransmission(ADDR);
  Wire.write(reg);
  if (Wire.endTransmission(false) != 0) return -1;
  if (Wire.requestFrom(ADDR, (uint8_t)1) != 1) return -1;
  return Wire.read();
}

inline float wrapPi(float a) {
  while (a > (float)PI) a -= (float)TWO_PI;
  while (a < -(float)PI) a += (float)TWO_PI;
  return a;
}

}  // namespace

bool begin() {
  Wire.begin(I2C_SDA, I2C_SCL, 400000);
  if (readReg(REG_WHOAMI) != 0x33) return false;
  writeReg(REG_CTRL1, 0x77);       // 400 Hz, all axes
  writeReg(REG_CTRL4, 0x08);       // +/-2 g, high resolution
  writeReg(REG_CTRL5, 0x40);       // FIFO on
  writeReg(REG_FIFO_CTRL, 0x80);   // stream: always the latest 32 samples
  ok = true;
  lastMove = millis();
  return true;
}

bool present() { return ok; }

void update() {
  if (!ok) return;
  unsigned long now = millis();
  unsigned long dtMs = now - lastRead;
  if (dtMs < 20) return;
  lastRead = now;
  float dt = dtMs * 0.001f;

  // Drain everything the FIFO collected since last time (~8 samples at 400 Hz).
  int fsrc = readReg(REG_FIFO_SRC);
  if (fsrc < 0) return;
  int count = (fsrc & 0x40) ? 32 : (fsrc & 0x1F);
  if (count == 0) return;
  float nx = ax, ny = ay, nz = az;
  while (count > 0) {
    int n = min(count, 16);                 // 96 bytes fits the I2C buffer
    Wire.beginTransmission(ADDR);
    Wire.write(REG_OUT | 0x80);             // auto-increment; reading OUT pops the FIFO
    if (Wire.endTransmission(false) != 0) return;
    if (Wire.requestFrom(ADDR, (uint8_t)(n * 6)) != n * 6) return;
    for (int i = 0; i < n; i++) {
      int16_t raw[3];
      for (int a = 0; a < 3; a++) {
        uint8_t lo = Wire.read(), hi = Wire.read();
        raw[a] = (int16_t)((hi << 8) | lo) >> 4;   // 12-bit, left justified, 1 mg/digit
      }
      nx = raw[0] * 0.001f; ny = raw[1] * 0.001f; nz = raw[2] * 0.001f;
    }
    count -= n;
  }

  float dx = nx - ax, dy = ny - ay, dz = nz - az;
  float j = sqrtf(dx * dx + dy * dy + dz * dz);
  if (now < deafUntil) shakeLevel *= 0.80f;      // coast: the noise is our own
  else                 shakeLevel = shakeLevel * 0.80f + j * 0.20f;

  ax = ax * 0.72f + nx * 0.28f;
  ay = ay * 0.72f + ny * 0.28f;
  az = az * 0.72f + nz * 0.28f;

  // Only trust the angle when gravity actually lies across the screen. Flat on
  // a desk there is no meaningful rotation, so the last one is kept and the fly
  // simply stays where it was sitting.
  float sideways = sqrtf(ax * ax + ay * ay);
  if (sideways > 0.30f) {
    float raw = atan2f(ax, -ay);
    float step = wrapPi(raw - upright);        // unwrapped: survives the +/-pi seam
    upright += step;
    float rate = step / dt;
    spinRate = spinRate * 0.70f + rate * 0.30f;
  } else {
    spinRate *= 0.80f;
  }

  if (sideways > 0.45f) {
    float offBy = wrapPi(upright - quadrant * (float)HALF_PI);
    if (fabsf(offBy) > 1.00f) {                // ~57 degrees of hysteresis
      quadrant = ((int)lroundf(upright / (float)HALF_PI)) & 3;
    }
  }

  if ((now >= deafUntil && shakeLevel > 0.12f) || fabsf(spinRate) > 0.5f) lastMove = now;
}

void  deafen(unsigned long ms) { unsigned long t = millis() + ms; if (t > deafUntil) deafUntil = t; }
float uprightAngle() { return upright; }
float spin() { return spinRate; }
int   orientation() { return quadrant; }
// The snapped angle, expressed in the same winding as uprightAngle() so that
// springing from one to the other never takes the long way round after the
// board has been turned through a full circle.
float orientationAngle() {
  return upright + wrapPi(quadrant * (float)HALF_PI - upright);
}
float jolt() { return shakeLevel; }
bool  flat() { return sqrtf(ax * ax + ay * ay) < 0.30f; }
unsigned long stillFor() { return millis() - lastMove; }

}  // namespace motion
