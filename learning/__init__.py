"""Local song and tune learning for the fly.

The fly guesses first from its own memory and only asks Shazam about what it
could not place, so a song costs one API call in its life however often it is
played. See README.md.
"""

from .events import bus
from .memory import LearningMemory
from .models import Recognition, Reward

__all__ = ["Answer", "Ears", "LearningMemory", "Recognition", "Reward",
           "ShazamTeacher", "Song", "Utterance", "bus"]

# The rest are fetched on first use. Importing `ears` here instead would make
# `python -m learning.ears` load the module twice and warn about it, and that
# command is how the whole thing is tried out.
_LAZY = {"Answer": ".ears", "Ears": ".ears", "Utterance": ".says",
         "ShazamTeacher": ".providers", "Song": ".providers"}


def __getattr__(name: str):
    if name in _LAZY:
        from importlib import import_module
        return getattr(import_module(_LAZY[name], __name__), name)
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
