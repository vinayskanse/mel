"""The join between the ears, the brain and the board, checked without either.

`sim_server.py` cannot be imported on a machine without MLX and the pack, so
none of the rules it depends on could be tested there. They live in
`reactions.py`, `flystate.py` and `device.py` instead, and this exercises them
against a fake simulator and a fake board.

    python -m unittest discover -s visualization -p 'test_*.py'
"""

from __future__ import annotations

import sys
import unittest
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
sys.path.insert(0, str(HERE.parent))

import device
import reactions
from flystate import Fly, bridge


class FakeSim:
    """A simulator that has some stimuli and remembers what it was asked for."""

    def __init__(self, have=("sugar", "water", "smell", "looming", "sound")):
        self.have = set(have)
        self.drives: list[tuple[str, float]] = []

    def request(self, key: str, ms: float, rate=None) -> bool:
        if key not in self.have:
            return False
        self.drives.append((key, ms))
        return True


class FakeLink(device.DeviceLink):
    """The real line-building, without a socket under it."""

    def __init__(self):
        super().__init__(announce=False)
        self.started = True
        self.sent: list[str] = []

    def _send(self, lines, remember=None):
        if remember is not None:
            self._state = remember
        self.sent.extend(lines)


def wire(have=("sugar", "water", "smell", "looming", "sound")):
    sim, link, fly, seen = FakeSim(have), FakeLink(), Fly(), []
    return sim, link, fly, seen, bridge(sim, link, fly, seen.append)


HEARD_KNOWN = {"kind": "heard", "mode": "guess", "asked": False,
               "say": {"text": "that's Perfect", "mood": "DANCING"},
               "answer": {"fingerprint": "perfect-ed-sheeran", "label": "Perfect",
                          "artist": "Ed Sheeran", "heard": 5}}


class TestReactions(unittest.TestCase):
    def test_every_mood_is_one_the_firmware_has(self):
        """A face invented here would be sent and silently ignored on the board."""
        events = [
            {"kind": "listening", "armed": True}, {"kind": "listening", "armed": False},
            {"kind": "music"}, {"kind": "identify"}, {"kind": "quiet"},
            HEARD_KNOWN,
            {"kind": "heard", "mode": "taught", "answer": {"label": "X", "heard": 1}},
            {"kind": "heard", "mode": "stumped", "answer": None},
            {"kind": "reward", "reward": "sugar", "answer": {"label": "X"}},
            {"kind": "reward", "reward": "bitter", "answer": {"label": "X"}},
        ]
        for event in events:
            with self.subTest(event=event):
                mood = reactions.react(event).mood
                self.assertTrue(mood == "" or mood in device.MOODS, mood)

    def test_a_thumbs_up_is_a_real_sweet_reward(self):
        """Not a flag, not a mood: the 17 labellar sugar cells, and a crumb."""
        r = reactions.react({"kind": "reward", "reward": "sugar",
                             "answer": {"label": "Perfect"}})
        self.assertEqual(r.stimulus, "sugar")
        self.assertGreater(r.ms, 0)
        self.assertEqual(r.mood, "EATING")
        self.assertTrue(r.feed)

    def test_a_thumbs_down_drives_nothing(self):
        """No bitter receptor is identified in this pack, so nothing is claimed."""
        r = reactions.react({"kind": "reward", "reward": "bitter",
                             "answer": {"label": "Perfect"}})
        self.assertEqual(r.stimulus, "")
        self.assertEqual(r.mood, "ANGRY")
        self.assertFalse(r.feed)

    def test_familiarity_changes_the_face_not_the_brain(self):
        """A song heard twenty times gets a different face and the same ear."""
        once = reactions.react({"kind": "heard", "mode": "guess",
                                "answer": {"label": "X", "heard": 1}})
        often = reactions.react({"kind": "heard", "mode": "guess",
                                 "answer": {"label": "X", "heard": 20}})
        self.assertEqual(once.mood, "EXCITED")
        self.assertEqual(often.mood, "DANCING")
        self.assertEqual(once.stimulus, often.stimulus)

    def test_an_unknown_event_does_nothing_at_all(self):
        self.assertTrue(reactions.react({"kind": "birthday"}).empty)


