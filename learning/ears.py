"""Listening for music, guessing first, and only then asking.

The order matters and is the whole design. Memory is consulted first because
it is free and instant; Shazam is asked only for what memory could not place,
and whatever it answers is written down so that clip is never paid for twice.
A song therefore costs one call in its life, no matter how often it is played.

Listening is armed by a button rather than guessed at, the way the deskbuddy
firmware does it: a click turns the ears on, a double click means "name this
one now". That is deliberate. A three-second energy test tells music from an
empty room, but it cannot reliably tell music from continuous speech - a
produced voiceover is steadier than most songs - so the gate here only paces
the asking. What the fly is being asked to do is settled by the button.

Run it against a file, with no board and no room:

    python -m learning.ears --file song.mp3
    python -m learning.ears --mic
"""

from __future__ import annotations

import argparse
import os
import random
import sys
import time
from dataclasses import dataclass, field
from pathlib import Path

from . import audio, says
from . import fingerprint as fpmod
from .memory import LearningMemory, slug
from .models import Recognition
from .providers import DeafTeacher, ShazamTeacher, Song, SongTeacher
from .says import Utterance

# How long a clip to hand over. Four seconds is what the deskbuddy sends and
# what Shazam is happy with, and it is about 300 landmark pairs for memory.
CLIP_SECONDS = 4.0

# Pacing, in seconds, following music_id.cpp. Once a song is named there is no
# reason to look again until it could plausibly have changed; when nobody could
# name it, try a different part of it a few times and then let it go.
AGAIN = 120.0
RETRY = 20.0
RETRIES = 3
FORGET = 8.0        # this long without music and the fly drops the title


@dataclass(frozen=True)
class Answer:
    """One decision about one clip."""

    mode: str                  # guess | taught | stumped | quiet
    utterance: Utterance
    answer: Recognition | None = None
    score: int = 0
    asked: bool = False        # whether this cost a teacher call

    def as_dict(self) -> dict:
        return {"mode": self.mode,
                "say": self.utterance.as_dict(),
                "answer": self.answer.as_dict() if self.answer else None,
                "score": self.score,
                "asked": self.asked}


