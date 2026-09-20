# Fly learning service

The fly listens to whatever is playing, guesses what it is, and shows the
answer in a bubble as though it had said it. When it does not know, it asks
Shazam once, writes the answer down, and does not ask again.

This package owns that: the listening, the guessing, the asking and the
remembering. It is separate from the connectome simulator so learning can be
tested without loading the brain and the simulator can stay reproducible.

## How it decides

```
 4 s of sound
     |
     v
 landmarks  ---->  memory: do I know this?  --- yes --->  "that's Perfect"
                            |                                 (free, instant)
                            no
                            |
                            v
                      Shazam, once  ----- named ----->  "ooh! Perfect"
                            |                          and written down
                         nameless
                            |
                            v
                  remembered anyway, so the next
                  hearing is at least recognised
                  as the same unknown thing
```

The order is the point. Memory is free and instant, so it goes first; Shazam
costs a call, so it only sees what memory could not place. A song is paid for
once in its life, however often it is played.

Nothing is spoken. The fly's voice is `song.cpp` - wingbeats and the pulse
train of a real *D. melanogaster* courtship song - and interrupting that with a
synthesised English sentence would be a shame. The name is *shown*, in a band
under the face, the way a comic panel puts words on an animal that has never
spoken in its life. The speaker keeps buzzing throughout.

## Why it gets better

Two different things improve, and they are not the same thing.

**Being told the name** happens once. A tune nobody could name is still
remembered, under a placeholder key, and asked about a few more times; when a
name finally arrives it is attached to the tune already known, rather than
starting a second record of it.

**Recognising it** improves every time. Each hearing's landmarks are folded
into the song's, shifted by the offset that matching worked out, so all the
hearings share one timeline. A song first met through its chorus is eventually
known by its intro and its last thirty seconds too. It is why the fly answers
faster and more often the longer you have had it.

## Recognising a song again

A fingerprint here is not a checksum. Two recordings of the same song, taken
from different points, through a mic, in a room, share almost no samples. What
they share is the pattern of loud spots in the spectrogram and the distances
between them, which survive volume, noise and a small speaker.

So a clip becomes a list of `(hash, time)` pairs, each hash packing two peak
frequencies and the gap between them. Matching is a histogram of time offsets
between the clip's hashes and a remembered song's: coincidence scatters, a real
match stacks up at one offset, and the score is the tallest bar.

Measured on four unrelated real recordings - music, a fruit fly courtship
recording, speech and a farm ambience - across 64 four-second clips at a range
of volumes and noise levels:

| | |
|---|---|
| Right source scored | 14 to 277 |
| Best *wrong* source ever scored | 3 |
| Clip of pure noise | 0 against everything |
| Decisions | 64 right, 0 wrong |

`MIN_SCORE = 8`, and twice the runner-up, sits in that gap with room on both
sides. Being unsure costs one Shazam call; being wrong puts a confident lie on
the fly's face, so the rule leans towards unsure.

Fingerprinting a four-second clip takes 0.09 s in pure Python - no numpy, no
build toolchain - which is what makes it reasonable to check memory before
reaching for the network every time.

## Listening is armed by a button

Following the deskbuddy firmware: **a click on `+` turns the ears on, a double
click means "name this one now"**.

That is deliberate rather than lazy. The energy gate in `audio.py` tells music
from an empty room perfectly well, measured through this Mac's own mic:

| | share of blocks loud |
|---|---|
| Quiet room | 2% |
| Farm ambience | 38% |
| Music | 78% |
| Music at 1/4 volume | 44% |
| A produced voiceover | 74-94% |

What it cannot do is tell music from *continuous* speech - the voiceover above
is steadier than the music - and nothing cheap can. The deskbuddy's own
continuity test works on live talking, which drops back to the room between
words; a broadcast voiceover never does. So the gate is only used to pace the
asking. What the fly is being asked to do is settled by the button.

## Running it

Against a file, with no board and no room:

