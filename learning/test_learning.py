import math
import random
import struct
import tempfile
import unittest
from pathlib import Path

from learning import audio, says
from learning import fingerprint as fpmod
from learning.ears import Ears
from learning.memory import LearningMemory, slug
from learning.providers import Song, StaticSongTeacher, StaticTeacher, plain
from learning.service import LearningApp


def tone_clip(seed: int, seconds: float = 4.0, start: float = 0.0,
              gain: float = 1.0, noise: float = 0.0) -> bytes:
    """A repeatable synthetic tune as PCM16 at the board's rate.

    Real recordings would be a better test and are what the thresholds were
    actually chosen against, but they cannot live in the repository, so this
    stands in: a fixed sequence of notes with harmonics and a kick, which has
    the landmark structure the fingerprint looks for.
    """
    rng = random.Random(seed)
    # Each tune gets its own scale. Drawing every tune from one shared scale
    # made them near-duplicates of each other - the same notes in a different
    # order, over the same few kick drums - and a fingerprint is quite right to
    # find those similar. Real songs are not related that way.
    scale = [rng.uniform(150, 700) for _ in range(8)]
    notes = [rng.choice(scale) for _ in range(64)]
    kick = rng.choice([55, 62, 70])
    beat = 60.0 / rng.choice([96, 120])
    noise_rng = random.Random(seed * 7 + 1)
    out = []
    for i in range(int(audio.BOARD_RATE * seconds)):
        t = start + i / audio.BOARD_RATE
        phase = (t / beat) - int(t / beat)
        f = notes[int(t / beat) % len(notes)]
        v = sum(g * math.sin(2 * math.pi * f * h * t)
                for h, g in [(1, 1.0), (2, 0.5), (3, 0.25), (5, 0.12)])
        v *= 1.0 - phase
        v += 0.7 * math.sin(2 * math.pi * kick * t) * max(0.0, 1 - phase * 8)
        v = v * 0.2 * gain
        if noise:
            v += noise_rng.gauss(0, noise)
        out.append(max(-1.0, min(1.0, v)))
    return audio.to_pcm(out)


def fingerprint_of(pcm: bytes) -> fpmod.Fingerprint:
    return fpmod.of(audio.for_fingerprint(pcm))


class Fingerprints(unittest.TestCase):
    def test_a_clip_matches_itself_far_above_a_different_tune(self):
        mine = fingerprint_of(tone_clip(1))
        postings = {}
        for value, when in mine.pairs:
            postings.setdefault(value, []).append(when)

        same = fpmod.score(fingerprint_of(tone_clip(1)), postings)
        other = fpmod.score(fingerprint_of(tone_clip(2)), postings)

        self.assertGreaterEqual(same, fpmod.MIN_SCORE)
        self.assertGreater(same, other * fpmod.MARGIN)

    def test_quieter_and_noisier_is_still_the_same_song(self):
        postings = {}
        for value, when in fingerprint_of(tone_clip(3)).pairs:
            postings.setdefault(value, []).append(when)
        quiet = fingerprint_of(tone_clip(3, gain=0.3, noise=0.004))
        self.assertGreaterEqual(fpmod.score(quiet, postings), fpmod.MIN_SCORE)

    def test_silence_produces_no_landmarks_to_match_on(self):
        silence = fpmod.of([0.0] * (fpmod.RATE * 2))
        self.assertEqual(silence.pairs, [])

    def test_the_offset_says_where_in_the_song_the_clip_came_from(self):
        whole = fingerprint_of(tone_clip(4, seconds=8))
        postings = {}
        for value, when in whole.pairs:
            postings.setdefault(value, []).append(when)
        later = fingerprint_of(tone_clip(4, seconds=3, start=4.0))
        score, offset = fpmod.best(later, postings)
        self.assertGreaterEqual(score, fpmod.MIN_SCORE)
        # Four seconds in, in frames, give or take a frame either way.
        self.assertAlmostEqual(offset, 4.0 * fpmod.RATE / fpmod.HOP, delta=2)


