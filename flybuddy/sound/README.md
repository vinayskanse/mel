# The fly's voice

A synthesiser, not a sample bank. Every sound is built from one 257-entry sine
table and a handful of oscillators, so the whole repertoire costs **2.9 KB of
flash, 1.2 KB of RAM and about 1 % of one core** at 16 kHz — against the 353 KB
and 25 ms/frame the renderer already spends.

The parameters are measured from a real recording of a male *D. melanogaster*
courting a female. The measurements, and how to redo them, are in
[`../../research/song/README.md`](../../research/song/README.md).

## Why synthesise rather than play the clip

| | a stored sample | this |
|---|---|---|
| flash | 10.9 s at 16 kHz mono = **349 KB** | **2.9 KB** |
| length | always the same 10.9 s | never repeats |
| reacting to the fly | cross-fade between clips | the sound *is* the state |
| pitch for the speaker | resample offline, lose quality | one constant |

The last row is the real argument. The fly on screen already banks, tucks its
legs and snaps back down; a recording cannot rise in pitch as it takes off or
swell as it looms, and a synthesiser gets that for free.

## The voices

| voice | what it is | built from |
|---|---|---|
| `COURT` | the courtship song — pulse trains and sine song alternating in bouts | damped-sine clicks every 34 ms; a 145 Hz hum |
| `FLIGHT` | steady wingbeat buzz | 200 Hz + 3 harmonics, with wing jitter |
| `TAKEOFF` | a burst of clicks, then the buzz | both of the above |
| `LOOM` | a buzz that rises 175→255 Hz and swells ×9 | `FLIGHT` with ramps |
| `EAT` | legs rubbing at the mouth | shaped noise ticks every 70–100 ms |

Voice changes cross-fade through zero over 4 ms, so switching never clicks.

## Listening to it without a board

```sh
./run.sh
```

Writes `c_*_raw.wav` (the true fly — 145/215 Hz, for headphones) and `c_*.wav`
(pitch ×3, what the board's speaker can actually reproduce), then benchmarks.

`c_court_raw.wav` measures against the original recording like this:

| | recording | engine |
|---|---|---|
| pulse carrier | 188 Hz | 199 Hz |
| sine carrier | 145 Hz | 146 Hz |
| inter-pulse interval | 33.9 ms | 35.6 ms |
| IPI spread (sd) | 8.3 ms | 7.8 ms |
| energy 100–200 Hz | 72.8 % | 77.2 % |
| energy 200–400 Hz | 22.0 % | 16.9 % |

(`python ../../research/song/compare.py` reproduces that table.)

## How it is wired in

Done, and it compiles; **not flashed**. The chain is:

```
fly.cpp  --(state, mood)-->  voice.cpp  --(Voice)-->  song.cpp  --(PCM)-->  audio.cpp --> ES8311 --> amp
   |                             |                        |                     |
 owns the animal          owns the policy          owns the sound        owns the codec
```

`voice.cpp` only ever *reads* `fly::stateName()` and `fly::mood()`. Nothing in
`fly.cpp` knows that sound exists, so the animal and its voice can be worked on
independently — and the fly's own file never had to be touched.

| fly is | voice |
|---|---|
| `fly` / `land` (airborne) | `TAKEOFF` for 0.35 s, then `FLIGHT` |
| sitting, mood `EATING` | `EAT` |
| sitting, mood `DANCING` or `EXCITED` | `COURT` — dancing *is* courtship |
| sitting, mood `ANGRY` or `LETMEOUT` | `LOOM` |
| sitting, mood `SLEEPING` or `LOWBATT` | `QUIET` |
| sitting, otherwise | `QUIET`, striking up a 1.2–3.5 s bout every 7–20 s |

A real male is silent most of the time and then sings for a second or two, which
is why most moods map to `QUIET` and the courtship song arrives as an occasional
bout rather than a drone.

`audio.cpp` runs one task on core 0, next to the SPI sender. It blocks inside
`i2s_channel_write`, which is what paces it: it wakes every 8 ms, renders 128
samples and goes back to sleep. The amp is powered only while there is something
to hear (plus a 100 ms tail), because the board hisses with it enabled and idle.

### What it cost

Measured by building the same tree with and without the audio files:

| | without | with | delta |
|---|---|---|---|
| flash | 367,658 B | 386,738 B | **+18.6 KB** (mostly the ESP-IDF I2S driver) |
| static RAM | 59,128 B | 61,120 B | **+1.9 KB** |

Against 349 KB for storing the clip. The audio task also takes a 3 KB stack from
the heap.

### The one change to a file that already existed

`motion.cpp` gained `deafen(ms)`. The speaker vibrates the accelerometer hard
enough to read as a shake (`../../context/hardware.md`), and left alone that
closes a loop: the buzz reads as rough handling, rough handling keeps the fly in
the air, and the fly in the air keeps the buzz going. So while there is sound,
the jolt channel coasts instead of believing what it reads. The gravity angle is
DC and stays trustworthy, which is why turning the board still works in flight.

## Two things to measure on the hardware first

- **The speaker's real roll-off.** `P.pitch = 3.0` is set from a *model* of a
  micro-speaker, not from this one. MIC3 on the ES7210 is a speaker loopback:
  play a slow sweep, record MIC3, and the response falls out. Then set `pitch`
  from data. This is the single highest-value measurement here.
- **Whether `deafen()` is enough, or too much.** It is in and it compiles, but
  the coupling strength is unmeasured. Two things to watch on the board: that
  the fly still comes down while the buzz is playing (the loop is broken), and
  that shaking it still throws it into the air (we have not deafened so hard
  that it stops listening). `FRAME_MS` pacing and the reported fps should also
  be unchanged — the audio task is on core 0 with the SPI sender.

## The files

| | |
|---|---|
| `../song.h` | the voices and the tunable `Params` |
| `../song.cpp` | the whole synthesiser — no ESP dependencies, pure C++ |
| `test_main.cpp` | renders each voice to a `.wav` |
| `../audio.cpp` | ES8311 + I2S + the amp, from deskbuddy |
| `../voice.cpp` | the fly-to-voice mapping above |
| `bench.cpp` | ns per sample per voice |