```sh
python -m learning.ears --file song.mp3
python -m learning.ears --mic            # the Mac's own microphone
python -m learning.ears --file song.mp3 --offline   # guess only, never ask
```

As a service:

```sh
python -m learning.service
```

HTTP on `FLY_PORT` (8020), for anything on the desk:

| | |
|---|---|
| `POST /listen` `{"arm": true}` | a click on `+`: ears on, or off |
| `POST /identify` | a double click: name it now |
| `POST /clip` | raw mono PCM16 at 16 kHz in the body |
| `POST /hear` | `{"fingerprint": "song-1"}`, the older string path |
| `POST /reward` | `{"fingerprint": .., "kind": "sugar"\|"bitter"}` |
| `GET /memories`, `GET /health` | what it knows, and whether it is listening |

Plain TCP on `FLY_PORT + 1` is for the board, and speaks the deskbuddy's song
protocol so the firmware is a port rather than a rewrite:

```
board -> host   1 = audio chunk (16 kHz mono PCM16), 2 = end
host  -> board  1 = four lines - mood, what to show, title, artist -
                    or empty when there is nothing to say
```

The fourth line is the only change. The deskbuddy sent `title\nartist`; the fly
also needs to know which face to pull while the bubble is up, and that is
cheaper to send than to work out twice.

`SHAZAM_API_KEY` comes from the repository's `.env` (RapidAPI's Shazam API),
the same key and the same endpoint the deskbuddy server uses. Without it the
fly still listens and still guesses from memory - it just cannot learn anything
new. Memories live in `learning/data/memories.json` (`FLY_MEMORY`), written
atomically, and are not committed.

## The files

| File | |
|---|---|
| `fingerprint.py` | spectrogram, landmarks, hashing, offset matching. Pure stdlib, including the FFT |
| `memory.py` | what the fly knows and the landmark index, in one JSON file |
| `audio.py` | PCM conversions, resampling, capture through ffmpeg, the music gate |
| `providers.py` | Shazam, and the stand-ins used by the tests |
| `says.py` | what the bubble shows, and which face goes with it |
| `ears.py` | the loop: guess, ask, remember, and how often to bother |
| `service.py` | HTTP for the desk, the board's own TCP port |
| `events.py` | the notice board: how one decision reaches the brain and the face |

```sh
python -m unittest discover -s learning -p 'test_*.py'
```

## Where this ends up

Nothing here is a demo on its own. `visualization/sim_server.py` runs this
package in its own process and subscribes to `events.py`, so every decision
above lands in two more places at once - see
[`../visualization/README.md`](../visualization/README.md) for the table:

- **The connectome.** Hearing something drives the fly's auditory neurons, and
  agreeing with its guess drives the 17 sugar receptor neurons of the right
  labellum, through 24.5M synapses, to the motor neuron that extends the
  proboscis. A thumbs-up is a real sweet reward, not a flag in a JSON file.
- **The board.** The bubble this package writes is drawn under the fly's face
  on the desk, and the face changes with it: dancing for a song it knows,
  excited for one it has just been told, curious for one nobody can name.

`events.py` is how, and it is a notice board with no sockets in it: publishing
is a function call, so none of this added a network round trip and a song still
costs at most one Shazam lookup in its life.

## Not done yet

The mic. The board has one - ES7210 at I2C 0x40, the same part the deskbuddy
records through - but `flybuddy/` is playback-only, so the ear in the loop
today is the laptop's. The TCP port above already speaks the deskbuddy's song
protocol for it; what is missing is `mic.cpp` ported over, a `music_id.cpp`
pointed at port 8021, and `doublePressedPlus()` alongside the existing
`doublePressedMinus()` in `buttons.cpp`. The bubble under the face is done
(`flybuddy/bubble.cpp`).

One thing is unverified: no commercially released music was available on this
machine, so while the Shazam round trip is confirmed working - it accepts the
audio, assigns a tag and answers cleanly - a *positive* identification has not
been seen end to end. The parsing follows the deskbuddy server, which has been
answering with it for a while. Worth playing something well known at it first
thing on flashing day.
