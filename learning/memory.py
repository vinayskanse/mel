"""Persistent local memory for song identities and user preferences.

Two things live here, keyed the same way. One is what the fly knows about a
song - its name, how sure it is, whether you liked hearing about it. The other
is the landmark index that lets it recognise the song again from four seconds
picked up mid-chorus, which is what makes the first thing worth keeping.

The fly gets better at a song in two ways, and they are separate. Being told
the name is a step change and happens once. Recognising it more reliably is
gradual: every time it hears a song it already knows, the landmarks from that
hearing are folded in, so a song first met through its chorus is eventually
known by its intro and its last thirty seconds too.
"""

from __future__ import annotations

import json
import os
import re
import tempfile
import unicodedata
import time
from pathlib import Path
from typing import Any

from . import fingerprint as fpmod
from .fingerprint import Fingerprint
from .models import Recognition, Reward

# How many landmark pairs one song may hold. A four-second clip contributes
# about 300, so this is roughly a hundred hearings' worth - far more than
# enough to cover a whole song - and it bounds the JSON file at a few MB.
HASH_CAP = 30000


def slug(label: str, artist: str = "") -> str:
    """A stable, readable key for a named song.

    Accents are folded rather than dropped, so "Deja Vu" and "Deja Vu" reach
    the same key whichever way Shazam spells it back, and the key stays
    readable when someone opens the JSON to see what the fly knows.
    """
    text = f"{label} {artist}".strip()
    text = unicodedata.normalize("NFKD", text).encode("ascii", "ignore").decode()
    text = re.sub(r"[^a-z0-9]+", "-", text.lower()).strip("-")
    return text or "untitled"


