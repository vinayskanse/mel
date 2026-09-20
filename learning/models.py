"""Data objects exchanged by the learning service."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True)
class Recognition:
    """The answer shown for one heard audio fingerprint.

    `fingerprint` is the memory's key for the song. `local` says how *this*
    answer was reached - True when memory alone produced it, False when a
    teacher had to be asked - which is not the same as where the name
    originally came from. A song Shazam named once is remembered forever after,
    and every later hearing of it is local even though `source` stays "shazam".
    That distinction is the whole point of the exercise: it is what separates a
    guess the fly made from an answer it was handed.
    """

    fingerprint: str
    label: str
    source: str
    confidence: float
    local: bool
    artist: str = ""
    score: int = 0
    heard: int = 0

    @property
    def named(self) -> bool:
        """False for a tune that has been heard but never successfully named."""
        return bool(self.label)

    @property
    def title(self) -> str:
        """Title and artist on one line, for anywhere with room for both."""
        if not self.label:
            return "something I don't know yet"
        return f"{self.label} - {self.artist}" if self.artist else self.label

    def as_dict(self) -> dict[str, Any]:
        return {
            "fingerprint": self.fingerprint,
            "label": self.label,
            "artist": self.artist,
            "source": self.source,
            "confidence": self.confidence,
            "local": self.local,
            "score": self.score,
            "heard": self.heard,
        }


@dataclass(frozen=True)
class Reward:
    """Feedback from the user after the fly makes a guess."""

    fingerprint: str
    kind: str
    amount: float = 1.0

    def as_dict(self) -> dict[str, Any]:
        return {
            "fingerprint": self.fingerprint,
            "kind": self.kind,
            "amount": self.amount,
        }