@dataclass
class Ears:
    """The fly's listening, guessing and remembering, without any I/O."""

    memory: LearningMemory
    teacher: SongTeacher
    gate: audio.MusicGate = field(default_factory=audio.MusicGate)
    armed: bool = False
    rng: random.Random | None = None

    _buffer: bytearray = field(default_factory=bytearray)
    _next_ask: float = 0.0
    _retries: int = 0
    _quiet_since: float = 0.0
    _now: bool = False

    # ---- what the buttons do ----------------------------------------------

    def arm(self, on: bool = True) -> Utterance:
        """A click on `+`: ears on, or off again."""
        self.armed = on
        if not on:
            self.gate.forget()
            self._buffer.clear()
        return says.listening(self.rng) if on else says.quiet(self.rng)

    def ask_now(self) -> None:
        """A double click on `+`: name this one, without waiting for the gate."""
        self.armed = True
        self._now = True
        self._next_ask = 0.0
        self._retries = 0

    # ---- the decision ------------------------------------------------------

    def hear(self, pcm: bytes, rate: int = audio.BOARD_RATE) -> Answer:
        """Guess at a clip, ask about it if the guess fails, and remember.

        Four things can happen, and only one of them costs anything:
          - memory knows it by name              -> a guess, free
          - memory has heard it but never got a name -> ask again, if it is
            still worth asking
          - memory has never heard it            -> ask, and write down whatever
            comes back, name or no name
          - nobody can name it                   -> remember the tune anyway, so
            the next hearing is at least recognised as the same unknown thing
        """
        clip = fpmod.of(audio.for_fingerprint(pcm, rate))
        known = self.memory.recall(clip)

        if known is not None and known.named:
            return Answer("guess", says.recalled(known, self.rng), known, known.score)

        if known is not None:
            # Heard before, still nameless. Worth another try on a fresh part
            # of it, but not forever.
            if self.memory.asked(known.fingerprint) >= RETRIES:
                return Answer("stumped", says.recalled(known, self.rng), known, known.score)
            song = self._ask(pcm, rate, known.fingerprint)
            if song is None:
                return Answer("stumped", says.recalled(known, self.rng),
                              known, known.score, asked=True)
            named = self.memory.rename(known.fingerprint, song.title, song.artist)
            return Answer("taught", says.learned(named, self.rng), named,
                          known.score, asked=True)

        # Never heard. Ask, then write down whatever came back.
        song = self._ask(pcm, rate, None)
        if song is not None:
            key = slug(song.title, song.artist)
            learned = self.memory.learn(key, clip, song.title, song.artist, "shazam")
            return Answer("taught", says.learned(learned, self.rng), learned, asked=True)

        key = self.memory.next_tune_key()
        remembered = self.memory.learn(key, clip, source="local")
        self.memory.note_ask(key)
        return Answer("stumped", says.stumped(self.rng), remembered, asked=True)

    def _ask(self, pcm: bytes, rate: int, key: str | None) -> Song | None:
        if key is not None:
            self.memory.note_ask(key)
        return self.teacher.identify(pcm, rate)

    # ---- the loop ----------------------------------------------------------

    def feed(self, pcm: bytes, now: float | None = None) -> Answer | None:
        """Take some audio; returns an answer on the clips it decides to judge.

        The fly keeps the last few seconds to hand at all times, so when it does
        decide to look it already has the clip and does not have to start
        recording and wait.
        """
        now = time.monotonic() if now is None else now
        want = int(audio.BOARD_RATE * CLIP_SECONDS) * 2
        self._buffer += pcm
        if len(self._buffer) > want:
            del self._buffer[:len(self._buffer) - want]

        playing = self.gate.feed(audio.to_samples(pcm))
        if not self.armed:
            return None

        if not playing and not self._now:
            if not self._quiet_since:
                self._quiet_since = now
            elif now - self._quiet_since > FORGET:
                self._next_ask = 0.0
                self._retries = 0
            return None
        self._quiet_since = 0.0

        if now < self._next_ask or len(self._buffer) < want:
            return None

        self._now = False
        answer = self.hear(bytes(self._buffer))
        if answer.mode == "taught" or answer.mode == "guess":
            self._retries = 0
            self._next_ask = now + AGAIN
        else:
            self._retries += 1
            self._next_ask = now + (RETRY if self._retries < RETRIES else AGAIN)
        return answer

    def run(self, source: audio.Source, on_say=None, seconds: float | None = None) -> None:
        """Listen to a source until it runs out, or for this long."""
        started = time.monotonic()
        chunk = 2048            # samples: about an eighth of a second
        while True:
            pcm = source.read(chunk)
            if not pcm:
                break
            answer = self.feed(pcm)
            if answer is not None and on_say is not None:
                on_say(answer)
            if seconds is not None and time.monotonic() - started > seconds:
                break


def show(answer: Answer) -> None:
    """Print a decision the way the band under the fly's face would show it."""
    say = answer.utterance
    cost = " (asked Shazam)" if answer.asked else ""
    print(f'  [{say.mood:<8}] "{says.fit(say.text)}"'
          + (f"  / {say.artist}" if say.artist else "")
          + (f"  score {answer.score}" if answer.score else "") + cost)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Listen for music and name it.")
    source = parser.add_mutually_exclusive_group(required=True)
    source.add_argument("--mic", nargs="?", const=":0", metavar="DEVICE",
                        help='microphone, default ":0"')
    source.add_argument("--file", metavar="PATH", help="a file, played in real time")
    parser.add_argument("--memory", default=os.environ.get(
        "FLY_MEMORY", "learning/data/memories.json"))
    parser.add_argument("--seconds", type=float, default=None)
    parser.add_argument("--now", action="store_true",
                        help="a double click: name it straight away")
    parser.add_argument("--offline", action="store_true",
                        help="never ask Shazam, guess from memory only")
    args = parser.parse_args(argv)

    if not audio.have_ffmpeg():
        print("ffmpeg is needed to capture audio: brew install ffmpeg")
        return 1

    memory = LearningMemory(Path(args.memory))
    teacher: SongTeacher
    if args.offline:
        teacher = DeafTeacher()
    else:
        teacher = ShazamTeacher.from_env()
        if not teacher.ready:
            print("no SHAZAM_API_KEY in .env: the fly can only guess")

    ears = Ears(memory, teacher)
    ears.arm(True)
    if args.now:
        ears.ask_now()

    source_stream = (audio.microphone(args.mic) if args.mic
                     else audio.from_file(args.file))
    print(f"listening to {source_stream.label}; {len(memory)} songs remembered")
    try:
        ears.run(source_stream, on_say=show, seconds=args.seconds)
    except KeyboardInterrupt:
        pass
    finally:
        source_stream.close()
    print(f"{len(memory)} songs remembered")
    return 0


if __name__ == "__main__":
    sys.exit(main())
