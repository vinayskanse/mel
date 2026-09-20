# FlyBuddy

One happy fruit fly living on the Cheeko Gotchi board (ESP32-S3, JD9853
240x296, LIS2DH12). The look is taken from
[`../design/reference.png`](../design/reference.png); the behaviour sheet is
[`../design/image.png`](../design/image.png), panel 2, "HAPPY".

Tall vermilion ovals for eyes, a light peach face plate that domes into a
forehead above them and a chin below, wide pale wings, and a warm halo hugging
the silhouette.

This round is the face only, wired honestly to the accelerometer. No audio, no
WiFi, no touch — touch does not work on this unit
([`../context/touchscreen.md`](../context/touchscreen.md)).

## What it does

It sits at the bottom of the screen and keeps itself busy: it breathes, turns
its head, lets its antennae trail behind the turn and settle after it, flicks
them, shuffles, and every eight seconds or so brings its front legs up to its
mouth and rubs them together. Tilt the board a little and it leans with you,
and the highlight slides across its eyes as if a real light were overhead.

Turn the board past about 35 degrees, spin it, or shake it, and it loses its
footing and flies: wings blur, legs tuck up, body banks into the motion. Hold
the board still and about a third of a second later it comes down, lands on
whichever edge is now the floor, and springs upright with a little overshoot —
the snap. It squashes on impact and grins wider for a second afterwards.

In landscape it has more room, so it sprawls: it drops its antennae, spreads
its wings and legs, sits about 12% bigger, and smiles wider.

Nothing is special-cased per orientation. Where the floor is, which way is up
and how big it can be are all worked out from the gravity vector, which is why
180 degrees and a full 360 need no code of their own. Through a full turn it
simply stays airborne until you stop.

## How it draws

There is no framebuffer. A full 240x296 canvas would be 142 KB; this draws into
one 15 KB band at a time and pushes each band out as it is finished.

The shapes are analytic rather than bitmaps. A rotated ellipse solves the conic
for its own span on each row, so the loop only ever visits pixels it is about to
touch, and every edge is antialiased from the real distance to the curve. That
is what keeps the fly smooth at any angle and any size without a single rotated
sprite in memory — and it is why turning the board is free.

Only the rectangle the fly covered last frame or covers this frame is redrawn.
The rest of the screen is already black.

| | |
|---|---|
| Frame rate | 30.0 fps, measured on the board |
| Draw | 27.0 ms/frame |
| Waiting on the panel | 0.8 ms/frame — the SPI push runs on the other core |
| Static RAM | 58.5 KB (17%), of which 30 KB is the two bands |
| Free heap | 304,804 B, and it does not move |
| Flash | 356 KB (27%) |

Three things got it from 11 fps to 30, with room to spare:

1. **No square root per pixel.** The shaders take q *squared*. Nothing needed q
   itself — the rim term is q⁴ and the sphere normal wants 1−q², and near the
   edge, the only place it matters, q−1 is (q²−1)/2 to well under a pixel. The
   one root that remains is a 512-entry table.
2. **No float divide per pixel.** The stroke code was dividing by the segment
   length for every pixel; that only depends on the segment. The facet crowding
   divide became a linear approximation.
3. **The SPI push runs on core 0** while core 1 draws the next band. It is not
   DMA — the CPU feeds the SPI FIFO — so it really does cost a core, which is
   exactly why it is worth giving it the idle one.

The halo is a fourth: it is drawn straight onto the band with a lookup and a
compare rather than a per-pixel alpha blend, and it keeps whichever of itself
and what is already there is brighter, so the three halos merge and the wings
still show through. It cost 2 ms and 72 bytes.

`build_opt.h` forces `-O3` for the sketch. At the Arduino default of `-Os` this
runs at about half the speed, so don't remove it.

## Looking at it without a board

[`preview/`](preview/) builds the renderer and the fly on the Mac against a stub
accelerometer and writes PNGs. This is how the fly was drawn: it caught the
green cast on the wings (RGB565 truncation at low alpha keeping only the 6-bit
green channel), the smile being crammed between the eyes, the facets reading as
a golf ball rather than a compound eye, and contour rings across the wings where
RGB565 quantised a smooth alpha ramp into about ten steps — none of which needed
a reflash.

```sh
preview/run.sh        # writes poses.png, idle.png, face.png
```

`spin` in the same folder walks the board through a quarter, a half and a full
turn and prints the state changes.

## Build and flash

```sh
arduino-cli compile \
  --fqbn esp32:esp32:esp32s3:USBMode=hwcdc,CDCOnBoot=cdc,FlashMode=dio,FlashSize=16M,PSRAM=disabled \
  --output-dir flybuddy/build flybuddy

python -m esptool --port /dev/cu.usbmodem2101 write_flash 0x10000 flybuddy/build/flybuddy.ino.bin
```

> **The board is borrowed.** Only ever write `0x10000`, the app partition. Never
> use `arduino-cli upload` — it rewrites the bootloader and partition table.
> Never run `erase_flash`. Never drive GPIO 2: it is the power-off latch and
> driving it HIGH cuts power.

Serial at 115200 prints one line every two seconds: frame rate, where the time
goes, what the fly is doing, and the free heap.

## The files

| File | |
|---|---|
| `flybuddy.ino` | frame loop, the band pipeline, the sender task |
| `fly.cpp` | the whole animal: proportions, springs, idle behaviour, the sit/fly/land machine |
| `gfx.h` / `gfx.cpp` | the band canvas, antialiased rotated ellipses, strokes, shading |
| `lcd.cpp` | JD9853, from the deskbuddy firmware, reworked for band blits |
| `motion.cpp` | LIS2DH12, from the deskbuddy firmware, audio coupling removed |
| `board_config.h` | pins, all verified — see [`../context/hardware.md`](../context/hardware.md) |

`lcd.cpp` and `motion.cpp` came from the deskbuddy firmware, which lives outside
this repo at `~/Documents/test_jovian_device/deskbuddy` (its `venv` is also where
`esptool` is installed). The JD9853 init table in particular was extracted from
the factory firmware and is not worth rediscovering. That project also has
working ES8311 audio, ES7210 mic and battery code to lift when the time comes.
The renderer and the fly are new.

## Next

The other nine faces on the design sheet — excited, eating, sleeping, curious,
angry, low battery — then sound through the ES8311, and the buttons
(`+` GPIO 40, `-` GPIO 39, both active LOW). See [`PLAN.md`](PLAN.md).
