"""What the fly appears to say about a song.

Nothing here reaches the speaker. The fly's voice is song.cpp - wingbeats,
pulse trains, the courtship song of a real D. melanogaster - and it would be a
shame to interrupt that with a synthesised English sentence. So the fly does
not say the name of the song. It shows it, in a bubble, the way a comic panel
puts words on an animal that has never spoken in its life. The speaker keeps
buzzing throughout.

That conceit is also why the lines are short and plain. They are drawn in
FreeSans9pt7b into a 240-pixel band under the face, in a font with no accents,
so anything long or non-ASCII is cut off rather than wrapped.
"""

from __future__ import annotations

import random
from dataclasses import dataclass

from .models import Recognition

# The faces the fly can pull, from fly.h. The bubble picks one to go with it,
# so the whole animal reacts rather than just the text changing underneath it.
DANCING = "DANCING"
EXCITED = "EXCITED"
HAPPY = "HAPPY"
CURIOUS = "CURIOUS"
IDLE = "IDLE"

# Roughly what fits the band at 9pt before music_id-style fitting truncates it.
WIDTH = 30


@dataclass(frozen=True)
class Utterance:
    """One thing the fly appears to say, and the face it makes saying it."""

    text: str
    mood: str = IDLE
    title: str = ""
    artist: str = ""

    def as_dict(self) -> dict[str, str]:
        return {"text": self.text, "mood": self.mood,
                "title": self.title, "artist": self.artist}


def _pick(options: list[str], rng: random.Random | None) -> str:
    return (rng or random).choice(options)


def listening(rng: random.Random | None = None) -> Utterance:
    """Ears on, nothing decided yet."""
    return Utterance(_pick(["hm?", "ooh, what's this", "listening..."], rng), CURIOUS)


def recalled(answer: Recognition, rng: random.Random | None = None) -> Utterance:
    """Memory alone named it: the fly guessed, and nobody was asked.

    How it says so depends on how well it knows the song, because that is the
    part worth showing. A song it has heard once is recognised with surprise; a
    song it has heard twenty times is greeted like a friend.
    """
    if not answer.named:
        return Utterance(_pick(["I know this one... no I don't",
                                "heard this before somewhere",
                                "this again! what IS it"], rng), CURIOUS)

    # Just the title in the bubble. The artist goes on its own line under it,
    # as music_id.cpp draws it, and "that's Perfect" fits the band where
    # "that's Perfect - Ed Sheeran" does not.
    name = answer.label
    if answer.heard >= 8:
        lines = [f"{name}, obviously", f"oh, {name} again", f"{name}. classic"]
        mood = DANCING
    elif answer.heard >= 3:
        lines = [f"that's {name}", f"{name}! I know this", f"this is {name}"]
        mood = DANCING
    else:
        lines = [f"is this {name}?", f"{name}, I think", f"pretty sure that's {name}"]
        mood = EXCITED
    return Utterance(_pick(lines, rng), mood, answer.label, answer.artist)


def learned(answer: Recognition, rng: random.Random | None = None) -> Utterance:
    """A teacher just named it. The fly is hearing the name for the first time."""
    name = answer.label
    return Utterance(_pick([f"ooh! {name}", f"so THAT's {name}",
                            f"new one: {name}"], rng),
                     EXCITED, answer.label, answer.artist)


def stumped(rng: random.Random | None = None) -> Utterance:
    """Neither the fly nor its teacher could name it."""
    return Utterance(_pick(["no idea what this is", "nobody knows this one",
                            "beats me"], rng), CURIOUS)


def quiet(rng: random.Random | None = None) -> Utterance:
    """The music stopped."""
    return Utterance("", IDLE)


def fit(text: str, width: int = WIDTH) -> str:
    """Shorten to something the band can hold, ending in an ellipsis if cut.

    The same idea as `fit()` in music_id.cpp, in characters rather than pixels,
    so the host can show roughly what the board will show.
    """
    if len(text) <= width:
        return text
    return text[:max(1, width - 3)].rstrip() + "..."
