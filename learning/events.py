"""A local notice board, so one decision can reach several listeners.

The fly's listening, its brain and its face are three separate things that have
to agree about one moment. When memory names a song, the bubble changes, the
auditory neurons get driven, and the board pulls a face -- all from the single
decision `Ears.hear` already made.

The alternative was for each of those to ask the others over HTTP, which would
mean the brain polling the learning service several times a second forever. This
costs nothing and asks nobody: a publisher hands over a dict, and whoever
subscribed gets called on the publisher's own thread.

That last point is the contract. A subscriber runs inline, so it must be quick
and must not block -- the simulator's subscriber only drops a trigger into a
queue, which is the shape every subscriber here should have. An exception in one
subscriber is printed and swallowed, because a broken face is not a reason to
stop the fly from hearing.
"""

from __future__ import annotations

import threading
import time
import traceback
from typing import Any, Callable

Listener = Callable[[dict[str, Any]], None]


class EventBus:
    def __init__(self) -> None:
        self._listeners: list[Listener] = []
        self._lock = threading.Lock()

    def subscribe(self, fn: Listener) -> Callable[[], None]:
        """Register fn, and hand back the thing that unregisters it."""
        with self._lock:
            self._listeners.append(fn)

        def drop() -> None:
            with self._lock:
                if fn in self._listeners:
                    self._listeners.remove(fn)
        return drop

    def publish(self, kind: str, **data: Any) -> dict[str, Any]:
        """Announce one thing that happened. Returns the event, for convenience."""
        event = {"kind": kind, "at": time.time(), **data}
        with self._lock:
            listeners = list(self._listeners)
        for fn in listeners:
            try:
                fn(event)
            except Exception:                    # a subscriber is never fatal
                traceback.print_exc()
        return event


# The one bus. The learning package publishes to it; the simulator and the
# board link subscribe. Nothing here imports either of those, so `learning`
# stays testable on its own.
bus = EventBus()
