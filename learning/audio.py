"""Getting sound into the fly, and deciding when it is worth listening to.

Everything here works in one of two forms: raw PCM16 bytes, which is what the
board sends and what Shazam wants, and lists of floats in -1..1, which is what
the fingerprint works in. Nothing here knows what a song is.

Capture goes through ffmpeg rather than a Python audio binding, because the
rest of this package is stdlib and asking someone to build PortAudio before the
fly can hear a song is a poor trade. The same path reads a file, which is how
the whole pipeline can be exercised without a board or a room.
"""

from __future__ import annotations

import shutil
import struct
import subprocess
import threading
from collections import deque
from dataclasses import dataclass, field

from . import fingerprint as fpmod

BOARD_RATE = 16000        # what the ES7210 records and what the board streams
SHAZAM_RATE = 44100       # Shazam takes 44.1 kHz mono PCM16 and nothing else


def have_ffmpeg() -> bool:
    return shutil.which("ffmpeg") is not None


# ---- converting between the two forms --------------------------------------

def to_samples(pcm: bytes) -> list[float]:
    """Mono 16-bit little-endian PCM to floats in -1..1."""
    count = len(pcm) // 2
    return [v / 32768.0 for v in struct.unpack(f"<{count}h", pcm[:count * 2])]


def to_pcm(samples: list[float]) -> bytes:
    """Floats in -1..1 back to mono 16-bit little-endian PCM, clipped."""
    return struct.pack(f"<{len(samples)}h",
                       *(max(-32768, min(32767, int(v * 32767))) for v in samples))


def resample(samples: list[float], src: int, dst: int) -> list[float]:
    """Linear resampling, with a two-tap average when halving.

    Halving is the case that actually runs - 16 kHz from the board down to the
    8 kHz the fingerprint works in - and dropping every other sample would fold
    everything above 4 kHz back down on top of the music. Averaging pairs is a
    crude low-pass, but it is the right shape and it costs one addition.
    """
    if src == dst or not samples:
        return list(samples)
    if src == dst * 2:
        return [(samples[i] + samples[i + 1]) * 0.5
                for i in range(0, len(samples) - 1, 2)]
    ratio = src / dst
    out = []
    count = int(len(samples) / ratio)
    for i in range(count):
        at = i * ratio
        low = int(at)
        frac = at - low
        high = min(low + 1, len(samples) - 1)
        out.append(samples[low] * (1 - frac) + samples[high] * frac)
    return out


def for_fingerprint(pcm: bytes, rate: int = BOARD_RATE) -> list[float]:
    """A clip as the fingerprint wants it: floats at fingerprint.RATE."""
    return resample(to_samples(pcm), rate, fpmod.RATE)


def energy(samples: list[float]) -> float:
    """Mean square. Cheaper than RMS and ordered the same way."""
    if not samples:
        return 0.0
    return sum(v * v for v in samples) / len(samples)


# ---- is anything playing? ---------------------------------------------------

# Measured through this Mac's own microphone, in 8 ms blocks, as the fraction
# of blocks whose energy passes the threshold:
#
#   quiet room            2%        music                  78%
#   farm ambience        38%        fruit fly courtship     70%
#   music at 1/3 volume  31%        a voiceover         74-94%
#
# So loudness plus continuity tells music from an empty room, which is what
# this gate is for. It does *not* tell music from continuous speech - the
# voiceover above is steadier than the music - and nothing cheap does. That is
# left to Shazam, which answers "not recognised" for talking, and to the
# backoff in ears.py that stops the fly asking about the same talking forever.
BLOCK = 128               # samples: 8 ms at 16 kHz, the board's own block size
WINDOW = 375              # blocks: three seconds
ON, OFF = 0.70, 0.45      # fraction of the window that must be loud, and stay
LOUD = 3e-4               # block energy: sits between the room's 90th
                          # percentile (1.7e-4) and music's median (8.7e-4)
OVER_FLOOR = 4.0          # a noisy room raises the bar; nothing lowers it
RISE, FALL = 1.0002, 0.995   # how fast the tracked room level may move


@dataclass
class MusicGate:
    """Follows the room and says whether something is playing in it.

    The threshold is the measured one above, which a noisy room may raise but
    nothing may lower: a fixed number alone would call a loud fan music, and a
    purely relative one would quietly adapt to the song and then decide the
    song had stopped. The tracked level therefore only moves while nothing is
    playing. Once the gate has latched on to music it stops following the room
    entirely, so a three-minute song cannot talk it out of hearing itself.
    """

    level: float = LOUD
    loud: deque = field(default_factory=lambda: deque(maxlen=WINDOW))
    playing: bool = False

    def feed(self, samples: list[float]) -> bool:
        """Take some audio at BOARD_RATE; returns whether music is playing."""
        for i in range(0, len(samples) - BLOCK + 1, BLOCK):
            e = energy(samples[i:i + BLOCK])
            if not self.playing:
                self.level *= RISE if e > self.level else FALL
            self.loud.append(e > max(LOUD, self.level * OVER_FLOOR))
        if len(self.loud) < WINDOW // 3:
            return self.playing
        share = sum(self.loud) / len(self.loud)
        if share >= ON:
            self.playing = True
        elif share < OFF:
            self.playing = False
        return self.playing

    @property
    def share(self) -> float:
        return sum(self.loud) / len(self.loud) if self.loud else 0.0

    def forget(self) -> None:
        self.loud.clear()
        self.playing = False


# ---- where sound comes from -------------------------------------------------

class Source:
    """A stream of PCM16 at BOARD_RATE, from wherever."""

    def read(self, count: int) -> bytes:
        raise NotImplementedError

    def close(self) -> None:
        pass


class FfmpegSource(Source):
    """PCM16 at BOARD_RATE out of anything ffmpeg can open."""

    def __init__(self, args: list[str], label: str):
        self.label = label
        self._process = subprocess.Popen(
            ["ffmpeg", "-v", "error", *args,
             "-ac", "1", "-ar", str(BOARD_RATE), "-f", "s16le", "-"],
            stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        # Without this, a long run eventually blocks on ffmpeg's own stderr.
        threading.Thread(target=self._drain, daemon=True).start()

    def _drain(self) -> None:
        stream = self._process.stderr
        if stream is not None:
            for _ in iter(stream.readline, b""):
                pass

    def read(self, count: int) -> bytes:
        assert self._process.stdout is not None
        return self._process.stdout.read(count * 2)

    def close(self) -> None:
        self._process.terminate()
        try:
            self._process.wait(timeout=2)
        except subprocess.TimeoutExpired:
            self._process.kill()


def microphone(device: str = ":0") -> FfmpegSource:
    """The Mac's microphone. `ffmpeg -f avfoundation -list_devices true -i ""`
    lists them; ":0" is the built-in one."""
    return FfmpegSource(["-f", "avfoundation", "-i", device], f"microphone {device}")


def from_file(path: str, realtime: bool = True) -> FfmpegSource:
    """A file, for trying the whole thing without a room or a board.

    `realtime` makes ffmpeg hand it over at the speed it would actually play,
    so the gate and the pacing behave as they will on the day.
    """
    args = ["-re"] if realtime else []
    return FfmpegSource([*args, "-i", path], path)


def record(source: Source, seconds: float) -> bytes:
    """Exactly this many seconds of PCM16, or less if the source runs out."""
    want = int(BOARD_RATE * seconds)
    out = bytearray()
    while len(out) < want * 2:
        chunk = source.read(min(4096, want - len(out) // 2))
        if not chunk:
            break
        out += chunk
    return bytes(out)
