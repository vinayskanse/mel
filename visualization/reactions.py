"""What the fly's brain and body do about each thing that happens to it.

This is the whole join between `learning/` and the simulator, and it is a table
on purpose. Every row is one claim -- "being handed a sweet reward drives the
sugar receptor neurons of the right labellum" -- and a claim in a table can be
read, argued with and corrected. The same decision spread across three
if-statements in a socket handler could not be.

Two rules the table keeps to:

  * **The brain column is anatomy, not decoration.** A row drives a stimulus
    only where a real fly has a sense organ for it. Hearing a song drives the
    auditory path because a fly hears with its antennae; a thumbs-up drives the
    sugar path because Tastekin et al. matched those cells to the sugar
    receptor. There is no "recognition" input and no "happiness" input, so
    those rows drive nothing and say so.
  * **The face column is the design sheet.** Ten moods exist in `fly.h` and
    nothing here invents an eleventh.

`stimulus` names a key in sim_server.STIMULI. A key that the connectome turned
out not to have simply does not fire -- see `LiveBrain`, which drops a stimulus
it cannot resolve rather than refusing to start -- so a row costs nothing when
its neurons are missing.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class Reaction:
    """One event's consequences, in all three places at once."""

    stimulus: str = ""          # a key in STIMULI, or "" for nothing to drive
    ms: float = 0.0             # how long to drive it
    mood: str = ""              # a fly.h Mood name, or "" to leave the face alone
    hold: float = 0.0           # seconds to hold that face; 0 means "until told otherwise"
    feed: bool = False          # put a crumb down: the fly eats and is pleased
    auto: bool = False          # hand the choice of face back to the fly
    headline: str = ""          # what the viewer's narration says
    detail: str = ""

    @property
    def empty(self) -> bool:
        return not (self.stimulus or self.mood or self.feed or self.auto)

    def as_dict(self) -> dict:
        return {"stimulus": self.stimulus, "ms": self.ms, "mood": self.mood,
                "hold": self.hold, "feed": self.feed, "auto": self.auto,
                "headline": self.headline, "detail": self.detail}


NOTHING = Reaction()

# How long each kind of drive lasts. Short: these fire while the brain is
# already running, and a two-second drive on top of a self-sustaining network
# is how you get a brain that never settles again (see context/circuits.md on
# Smell). The sweet reward gets the longest because it has the furthest to go --
# 27 ms of biological time from the labellum to MN9.
EAR = 400.0
SWEET = 700.0


def _heard(event: dict) -> Reaction:
    """A clip was judged. Which of the three outcomes it was matters to the face
    but not much to the brain: the ear fired either way, because the sound
    arrived either way. What memory then did with it is not a sense organ."""
    mode = event.get("mode", "")
    answer = event.get("answer") or {}
    say = event.get("say") or {}
    label = answer.get("label") or ""
    artist = answer.get("artist") or ""
    heard = int(answer.get("heard") or 0)
    named = f"{label} — {artist}" if artist else label

    if mode == "guess":
        # It knew the song from its own memory, without asking anyone. The
        # longer it has known it, the less surprised it is about it.
        mood = "DANCING" if heard >= 3 else "EXCITED"
        return Reaction(stimulus="sound", ms=EAR, mood=mood, hold=6.0,
                        headline=say.get("text") or f"knows this: {label}",
                        detail=f"recognised from memory{f' — {named}' if named else ''}"
                               f" · heard {heard}×, nobody was asked")
    if mode == "taught":
        return Reaction(stimulus="sound", ms=EAR, mood="EXCITED", hold=6.0,
                        headline=say.get("text") or f"learned: {label}",
                        detail=f"Shazam named it once{f' — {named}' if named else ''}."
                               " It is written down; it will never be asked again")
    return Reaction(stimulus="sound", ms=EAR, mood="CURIOUS", hold=5.0,
                    headline=say.get("text") or "no idea what this is",
                    detail="the tune is remembered anyway, so the next hearing "
                           "is at least recognised as the same unknown thing")


def _reward(event: dict) -> Reaction:
    """The only moment the fly is told whether it was right.

    Sweet is a real input and gets the real pathway: 17 sugar receptor neurons
    of the right labellum, through 24.5M synapses, to MN9, which is the motor
    neuron that extends the proboscis. Nothing in between is scripted, and the
    crumb on the board goes down at the same moment.

    Bitter has no row in the brain column. The pack's labellar bitter cells are
    not identified in `context/circuits.md`, and naming a cell type on a hunch
    would put a false claim on screen, so a thumbs-down moves the fly's
    confidence and its face and leaves the connectome alone. `find_types.py`
    is there for when the right type is known.
    """
    answer = event.get("answer") or {}
    label = answer.get("label") or "that"
    if event.get("reward") == "sugar":
        return Reaction(stimulus="sugar", ms=SWEET, mood="EATING", feed=True,
                        headline="sweet — the proboscis extends",
                        detail=f"you agreed it was {label}. 17 sugar neurons of the "
                               "right labellum are firing; watch MN9_L")
    return Reaction(mood="ANGRY", hold=3.0,
                    headline="bitter — it was wrong",
                    detail=f"confidence in {label} drops. No bitter receptor is "
                           "identified in this pack, so nothing is driven")


def react(event: dict) -> Reaction:
    """The one entry point: an event off the bus, and what to do about it."""
    kind = event.get("kind", "")
    say = event.get("say") or {}

    if kind == "listening":
        if event.get("armed"):
            return Reaction(mood="CURIOUS", hold=4.0,
                            headline=say.get("text") or "listening",
                            detail="ears armed — it will guess from memory first, "
                                   "and only ask about what it cannot place")
        return Reaction(auto=True, headline="ears off", detail="")

    if kind == "music":
        # Sound in the room, before anything has been decided about it. This is
        # the honest place for the auditory drive: something is audible now.
        return Reaction(stimulus="sound", ms=EAR, mood="CURIOUS", hold=4.0,
                        headline=say.get("text") or "hears something",
                        detail="the energy gate says music is playing")

    if kind == "identify":
        return Reaction(stimulus="sound", ms=EAR, mood="CURIOUS", hold=3.0,
                        headline="what IS this", detail="naming it now, without waiting")

    if kind == "quiet":
        return Reaction(auto=True, headline="the music stopped",
                        detail="the fly drops the title and goes back to its own life")

    if kind == "heard":
        return _heard(event)

    if kind == "reward":
        return _reward(event)

    return NOTHING