class TestBridge(unittest.TestCase):
    def test_recognising_a_song_drives_the_ear_and_shows_the_title(self):
        sim, link, fly, seen, on_event = wire()
        on_event(HEARD_KNOWN)
        self.assertEqual([k for k, _ in sim.drives], ["sound"])
        self.assertEqual((fly.title, fly.artist), ("Perfect", "Ed Sheeran"))
        self.assertEqual(fly.mood, "DANCING")
        self.assertIn("SAY that's Perfect", link.sent)
        self.assertIn("SUB Ed Sheeran", link.sent)
        self.assertEqual([m["type"] for m in seen], ["fly", "fired"])

    def test_a_thumbs_up_reaches_the_sugar_pathway_and_the_crumb(self):
        sim, link, fly, seen, on_event = wire()
        on_event(HEARD_KNOWN)
        sim.drives.clear(); link.sent.clear(); seen.clear()
        on_event({"kind": "reward", "reward": "sugar",
                  "answer": {"fingerprint": "perfect-ed-sheeran", "label": "Perfect"}})
        self.assertEqual([k for k, _ in sim.drives], ["sugar"])
        self.assertIn("FEED", link.sent)
        self.assertIn("MOOD EATING 0.0", link.sent)
        self.assertEqual([m["type"] for m in seen], ["fly", "fired"])
        self.assertEqual(seen[1]["key"], "sugar")

    def test_a_reward_does_not_wipe_the_song_off_the_fly(self):
        """The bubble is what the fly is showing, and being told it was right
        about a song does not change which song it was."""
        sim, link, fly, seen, on_event = wire()
        on_event(HEARD_KNOWN)
        link.sent.clear()
        on_event({"kind": "reward", "reward": "sugar", "answer": {"label": "Perfect"}})
        self.assertFalse([ln for ln in link.sent if ln.startswith("SAY")])
        self.assertEqual(fly.title, "Perfect")

    def test_a_thumbs_up_still_knows_which_song(self):
        """The key comes from the last hearing, so the page never has to send it."""
        sim, link, fly, seen, on_event = wire()
        on_event(HEARD_KNOWN)
        self.assertEqual(fly.fingerprint, "perfect-ed-sheeran")
        on_event({"kind": "heard", "mode": "stumped", "answer": None, "say": {}})
        self.assertEqual(fly.fingerprint, "perfect-ed-sheeran")

    def test_a_missing_stimulus_is_reported_not_faked(self):
        """A pack without Johnston's organ still hears; it just cannot show it."""
        sim, link, fly, seen, on_event = wire(have=("sugar",))
        on_event(HEARD_KNOWN)
        self.assertEqual(sim.drives, [])
        self.assertEqual([m["type"] for m in seen], ["fly"])     # no `fired`
        self.assertFalse(seen[0]["fired"])
        self.assertEqual(seen[0]["reaction"]["stimulus"], "sound")

    def test_the_music_stopping_lets_the_face_go(self):
        sim, link, fly, seen, on_event = wire()
        on_event(HEARD_KNOWN)
        link.sent.clear()
        on_event({"kind": "quiet", "say": {"text": ""}})
        self.assertIn("AUTO", link.sent)
        self.assertIn("SAY ", link.sent)
        self.assertEqual((fly.title, fly.artist), ("", ""))

    def test_a_board_with_no_link_started_is_simply_not_talked_to(self):
        sim, link, fly, seen, on_event = wire()
        link.started = False
        on_event(HEARD_KNOWN)
        self.assertEqual(link.sent, [])
        self.assertEqual(len(seen), 2)      # the page still hears about it


class TestDeviceLines(unittest.TestCase):
    def test_a_late_board_is_caught_up_on_state_but_not_on_events(self):
        link = FakeLink()
        link.apply(reactions.react(HEARD_KNOWN), say="that's Perfect", sub="Ed Sheeran")
        link.apply(reactions.react({"kind": "reward", "reward": "sugar",
                                    "answer": {"label": "Perfect"}}))
        self.assertIn("MOOD EATING 0.0", link._state)
        self.assertIn("SAY that's Perfect", link._state)
        self.assertNotIn("FEED", link._state)

    def test_going_back_to_auto_forgets_the_held_face(self):
        link = FakeLink()
        link.apply(reactions.react(HEARD_KNOWN), say="hi", sub="")
        link.apply(reactions.react({"kind": "quiet"}), say="", sub="")
        self.assertFalse([ln for ln in link._state if ln.startswith("MOOD")])
        self.assertIn("AUTO", link._state)

    def test_a_face_the_firmware_lacks_is_refused_here(self):
        class Wrong:
            mood, hold, feed, auto = "ECSTATIC", 0.0, False, False
        with self.assertRaises(ValueError):
            FakeLink().apply(Wrong())

    def test_the_bubble_is_ascii_and_short(self):
        """The band is 240 px of a font with no accents; cutting here rather
        than on the board means the log shows what the fly is showing."""
        self.assertEqual(device._clean("Naïve — Café"), "Nave  Caf")
        long = device._clean("x" * 80)
        self.assertLessEqual(len(long), 40)
        self.assertTrue(long.endswith("~"))


class TestBus(unittest.TestCase):
    def test_one_broken_listener_does_not_stop_the_others(self):
        from learning.events import EventBus
        bus, got = EventBus(), []
        bus.subscribe(lambda e: (_ for _ in ()).throw(RuntimeError("boom")))
        bus.subscribe(got.append)
        bus.publish("heard", mode="guess")
        self.assertEqual(len(got), 1)
        self.assertEqual(got[0]["kind"], "heard")

    def test_unsubscribing_stops_delivery(self):
        from learning.events import EventBus
        bus, got = EventBus(), []
        drop = bus.subscribe(got.append)
        bus.publish("a")
        drop()
        bus.publish("b")
        self.assertEqual([e["kind"] for e in got], ["a"])


if __name__ == "__main__":
    unittest.main()
