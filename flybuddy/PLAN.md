# FlyBuddy — agile plan

One fruit fly living on the Cheeko Gotchi screen (ESP32-S3, JD9853 240x296,
LIS2DH12 at 0x19). Design reference: `../design/image.png`, panel 2 "HAPPY".

**Goal for this round: the face only.** Happy at rest, alive in small ways, and
honestly wired to the accelerometer. No audio, no WiFi, no touch (touch is dead
on this unit — see `../context/touchscreen.md`).

## The idea in one line

The fly sits at the bottom of the screen. Turn the board and it loses its
footing and flies; hold the board still and it snaps back down, lands, and sits
upright again — and in landscape it has more room, so it sits bigger and grins
wider.

## Milestones

### M1 — it draws  ✅
- [x] Band renderer: no full framebuffer, one 16 KB scratch band, dirty-rect blits
- [x] JD9853 driver reworked for band blits (single SPI write per band)
- [x] LIS2DH12 driver, audio dependency removed, exposes angle + spin + shake
- [x] The fly itself: wings, thorax, legs, head, two compound eyes, antennae, smile
- [x] Compiles and runs at the target frame rate

### M2 — it is alive  ✅
- [x] Breathing (slow squash)
- [x] Head tilts and looks around, antennae trail behind with a spring (secondary motion)
- [x] Grooming: front legs come up and rub together, every 7-14 s
- [x] Antenna flick
- [x] Eye highlight slides with the board's tilt — glossy spheres catching the light

### M3 — it answers the accelerometer  ✅
- [x] SIT / FLY / LAND state machine
- [x] Turn the board past ~35 deg, or spin it, or shake it → takeoff
- [x] While flying: wings blur, legs tuck, body banks into the motion, wanders
- [x] Hold it still → lands on the new "down" edge, springs upright with a little
      overshoot, squashes on impact, smiles bigger for a moment
- [x] 180 deg and a full 360 both work because the sit spot is derived from
      gravity, not from a table of cases
- [x] Landscape: bigger fly, wider smile, wings spread

### M4 — smooth and small  ✅
- [x] Dirty rect is the union of last and current bounding box, nothing else redraws
- [x] `fps` line on serial with draw/wait split and free heap
- [x] 11 fps -> 31.5 fps: no square root and no float divide per pixel, and the
      SPI push moved onto the idle core
- [x] `build_opt.h` pins `-O3`; at the Arduino default `-Os` it runs at half speed

**Measured on the board:** 31.5 fps, draw 25.0 ms, panel wait 1.2 ms, static RAM
58 KB (17%), free heap 304,876 B and steady, flash 353 KB (26%). 25 minutes
sitting undisturbed on the desk produced no false takeoffs.

## Later (not this round)
- Moods from the design sheet: excited, eating, sleeping, curious, angry, low battery
- Sound (ES8311), the brain in `../viewer/live_engine.py` driving the mood
- Buttons: `+` GPIO 40, `-` GPIO 39, both active LOW

## Build, flash and preview

See [README.md](README.md). `preview/run.sh` renders the fly on the Mac, which is
how the look was iterated without reflashing.

The board is borrowed: only ever write `0x10000`, never `arduino-cli upload`,
never `erase_flash`, and never drive GPIO 2 (it is the power-off latch).