class LearningMemory:
    """A small JSON-backed memory, deliberately independent of the brain model.

    The string-keyed half (`remember`, `lookup`) came first, when fingerprints
    were opaque strings handed in by a future audio adapter. That adapter now
    exists, so the audio half (`learn`, `recall`) is the one the fly uses; the
    string half is kept because it is a useful way to drive the service by hand.
    """

    def __init__(self, path: str | Path):
        self.path = Path(path)
        self._data: dict[str, Any] = {"memories": {}}
        self._index: dict[int, list[tuple[str, int]]] = {}
        self._load()

    # ---- storage -----------------------------------------------------------

    def _load(self) -> None:
        if not self.path.exists():
            return
        with self.path.open(encoding="utf-8") as stream:
            loaded = json.load(stream)
        if not isinstance(loaded, dict) or not isinstance(loaded.get("memories"), dict):
            raise ValueError(f"invalid learning memory file: {self.path}")
        self._data = loaded
        self._reindex()

    def _reindex(self) -> None:
        """Rebuild the hash -> (song, time) index that matching reads.

        It is derived, not stored: keeping it in the file as well would double
        the size and give it a second chance to disagree with itself.
        """
        self._index = {}
        for key, entry in self._data["memories"].items():
            for value, times in entry.get("hashes", {}).items():
                postings = self._index.setdefault(int(value), [])
                postings.extend((key, int(t)) for t in times)

    def _save(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        fd, temporary = tempfile.mkstemp(
            prefix=f".{self.path.name}.", dir=self.path.parent, text=True)
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as stream:
                json.dump(self._data, stream, indent=2, sort_keys=True)
                stream.write("\n")
            os.replace(temporary, self.path)
        except BaseException:
            os.unlink(temporary)
            raise

    def _entry(self, key: str, label: str = "", source: str = "local") -> dict[str, Any]:
        return self._data["memories"].setdefault(key, {
            "label": label,
            "artist": "",
            "source": source,
            "confidence": 0.5,
            "rewards": {"sugar": 0.0, "bitter": 0.0},
            "heard": 0,
            "asked": 0,
            "hashes": {},
            "first": time.time(),
            "last": time.time(),
        })

    # ---- the string-keyed half --------------------------------------------

    def remember(self, fingerprint: str, label: str, source: str) -> Recognition:
        if not fingerprint.strip() or not label.strip():
            raise ValueError("fingerprint and label are required")
        entry = self._entry(fingerprint, label, source)
        entry["label"] = label
        entry["source"] = source
        entry["heard"] += 1
        entry["last"] = time.time()
        self._save()
        return self._recognition(fingerprint, entry, local=False)

    def lookup(self, fingerprint: str) -> Recognition | None:
        entry = self._data["memories"].get(fingerprint)
        if entry is None:
            return None
        entry["heard"] += 1
        entry["last"] = time.time()
        self._save()
        return self._recognition(fingerprint, entry, local=True)

    # ---- the audio half ----------------------------------------------------

    def recall(self, clip: Fingerprint) -> Recognition | None:
        """The song this clip is, if memory is sure enough to say so.

        Every remembered song is scored, the best one wins, and it only counts
        if it is both above the floor and clearly ahead of the runner-up. A
        near-tie means two songs share a riff, or that this is neither of them,
        and in both cases the honest answer is to say nothing and let Shazam
        settle it.
        """
        if not clip.pairs:
            return None

        # Gather the candidate offsets per song in one pass over the query,
        # rather than scoring every song against the whole index separately.
        tally: dict[str, dict[int, int]] = {}
        for value, when in clip.pairs:
            for key, other in self._index.get(value, ()):
                offsets = tally.setdefault(key, {})
                offset = other - when
                offsets[offset] = offsets.get(offset, 0) + 1

        ranked = sorted(((max(offsets.values()), key, max(offsets, key=offsets.get))
                         for key, offsets in tally.items()), reverse=True)
        if not ranked:
            return None
        score, key, offset = ranked[0]
        runner_up = ranked[1][0] if len(ranked) > 1 else 0
        if score < fpmod.MIN_SCORE or score < max(1, runner_up) * fpmod.MARGIN:
            return None

        entry = self._data["memories"][key]
        entry["heard"] += 1
        entry["last"] = time.time()
        self._merge(key, entry, clip, offset)
        self._save()
        return self._recognition(key, entry, local=True, score=score)

    def learn(self, key: str, clip: Fingerprint, label: str = "",
              artist: str = "", source: str = "shazam",
              offset: int = 0) -> Recognition:
        """Take this clip into the song's memory, naming it if a name is known.

        Called both for a song met for the first time and for one already known
        whose name has only now arrived, so it must not assume either.
        """
        entry = self._entry(key, label, source)
        if label:
            entry["label"] = label
            entry["artist"] = artist
            entry["source"] = source
        entry["heard"] += 1
        entry["last"] = time.time()
        self._merge(key, entry, clip, offset)
        self._save()
        return self._recognition(key, entry, local=False)

    def _merge(self, key: str, entry: dict[str, Any],
               clip: Fingerprint, offset: int) -> None:
        """Fold one hearing's landmarks into the song's.

        `offset` is where this clip sat in the song's own timeline, as matching
        worked out. Shifting by it puts every hearing into one frame of
        reference, so overlapping clips reinforce each other's evidence instead
        of each forming a separate cluster the histogram has to choose between.
        """
        hashes = entry.setdefault("hashes", {})
        if sum(len(v) for v in hashes.values()) >= HASH_CAP:
            return
        for value, when in clip.pairs:
            at = when + offset
            times = hashes.setdefault(str(value), [])
            if at in times:
                continue
            times.append(at)
            self._index.setdefault(value, []).append((key, at))

    def rename(self, old: str, label: str, artist: str = "",
               source: str = "shazam") -> Recognition:
        """Give a name to a tune that was remembered before it had one.

        The key changes with the name, because the key is the name, so the
        index has to be told. Everything the fly learned about the tune while
        it was nameless - its landmarks, how often it has come up - is carried
        across, which is the point of having remembered it at all.
        """
        entry = self._data["memories"].pop(old)
        entry["label"] = label
        entry["artist"] = artist
        entry["source"] = source
        key = slug(label, artist)
        existing = self._data["memories"].get(key)
        if existing is not None:
            # The same song was already known under this name: keep the older
            # record and give it this one's landmarks and hearings.
            for value, times in entry.get("hashes", {}).items():
                merged = existing.setdefault("hashes", {}).setdefault(value, [])
                merged.extend(t for t in times if t not in merged)
            existing["heard"] += entry.get("heard", 0)
            entry = existing
        self._data["memories"][key] = entry
        self._reindex()
        self._save()
        return self._recognition(key, entry, local=False)

    def asked(self, key: str) -> int:
        """How many times a teacher has been asked about this tune."""
        entry = self._data["memories"].get(key)
        return int(entry.get("asked", 0)) if entry else 0

    def note_ask(self, key: str) -> None:
        """Record that a teacher was asked, so a tune nobody can name is not
        asked about forever."""
        entry = self._data["memories"].get(key)
        if entry is not None:
            entry["asked"] = int(entry.get("asked", 0)) + 1
            self._save()

    def next_tune_key(self) -> str:
        """A placeholder key for a tune heard but not yet named."""
        taken = {k for k in self._data["memories"] if k.startswith("tune-")}
        n = 1
        while f"tune-{n}" in taken:
            n += 1
        return f"tune-{n}"

    # ---- feedback and listing ---------------------------------------------

    def reward(self, reward: Reward) -> Recognition:
        entry = self._data["memories"].get(reward.fingerprint)
        if entry is None:
            raise KeyError(f"unknown fingerprint: {reward.fingerprint}")
        if reward.kind not in ("sugar", "bitter"):
            raise ValueError("reward kind must be sugar or bitter")
        entry["rewards"][reward.kind] += reward.amount
        direction = 1.0 if reward.kind == "sugar" else -1.0
        entry["confidence"] = min(1.0, max(0.0, entry["confidence"] + direction * 0.1 * reward.amount))
        self._save()
        return self._recognition(reward.fingerprint, entry, local=True)

    def all(self) -> list[Recognition]:
        return [self._recognition(key, value, local=True)
                for key, value in self._data["memories"].items()]

    def __len__(self) -> int:
        return len(self._data["memories"])

    @staticmethod
    def _recognition(fingerprint: str, entry: dict[str, Any],
                     local: bool, score: int = 0) -> Recognition:
        return Recognition(fingerprint, entry["label"], entry["source"],
                           float(entry["confidence"]), local,
                           entry.get("artist", ""), score,
                           int(entry.get("heard", 0)))
