"""Turning a few seconds of sound into landmarks the fly can recognise again.

The fly has to answer two different questions, and only one of them is Shazam's.
Shazam answers "what is this song called", once, for money. This file answers
"have I heard this before", every time, for free, on whatever the board can
spare. So a fingerprint here is not a checksum of the clip: two recordings of
the same song, taken from different points in the song, through a mic, in a
room, share almost no samples. What they do share is the pattern of loud spots
in the spectrogram - a drum hit, a held note - and, more to the point, the
*distances between them*, which survive volume, noise, and a cheap speaker.

So each clip becomes a list of (hash, time) pairs, where a hash packs two peak
frequencies and the gap between them. Two clips of the same song produce many
equal hashes, and - this is the part that separates a real match from chance -
the equal hashes all land at the *same offset* apart. Matching is therefore a
histogram of offsets, and the score is the tallest bar. Chance scatters; a real
match stacks up.

This is the constellation/landmark scheme Shazam's own paper describes. It is
here in pure Python, with no numpy, because the rest of this package is stdlib
and the fly's host should not need a build toolchain to remember a song.
"""

from __future__ import annotations

import cmath
import math
from dataclasses import dataclass, field

# The spectrogram the landmarks are found in. 8 kHz keeps everything a mic in a
# room actually captures (music's landmarks sit well under 4 kHz) and halves the
# work; 1024 samples is 128 ms, fine enough to separate two notes a tone apart;
# the 256-sample hop gives 31 frames a second, which is the time resolution the
# offset histogram ends up quantised to.
RATE = 8000
FRAME = 1024
HOP = 256
BINS = FRAME // 2          # bins 0..511, i.e. 0..4 kHz at 7.8 Hz each

# Peak picking. Anything quieter than this fraction of the loudest spot in its
# own frame is texture, not a landmark, and PER_FRAME caps how many survive so
# one loud passage cannot flood the index.
#
# DENSITY is the one that earns its keep. A per-frame threshold is relative to
# that frame, so in the near-silence between two notes the loudest thing in the
# frame *is* the room noise, and it gets indexed as though it were music. With
# a quiet source and a noisy room that filled the index with hiss - the peak
# count went from 27 to 122 on a test clip - and the hiss crowded the real
# landmarks out of every pairing. Keeping only the strongest few peaks per
# second of the whole clip fixes it: noise loses to music everywhere at once.
FLOOR = 0.02
PER_FRAME = 6
DENSITY = 14               # peaks kept per second of clip

# Pairing. An anchor looks forward into a window of later peaks: far enough to
# span a beat, near enough that both ends stay inside a four-second clip.
MIN_DT, MAX_DT = 2, 40     # frames: 64 ms .. 1.3 s
FAN = 6                    # pairs made per anchor

# Accepting a match. A score is the number of landmark pairs that agree on one
# time offset, so it grows with how much of the song the clip overlaps, and the
# floor is what coincidence produces. Measured on four unrelated real
# recordings (music, a fruit fly courtship recording, speech and a farm
# ambience), 64 four-second clips at a range of volumes and noise levels:
# the right source scored 14 to 277, and the best *wrong* source never scored
# above 3. Eight, and twice the runner-up, sits in the gap with room either
# side. Being unsure is cheap - it costs one Shazam call - while being wrong
# puts a confident lie on the fly's face, so the rule leans towards unsure.
MIN_SCORE = 8
MARGIN = 2.0

_windows: dict[int, list[float]] = {}
_twiddles: dict[int, list[complex]] = {}
_reversals: dict[int, list[int]] = {}


def _hann(n: int) -> list[float]:
    """A Hann window, cached: without one, every frame edge rings across the
    whole spectrum and buries the peaks we came for."""
    if n not in _windows:
        _windows[n] = [0.5 - 0.5 * math.cos(2 * math.pi * i / n) for i in range(n)]
    return _windows[n]