class Memory(unittest.TestCase):
    def test_a_learned_song_is_recognised_from_a_different_clip(self):
        with tempfile.TemporaryDirectory() as directory:
            memory = LearningMemory(Path(directory) / "memories.json")
            memory.learn("perfect", fingerprint_of(tone_clip(5, seconds=8)),
                         "Perfect", "Ed Sheeran")

            again = memory.recall(fingerprint_of(tone_clip(5, seconds=4, start=2.0)))

            self.assertIsNotNone(again)
            self.assertEqual(again.label, "Perfect")
            self.assertTrue(again.local)

    def test_a_tune_it_has_never_heard_is_not_claimed(self):
        with tempfile.TemporaryDirectory() as directory:
            memory = LearningMemory(Path(directory) / "memories.json")
            memory.learn("perfect", fingerprint_of(tone_clip(6)), "Perfect", "Ed Sheeran")
            self.assertIsNone(memory.recall(fingerprint_of(tone_clip(7))))

    def test_hearing_it_again_widens_what_is_remembered(self):
        """The point of the exercise: coverage grows with every hearing."""
        with tempfile.TemporaryDirectory() as directory:
            memory = LearningMemory(Path(directory) / "memories.json")
            memory.learn("song", fingerprint_of(tone_clip(8, seconds=4)), "Song")
            before = memory.recall(fingerprint_of(tone_clip(8, seconds=4, start=1.0)))
            memory.learn("song", fingerprint_of(tone_clip(8, seconds=4, start=4.0)), "Song")

            later = memory.recall(fingerprint_of(tone_clip(8, seconds=4, start=5.0)))

            self.assertIsNotNone(before)
            self.assertIsNotNone(later)   # a stretch it could not have placed before

    def test_it_survives_being_written_and_read_back(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "memories.json"
            first = LearningMemory(path)
            first.learn("perfect", fingerprint_of(tone_clip(9, seconds=6)),
                        "Perfect", "Ed Sheeran")

            reopened = LearningMemory(path)
            again = reopened.recall(fingerprint_of(tone_clip(9, seconds=4, start=1.0)))

            self.assertIsNotNone(again)
            self.assertEqual(again.label, "Perfect")

    def test_naming_a_tune_keeps_what_it_already_learned(self):
        with tempfile.TemporaryDirectory() as directory:
            memory = LearningMemory(Path(directory) / "memories.json")
            memory.learn("tune-1", fingerprint_of(tone_clip(10, seconds=8)), source="local")

            named = memory.rename("tune-1", "Perfect", "Ed Sheeran")
            found = memory.recall(fingerprint_of(tone_clip(10, seconds=4, start=2.0)))

            self.assertEqual(named.fingerprint, slug("Perfect", "Ed Sheeran"))
            self.assertIsNotNone(found)
            self.assertEqual(found.label, "Perfect")

    def test_slug_is_stable_and_readable(self):
        self.assertEqual(slug("Déjà Vu", "Beyoncé"), "deja-vu-beyonce")
        self.assertEqual(slug("Perfect", "Ed Sheeran"), "perfect-ed-sheeran")


class Listening(unittest.TestCase):
    def ears(self, directory, answers):
        memory = LearningMemory(Path(directory) / "memories.json")
        teacher = StaticSongTeacher(list(answers))
        return Ears(memory, teacher, rng=random.Random(1)), teacher, memory

    def test_unknown_is_asked_about_once_and_then_guessed_for_free(self):
        with tempfile.TemporaryDirectory() as directory:
            ears, teacher, _ = self.ears(directory, [Song("Perfect", "Ed Sheeran")])

            first = ears.hear(tone_clip(11, seconds=8))
            second = ears.hear(tone_clip(11, seconds=4, start=2.0))

            self.assertEqual(first.mode, "taught")
            self.assertTrue(first.asked)
            self.assertEqual(second.mode, "guess")
            self.assertFalse(second.asked)
            self.assertEqual(teacher.calls, 1)

    def test_a_tune_nobody_can_name_is_still_remembered(self):
        with tempfile.TemporaryDirectory() as directory:
            ears, _, memory = self.ears(directory, [None])

            first = ears.hear(tone_clip(12, seconds=8))
            second = ears.hear(tone_clip(12, seconds=4, start=2.0))

            self.assertEqual(first.mode, "stumped")
            self.assertEqual(len(memory), 1)
            # It knows it has met this before, even though it has no name.
            self.assertIsNotNone(second.answer)
            self.assertFalse(second.answer.named)

    def test_a_name_arriving_later_is_attached_to_the_tune_already_known(self):
        with tempfile.TemporaryDirectory() as directory:
            ears, _, memory = self.ears(directory, [None, Song("Perfect", "Ed Sheeran")])

            ears.hear(tone_clip(13, seconds=8))
            named = ears.hear(tone_clip(13, seconds=4, start=2.0))

            self.assertEqual(named.mode, "taught")
            self.assertEqual(named.answer.label, "Perfect")
            self.assertEqual(len(memory), 1)     # renamed, not duplicated

    def test_it_stops_asking_about_a_tune_nobody_can_name(self):
        with tempfile.TemporaryDirectory() as directory:
            ears, teacher, _ = self.ears(directory, [None])
            for _ in range(6):
                ears.hear(tone_clip(14, seconds=8))
            self.assertLessEqual(teacher.calls, 3)

    def test_the_ears_only_listen_once_armed(self):
        with tempfile.TemporaryDirectory() as directory:
            ears, _, _ = self.ears(directory, [Song("Perfect")])
            self.assertFalse(ears.armed)
            self.assertIsNone(ears.feed(tone_clip(15, seconds=4), now=0.0))
            ears.arm(True)
            self.assertTrue(ears.armed)

    def test_a_double_click_asks_without_waiting_for_the_gate(self):
        with tempfile.TemporaryDirectory() as directory:
            ears, _, _ = self.ears(directory, [Song("Perfect", "Ed Sheeran")])
            ears.ask_now()
            answer = ears.feed(tone_clip(16, seconds=4), now=0.0)
            self.assertIsNotNone(answer)
            self.assertEqual(answer.mode, "taught")


class Gate(unittest.TestCase):
    def test_silence_is_not_music(self):
        gate = audio.MusicGate()
        self.assertFalse(gate.feed([0.0] * audio.BOARD_RATE * 4))

    def test_a_loud_steady_signal_is_music(self):
        gate = audio.MusicGate()
        loud = audio.to_samples(tone_clip(17, seconds=4))
        self.assertTrue(gate.feed(loud))


class AudioMaths(unittest.TestCase):
    def test_pcm_round_trip(self):
        values = [0.0, 0.5, -0.5, 0.25]
        back = audio.to_samples(audio.to_pcm(values))
        for before, after in zip(values, back):
            self.assertAlmostEqual(before, after, places=3)

    def test_halving_averages_rather_than_dropping_samples(self):
        self.assertEqual(audio.resample([0.0, 1.0, 2.0, 3.0], 16000, 8000), [0.5, 2.5])

    def test_resampling_up_keeps_the_length_right(self):
        out = audio.resample([0.0] * 1600, 16000, 44100)
        self.assertAlmostEqual(len(out), 4410, delta=2)


class Bubble(unittest.TestCase):
    def test_a_familiar_song_is_greeted_differently_from_a_new_one(self):
        from learning.models import Recognition
        rng = random.Random(0)
        new = Recognition("k", "Perfect", "shazam", 0.5, True, "Ed Sheeran", 40, 1)
        old = Recognition("k", "Perfect", "shazam", 0.5, True, "Ed Sheeran", 40, 20)
        self.assertNotEqual(says.recalled(new, rng).mood,
                            says.recalled(old, rng).mood)

    def test_every_line_is_plain_ascii_and_fits_the_band(self):
        from learning.models import Recognition
        answer = Recognition("k", "Perfect", "shazam", 0.5, True, "Ed Sheeran", 40, 4)
        for utterance in (says.recalled(answer), says.learned(answer),
                          says.stumped(), says.listening()):
            text = says.fit(utterance.text)
            self.assertEqual(text, plain(text))
            self.assertLessEqual(len(text), says.WIDTH)


class StringPath(unittest.TestCase):
    """The older fingerprint-string API, which is still how /hear is driven."""

    def test_unknown_is_taught_then_recognized_locally(self):
        with tempfile.TemporaryDirectory() as directory:
            memory = LearningMemory(Path(directory) / "memories.json")
            app = LearningApp(memory, StaticTeacher({"song-1": "Perfect"}))

            taught = app.hear("song-1")
            guessed = app.hear("song-1")

            self.assertEqual(taught["mode"], "teach")
            self.assertEqual(taught["answer"]["source"], "teacher")
            self.assertEqual(guessed["mode"], "guess")
            self.assertTrue(guessed["answer"]["local"])

    def test_sugar_and_bitter_change_confidence(self):
        with tempfile.TemporaryDirectory() as directory:
            memory = LearningMemory(Path(directory) / "memories.json")
            app = LearningApp(memory, StaticTeacher({"song-1": "Perfect"}))
            app.hear("song-1")

            before = memory.lookup("song-1").confidence
            app.reward("song-1", "sugar")
            after_sugar = memory.lookup("song-1").confidence
            app.reward("song-1", "bitter")
            after_bitter = memory.lookup("song-1").confidence

            self.assertGreater(after_sugar, before)
            self.assertLess(after_bitter, after_sugar)


if __name__ == "__main__":
    unittest.main()
