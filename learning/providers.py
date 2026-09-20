"""Teachers: who the fly asks when its own memory is not enough.

A teacher is asked rarely and costs something, which is the whole reason the
memory in this package exists. Every answer a teacher gives is written down so
the same question is never paid for twice.
"""

from __future__ import annotations

import base64
import json
import os
import unicodedata
import urllib.error
import urllib.request
from dataclasses import dataclass
from pathlib import Path
from typing import Protocol

from . import audio

ROOT = Path(__file__).resolve().parent.parent

SHAZAM_URL = ("https://shazam.p.rapidapi.com/songs/v2/detect"
              "?timezone=Asia%2FKolkata&locale=en-US")
SHAZAM_HOST = "shazam.p.rapidapi.com"

# Shazam takes a few seconds of 44.1 kHz mono PCM16 and nothing else, and a
# clip shorter than this is not worth a call.
MIN_SECONDS = 2.0
PEAK = 26000              # normalise up to here: a mic in a room is quiet
MAX_GAIN = 8.0


def load_env(path: Path | None = None) -> dict[str, str]:
    """The repository's .env, which is where the API key lives."""
    env: dict[str, str] = {}
    source = path or (ROOT / ".env")
    if not source.exists():
        return env
    for line in source.read_text(encoding="utf-8").splitlines():
        if "=" in line and not line.lstrip().startswith("#"):
            key, value = line.split("=", 1)
            env[key.strip()] = value.strip()
    return env


def plain(text: str) -> str:
    """The board's fonts are plain ASCII: drop accents and other scripts."""
    return unicodedata.normalize("NFKD", text).encode("ascii", "ignore").decode().strip()


@dataclass(frozen=True)
class Song:
    title: str
    artist: str = ""

    def __str__(self) -> str:
        return f"{self.title} - {self.artist}" if self.artist else self.title


class SongTeacher(Protocol):
    def identify(self, pcm: bytes, rate: int) -> Song | None:
        """Name the song in this clip, or None if it cannot."""


class Teacher(Protocol):
    """The older, string-keyed teacher, kept for driving `/hear` by hand."""

    def identify(self, fingerprint: str) -> str | None:
        """Return a label, or None when the teacher cannot identify it."""


@dataclass
class StaticTeacher:
    """Offline teacher for development and tests."""

    answers: dict[str, str]

    def identify(self, fingerprint: str) -> str | None:
        return self.answers.get(fingerprint)


@dataclass
class StaticSongTeacher:
    """A song teacher that answers from a list, for tests. Counts its calls so
    a test can show that memory is what stops the fly asking twice."""

    answers: list[Song | None]
    calls: int = 0

    def identify(self, pcm: bytes, rate: int) -> Song | None:
        self.calls += 1
        if not self.answers:
            return None
        return self.answers[min(self.calls - 1, len(self.answers) - 1)]


class DeafTeacher:
    """Never names anything. Lets the fly be run with the network left out, to
    see what it can manage on memory alone."""

    def identify(self, pcm: bytes, rate: int) -> Song | None:
        return None


@dataclass
class ShazamTeacher:
    """RapidAPI's Shazam endpoint. One clip in, one song out, one call spent.

    Lifted from the deskbuddy server, which has been answering with it for a
    while: the same URL, the same resampling to 44.1 kHz and the same
    normalisation, because a mic across a desk hands over something much
    quieter than the phone in your hand that Shazam was built for.
    """

    key: str = ""
    timeout: float = 20.0
    calls: int = 0

    @classmethod
    def from_env(cls) -> "ShazamTeacher":
        env = load_env()
        return cls(key=os.environ.get("SHAZAM_API_KEY", env.get("SHAZAM_API_KEY", "")))

    @property
    def ready(self) -> bool:
        return bool(self.key)

    def identify(self, pcm: bytes, rate: int = audio.BOARD_RATE) -> Song | None:
        if not self.key:
            print("  no SHAZAM_API_KEY in .env")
            return None
        if len(pcm) / (rate * 2) < MIN_SECONDS:
            return None

        samples = audio.resample(audio.to_samples(pcm), rate, audio.SHAZAM_RATE)
        peak = max((abs(v) for v in samples), default=0.0)
        if peak > 0:
            samples = [v * min(MAX_GAIN, (PEAK / 32768.0) / peak) for v in samples]

        request = urllib.request.Request(
            SHAZAM_URL, data=base64.b64encode(audio.to_pcm(samples)), method="POST",
            headers={"content-type": "text/plain",
                     "X-RapidAPI-Key": self.key,
                     "X-RapidAPI-Host": SHAZAM_HOST})
        self.calls += 1
        try:
            with urllib.request.urlopen(request, timeout=self.timeout) as response:
                found = json.load(response)
        except (urllib.error.URLError, TimeoutError, json.JSONDecodeError, OSError) as error:
            print(f"  shazam failed: {error}")
            return None

        track = found.get("track")
        if not track:
            return None
        return Song(plain(track.get("title", "")) or "Unknown title",
                    plain(track.get("subtitle", "")))