def _prepare(n: int) -> tuple[list[complex], list[int]]:
    """Twiddle factors and the bit-reversal permutation for an n-point FFT."""
    if n not in _twiddles:
        _twiddles[n] = [cmath.exp(-2j * math.pi * i / n) for i in range(n // 2)]
        bits = n.bit_length() - 1
        order = [0] * n
        for i in range(n):
            r = 0
            for b in range(bits):
                r = (r << 1) | ((i >> b) & 1)
            order[i] = r
        _reversals[n] = order
    return _twiddles[n], _reversals[n]


def _fft(values: list[complex]) -> list[complex]:
    """In-place iterative radix-2 FFT. n must be a power of two."""
    n = len(values)
    twiddle, order = _prepare(n)
    out = [values[order[i]] for i in range(n)]
    size = 2
    while size <= n:
        half, step = size // 2, n // size
        for start in range(0, n, size):
            k = 0
            for i in range(start, start + half):
                a, b = out[i], out[i + half] * twiddle[k]
                out[i], out[i + half] = a + b, a - b
                k += step
        size *= 2
    return out


def _spectrum(samples: list[float], start: int) -> list[float]:
    """Power spectrum of one FRAME-long window, as BINS values.

    A real signal's FFT is symmetric, so half of a complex FFT is wasted on it.
    This packs the even samples into the real part and the odd into the
    imaginary part of a half-length FFT and untangles the two afterwards, which
    is the difference between this running in a second and running in two.
    """
    window = _hann(FRAME)
    half = FRAME // 2
    packed = [complex(samples[start + 2 * i] * window[2 * i],
                      samples[start + 2 * i + 1] * window[2 * i + 1])
              for i in range(half)]
    z = _fft(packed)

    power = [0.0] * BINS
    for k in range(half):
        a = z[k]
        b = z[(half - k) % half].conjugate()
        even = (a + b) * 0.5
        odd = (a - b) * -0.5j * cmath.exp(-2j * math.pi * k / FRAME)
        value = even + odd
        power[k] = value.real * value.real + value.imag * value.imag
    return power


def spectrogram(samples: list[float]) -> list[list[float]]:
    """One power spectrum per HOP, for samples already at RATE."""
    return [_spectrum(samples, start)
            for start in range(0, len(samples) - FRAME + 1, HOP)]


def peaks(frames: list[list[float]]) -> list[tuple[int, int]]:
    """The (frame, bin) landmarks: spots louder than everything around them.

    Three passes, cheapest first. Each frame's own local maxima in frequency
    cost three comparisons a bin and leave a few dozen candidates. Only those
    are checked against the neighbouring frames in time, which is what stops a
    sustained note from entering the index once per frame for its whole length.
    What survives is then thinned to DENSITY peaks a second, strongest first.
    """
    candidates: list[list[tuple[float, int]]] = []
    for row in frames:
        loudest = max(row) if row else 0.0
        if loudest <= 0.0:
            candidates.append([])
            continue
        cut = loudest * FLOOR
        here = [(row[b], b) for b in range(1, BINS - 1)
                if row[b] > cut and row[b] >= row[b - 1] and row[b] > row[b + 1]]
        here.sort(reverse=True)
        candidates.append(here[:PER_FRAME])

    survivors: list[tuple[float, int, int]] = []
    for t, here in enumerate(candidates):
        for power, b in here:
            lo, hi = max(0, t - 2), min(len(frames), t + 3)
            if all(power >= max(frames[n][max(0, b - 1):b + 2])
                   for n in range(lo, hi) if n != t):
                survivors.append((power, t, b))

    keep = max(1, int(DENSITY * len(frames) * HOP / RATE))
    if len(survivors) > keep:
        survivors.sort(reverse=True)
        survivors = survivors[:keep]
    return sorted((t, b) for _, t, b in survivors)


def _hash(f1: int, f2: int, dt: int) -> int:
    """Pack a pair of landmarks into one integer.

    The frequencies are kept to 8 bits - half a bin's precision, about 15 Hz -
    on purpose. Exact bins would not survive a different mic or a slightly
    different pitch, and a hash that never matches is worse than a coarse one.
    """
    return ((f1 >> 1) << 14) | ((f2 >> 1) << 6) | (dt & 0x3F)


def pairs(landmarks: list[tuple[int, int]]) -> list[tuple[int, int]]:
    """(hash, time) for every anchor paired with the peaks just after it."""
    out: list[tuple[int, int]] = []
    for i, (t1, f1) in enumerate(landmarks):
        made = 0
        for t2, f2 in landmarks[i + 1:]:
            dt = t2 - t1
            if dt < MIN_DT:
                continue
            if dt > MAX_DT:
                break
            out.append((_hash(f1, f2, dt), t1))
            made += 1
            if made >= FAN:
                break
    return out


@dataclass(frozen=True)
class Fingerprint:
    """What one clip leaves behind: its landmark pairs, and how long it was."""

    pairs: list[tuple[int, int]] = field(default_factory=list)
    frames: int = 0

    def __len__(self) -> int:
        return len(self.pairs)

    @property
    def seconds(self) -> float:
        return self.frames * HOP / RATE


def of(samples: list[float]) -> Fingerprint:
    """Fingerprint samples that are already mono floats at RATE."""
    frames = spectrogram(samples)
    return Fingerprint(pairs(peaks(frames)), len(frames))


def best(query: Fingerprint, postings: dict[int, list[int]]) -> tuple[int, int]:
    """How well a clip matches one remembered song, and at what offset.

    `postings` maps hash -> the times that hash occurred at in the song. A hash
    in common is worth little on its own; what counts is how many of them agree
    on the same time offset, because that is the one thing coincidence does not
    produce. The answer is the height of the tallest bar in that histogram, and
    the offset it stands at - which is where in the song this clip came from.
    """
    offsets: dict[int, int] = {}
    best_count, best_offset = 0, 0
    for value, when in query.pairs:
        for other in postings.get(value, ()):
            offset = other - when
            count = offsets.get(offset, 0) + 1
            offsets[offset] = count
            if count > best_count:
                best_count, best_offset = count, offset
    return best_count, best_offset


def score(query: Fingerprint, postings: dict[int, list[int]]) -> int:
    """Just the height of the tallest bar; see `best`."""
    return best(query, postings)[0]
