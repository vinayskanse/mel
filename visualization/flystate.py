"""What the fly is doing about sound, and what everyone else does about that.

Two things live here, and neither of them needs the connectome loaded -- which
is the point. `sim_server.py` cannot be imported without MLX, a 1.5 GB pack and
an Apple GPU; the rule that a thumbs-up drives the sugar pathway and puts a
crumb down on the board can be checked on anything. See `test_wiring.py`.

`bridge` is deliberately the only place where an event becomes actions. Adding a
fifth consumer -- a log, a second board, a light on the desk -- is a line in the
function rather than a fifth subscriber racing the other four for the same
event.
"""

from __future__ import annotations

from typing import Any, Callable

import reactions


class Fly:
    """What the fly is doing about sound, for anyone who asks.

    The page, the board and the log all want the same few facts -- is it
    listening, what did it last hear, what is it showing, what face is it
    pulling -- and they want them at different moments, so they are kept here
    rather than reconstructed from the event stream three times over.
    """

    def __init__(self) -> None:
        self.available = False        # is there a learning service at all
        self.armed = False
        self.mood = "IDLE"
        self.say = ""
        self.title = ""
        self.artist = ""
        self.fingerprint = ""         # what a thumbs-up or thumbs-down is about
        self.heard = 0
        self.mode = ""                # guess | taught | stumped
        self.asked = False            # whether the last decision cost a lookup
        self.songs = 0
        self.headline = ""
        self.detail = ""

    def as_dict(self) -> dict[str, Any]:
        return dict(vars(self))


# The events that say something new about what the fly is showing. A reward is
# not one of them: being told you were right about a song does not change which
# song it was, and wiping the title off the fly's face on the way to making it
# eat would lose the one thing the moment is about.
BUBBLE_EVENTS = ("heard", "listening", "music", "quiet")


def bridge(sim, link, fly: Fly, push: Callable[[dict], None]) -> Callable[[dict], None]:
    """Return the bus subscriber: one learning event in, three places updated.

    It runs on whichever thread published -- the listening thread, or an HTTP
    handler -- so it does no work of its own beyond a dict update, a queued
    trigger and two sends that do not block. That is the contract `events.py`
    asks every subscriber to keep.
    """
    def on_event(event: dict) -> None:
        reaction = reactions.react(event)
        kind = event.get("kind", "")
        answer = event.get("answer") or {}
        say = event.get("say") or {}

        if kind == "listening":
            fly.armed = bool(event.get("armed"))
        elif kind == "heard":
            fly.mode = event.get("mode", "")
            fly.asked = bool(event.get("asked"))
            # Keep the old key if this hearing produced none: a thumbs-up a
            # moment later should still be about the song that was named.
            fly.fingerprint = answer.get("fingerprint") or fly.fingerprint
            fly.heard = int(answer.get("heard") or 0)
            fly.title = answer.get("label") or ""
            fly.artist = answer.get("artist") or ""
        elif kind == "quiet":
            fly.title = fly.artist = ""
        if kind in BUBBLE_EVENTS:
            fly.say = say.get("text", "")
        if reaction.mood:
            fly.mood = reaction.mood
        elif reaction.auto:
            fly.mood = "IDLE"
        fly.headline, fly.detail = reaction.headline, reaction.detail

        # False when this pack carries no such cells -- `sound` on a pack
        # without Johnston's organ. Passed on rather than swallowed, so the
        # page can say so instead of showing a drive that never happened.
        fired = bool(reaction.stimulus) and sim.request(reaction.stimulus, reaction.ms)

        if getattr(link, "started", False):
            link.apply(reaction, say=fly.say if kind in BUBBLE_EVENTS else None,
                       sub=fly.artist)

        push({"type": "fly", "event": kind, "fly": fly.as_dict(),
              "reaction": reaction.as_dict(), "fired": fired})
        if fired:
            push({"type": "fired", "key": reaction.stimulus, "ms": reaction.ms,
                  "source": "fly", "why": reaction.headline})

        mark = "!" if reaction.stimulus and not fired else " "
        print(f"[fly]{mark}{kind:<10} {reaction.mood or '-':<8} "
              f"{reaction.stimulus or '-':<7} {reaction.headline}", flush=True)

    return on_event
