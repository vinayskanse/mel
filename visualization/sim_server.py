"""Serve the whole fly: the brain, its ears, the page, and the board.

    python sim_server.py            # http://127.0.0.1:8010, ws://127.0.0.1:8011

One process, because one fly. The connectome steps here, the listening runs
here, and the board is talked to from here -- so when memory names a song, the
auditory neurons are driven, the page narrates it and the face on the desk
changes, all from a single decision and without any of the four asking each
other for it. `learning/events.py` is the notice board they share, and
`reactions.py` is the table that says what each notice means.

Nothing in this file adds a network call. The listening still asks Shazam at
most once per song in its life, exactly as `learning/README.md` describes; the
page holds one WebSocket and no more; the board holds one socket and is not
polled.

The simulation runs on a worker thread because every MLX call blocks, and hands
finished chunks to the asyncio loop through a queue of depth one: if the browser
falls behind, frames are dropped rather than queued, so what is on screen is
always the most recent brain state rather than a growing backlog.

Wire format. Control messages are JSON, in both directions. Spike frames are
binary, little endian, because a busy chunk names several thousand neurons and
JSON would spend most of the bandwidth on commas:

    float32  t_bio        biological seconds since reset
    float32  wall_ms      what the chunk cost to compute
    float32  bio_ms       how much brain time it covered
    uint32   n_firing     neurons with at least one spike, of those drawn
    uint32   n_spikes     total spikes in the chunk, including undrawn neurons
    uint32   n_readouts
    float32  readouts[n_readouts]      in the order given in the hello message
    uint32   point[n_firing]           index into the soma point cloud
    uint8    count[n_firing]           spikes in this chunk, saturating at 255
"""

from __future__ import annotations

import asyncio
import functools
import json
import os
import struct
import sys
import threading
import time
from pathlib import Path

import numpy as np
import websockets
from websockets.asyncio.server import serve

from device import DeviceLink
from flystate import Fly, bridge
from live_engine import LiveBrain

HERE = Path(__file__).resolve().parent
PACK = HERE.parent / "research/drosophila-brain-mlx/data/pack/male_cns_v1"

HTTP_PORT = 8010
WS_PORT = 8011

# 10 ms of biological time per chunk: the bin the repository's own activity film
# uses, and about 8 ms of wall clock here, so the display keeps up.
CHUNK_TICKS = 100
DEFAULT_SPEED = 0.25          # 4x slow motion; the spread is too quick to read at 1.0

# label, what it is, the cell types to drive, default rate.
#
# A selector may be a list of names, or a list of alternative lists tried in
# order -- see LiveBrain._resolve. The four original buttons name cells that
# context/circuits.md verified against this pack. The two added for the ears
# and the feedback name cells from the literature instead, so they are written
# as candidates and are dropped rather than fatal if this pack spells them
# differently. `python find_types.py JO` says what it actually has.
STIMULI = {
    "sugar":  ("Sugar", "Sweet taste, right labellum. LB3b/LB3c are matched to "
                        "Gr64f sugar neurons.", ["LB3b_R", "LB3c_R"], 100.0),
    "water":  ("Water", "Water taste, right labellum.", ["LB3a_R"], 100.0),
    "smell":  ("Smell", "Olfactory receptor neurons of glomerulus DM1, right antenna.",
               ["ORN_DM1_R"], 100.0),
    "looming": ("Looming", "LC4 visual projection neurons, right eye: an approaching object.",
                ["LC4_R"], 100.0),
    # The ear. A fly hears with its antennae: sound vibrates the arista and
    # Johnston's organ transduces it, which is the organ that hears courtship
    # song. JO-B is the sub-population tuned to it. Failing that, AMMC-A1 --
    # which context/circuits.md found in this pack -- is one synapse further
    # in, in the antennal mechanosensory and motor centre where JO terminates.
    # Second-order, so the panel says "auditory" rather than "the ear itself".
    "sound":  ("Sound", "Johnston's organ, the fly's ear: the antennal receptor that "
                        "hears courtship song. Driven when the fly hears music.",
               # Right side first, to match the four above -- all of which drive
               # one side, which is what makes the lateralisation in
               # context/circuits.md legible. Whole-type fallbacks after, so a
               # pack that does not split JO-B by side still gets an ear.
               [["JO-B_R"], ["JO-B"], ["JO-A_R"], ["JO-A"],
                ["AMMC-A1_R"], ["AMMC-A1"]], 100.0),
    # Bitter. Named on the same reading of the labellar sensilla that gives
    # LB3a/b/c above, but not verified against this pack, so it is very likely
    # to be dropped at load. That is the intended behaviour: see _reward in
    # reactions.py for what a thumbs-down does without it.
    "bitter": ("Bitter", "Bitter-sensing receptor neurons of the right labellum.",
               [["LB1e_R", "LB2e_R"], ["Gr66a_R"], ["Gr66a"]], 100.0),
}
READOUTS = {
    "MN9_L": ["MN9_L"],       # proboscis extension, left
    "MN9_R": ["MN9_R"],       # proboscis extension, right
    "DNp01": ["DNp01"],       # the giant fibers, escape
}

# How long the page should be told a stimulus lasted, when something other than
# a button press fired it. The page uses it only to time its own narration.
DEFAULT_MS = 500.0
DEVICE_SPEED = 0.05            # 20x slow motion for a physical Sugar feed


def soma_point_of(neuron_ids: np.ndarray, soma_ids_path: Path) -> np.ndarray:
    """int32[N]: each model neuron's index in the soma point cloud, or -1.

    The viewer draws 124,314 of the connectome's 166,700 neurons -- the ones with
    a soma position inside the brain ROI box. The rest still spike and still
    count; they simply have nowhere to be drawn.
    """
    soma = np.load(soma_ids_path).astype(np.int64)
    order = np.argsort(soma)
    ids = np.asarray(neuron_ids, dtype=np.int64)
    at = np.searchsorted(soma[order], ids)
    ok = at < soma.size
    hit = np.zeros(ids.size, dtype=bool)
    hit[ok] = soma[order][at[ok]] == ids[ok]
    out = np.full(ids.size, -1, dtype=np.int32)
    out[hit] = order[at[hit]]
    return out


class Simulation:
    def __init__(self):
        self.brain = LiveBrain(PACK, STIMULI, READOUTS, edge_split=1)
        self.point_of = soma_point_of(self.brain.pack.neuron_ids,
                                      HERE / "data/soma_body_ids.npy")
        self.drawn = self.point_of >= 0

        # The indices sent over the wire address the browser's point cloud, so
        # the two must have been built from the same somas.bin. Rebuilding the
        # cloud without restarting here would light the wrong neurons -- silently,
        # since every index would still be in range. The count is sent in the
        # hello message and the page refuses to run on a mismatch.
        self.n_points = int(json.loads((HERE / "data/somas.json").read_text())["count"])
        top = int(self.point_of.max())
        if top >= self.n_points:
            raise SystemExit(f"soma_body_ids.npy indexes point {top} but somas.json "
                             f"declares {self.n_points}; rebuild both with build_somas.py")
        self.speed = DEFAULT_SPEED
        self.running = True
        self._pending: list[tuple] = []          # (key, ms, rate) from the browser
        self._lock = threading.Lock()
        print(f"  {self.drawn.sum():,} of {len(self.point_of):,} neurons map onto a soma point")

    def request(self, key: str, ms: float, rate: float | None = None) -> bool:
        """Queue a drive. False if this pack has no such stimulus, so a caller
        that cares -- the event bridge does -- can say so instead of pretending."""
        if key not in self.brain.stimuli:
            return False
        with self._lock:
            self._pending.append((key, ms, rate))
        return True

    def request_reset(self) -> None:
        with self._lock:
            self._pending.append((None, 0, None))

    def _apply_pending(self) -> None:
        with self._lock:
            pending, self._pending = self._pending, []
        for key, ms, rate in pending:
            if key is None:
                self.brain.reset()
            elif key in self.brain.stimuli:
                self.brain.trigger(key, ms, rate)

    def frame(self) -> bytes:
        self._apply_pending()
        per_neuron, wall = self.brain.step(CHUNK_TICKS)

        total = int(per_neuron.sum())
        # (per_neuron > 0), not per_neuron itself: a bitwise and against the
        # boolean mask would keep only the low bit of the count, so a neuron
        # that fired exactly twice in the chunk would silently disappear.
        fired = np.flatnonzero((per_neuron > 0) & self.drawn)
        points = self.point_of[fired].astype("<u4")
        counts = per_neuron[fired].astype(np.uint8)
        rates = self.brain.rates(per_neuron, CHUNK_TICKS)
        bio_ms = CHUNK_TICKS * 0.1

        head = struct.pack("<fffIII", self.brain.t_bio, wall * 1000, bio_ms,
                           len(fired), total, len(READOUTS))
        body = struct.pack(f"<{len(READOUTS)}f", *(rates[k] for k in READOUTS))
        return head + body + points.tobytes() + counts.tobytes()

    def hello(self, fly: dict) -> str:
        return json.dumps({
            "type": "hello",
            "neurons": int(self.brain.pack.n_neurons),
            "edges": int(self.brain.pack.n_edges),
            "drawn": int(self.drawn.sum()),
            "points": self.n_points,
            "chunkTicks": CHUNK_TICKS,
            "dtMs": 0.1,
            "speed": self.speed,
            "readouts": list(READOUTS),
            "stimuli": [{"key": s.key, "label": s.label, "description": s.description,
                         "size": s.size, "rateHz": s.rate_hz, "types": s.types}
                        for s in self.brain.stimuli.values()],
            "dropped": sorted(self.brain.missing),
            "fly": fly,
        })


def start_learning(fly: Fly):
    """Bring the ears up in this process, if the package will import.

    Returns the LearningApp, or None with a printed reason. The simulator is
    the point of this program and must start without ffmpeg, without a key and
    without a microphone, so every failure here is survivable.
    """
    try:
        sys.path.insert(0, str(HERE.parent))
        from learning.ears import Ears
        from learning.memory import LearningMemory
        from learning.providers import ShazamTeacher
        from learning.providers import StaticTeacher
        from learning.service import (LearningApp, Server, make_handler,
                                      make_song_handler)
    except ImportError as error:
        print(f"  ears: learning package will not import ({error}); "
              "the brain runs without them")
        return None

    from http.server import ThreadingHTTPServer

    path = Path(os.environ.get("FLY_MEMORY", HERE.parent / "learning/data/memories.json"))
    port = int(os.environ.get("FLY_PORT", "8020"))
    memory = LearningMemory(path)
    shazam = ShazamTeacher.from_env()
    ears = Ears(memory, shazam)
    # StaticTeacher, not the Shazam one: /hear is the string-keyed path and
    # has no audio to send anywhere. The ears hold the teacher that can ask.
    app = LearningApp(memory, StaticTeacher({}), ears)

    try:
        songs = Server(("0.0.0.0", port + 1), make_song_handler(app))
        threading.Thread(target=songs.serve_forever, daemon=True).start()
        http = ThreadingHTTPServer(("0.0.0.0", port), make_handler(app))
        threading.Thread(target=http.serve_forever, daemon=True).start()
    except OSError as error:
        print(f"  ears: port {port} busy ({error}); is learning.service already running?")
        return None

    fly.available = True
    fly.songs = len(memory)
    print(f"  ears: {len(memory)} songs remembered, HTTP on {port}, board audio on {port + 1}"
          + ("" if shazam.ready else "  (no SHAZAM_API_KEY: guesses only, never asks)"))
    return app


async def main() -> None:
    print("loading the connectome ...")
    t0 = time.perf_counter()
    sim = Simulation()
    print(f"  ready in {time.perf_counter() - t0:.1f}s")

    fly = Fly()
    app = start_learning(fly)

    loop = asyncio.get_running_loop()
    clients: set = set()
    latest: asyncio.Queue = asyncio.Queue(maxsize=1)
    control: asyncio.Queue = asyncio.Queue(maxsize=64)

    def push(obj: dict) -> None:
        """Send a JSON message to every page, from any thread.

        Spike frames are dropped under load because a stale one is worthless;
        these are not, because each one is a thing that happened. The queue is
        bounded anyway, and a full one drops the oldest -- a page that has been
        unresponsive for sixty messages has bigger problems than a lost line of
        narration.
        """
        def deliver() -> None:
            if control.full():
                try:
                    control.get_nowait()
                except asyncio.QueueEmpty:
                    pass
            try:
                control.put_nowait(json.dumps(obj))
            except asyncio.QueueFull:
                pass
        try:
            loop.call_soon_threadsafe(deliver)
        except RuntimeError:            # the loop is closing
            pass

    def device_event(event: str) -> None:
        if event == "feed" and sim.request("sugar", DEFAULT_MS):
            # A button on the buddy is a presentation, not a quick control
            # adjustment: slow the running brain to 1/20 real-time so its
            # Sugar pathway can be followed on the screen.
            sim.speed = DEVICE_SPEED
            push({"type": "fired", "key": "sugar", "ms": DEFAULT_MS,
                  # A physical feed is the presentation trigger.  It must not
                  # be hidden by a previously disabled auto-trace checkbox or
                  # an open manual pathway view in the browser.
                  "source": "device", "trace": True, "speed": DEVICE_SPEED})

    link = DeviceLink(on_event=device_event)
    link.start()

    if app is not None:
        from learning.events import bus
        bus.subscribe(bridge(sim, link, fly, push))

    def worker() -> None:
        """Step forever on a thread; MLX blocks, so it cannot share the loop.

        Hands each frame over with call_soon_threadsafe: asyncio queues are not
        thread-safe, and put_nowait straight from here would race the loop.
        """
        while sim.running:
            if not clients:
                time.sleep(0.05)
                continue
            start = time.perf_counter()
            buf = sim.frame()
            loop.call_soon_threadsafe(_offer, buf)
            target = (CHUNK_TICKS * 0.1 / 1000.0) / max(sim.speed, 0.01)
            time.sleep(max(0.0, target - (time.perf_counter() - start)))

    def _offer(buf: bytes) -> None:
        if latest.full():
            try:
                latest.get_nowait()
            except asyncio.QueueEmpty:
                pass
        try:
            latest.put_nowait(buf)
        except asyncio.QueueFull:
            pass

    async def send_all(payload) -> None:
        if clients:
            await asyncio.gather(*(c.send(payload) for c in list(clients)),
                                 return_exceptions=True)

    async def broadcast() -> None:
        while True:
            await send_all(await latest.get())

    async def broadcast_control() -> None:
        while True:
            await send_all(await control.get())

    def fly_command(msg: dict) -> dict:
        """The page's half of the ears. Called in-process, not over HTTP: the
        learning service's own endpoints are still there for anything else on
        the desk, but the page is already holding a socket to this program and
        a second round trip to localhost would buy nothing."""
        if app is None or app.ears is None:
            return {"error": "no ears in this process"}
        action = msg.get("action")
        if action == "listen":
            app.ears.arm(bool(msg.get("on", True)))
            return {"armed": app.ears.armed}
        if action == "identify":
            app.ears.ask_now()
            return {"armed": True}
        if action == "reward":
            key = msg.get("fingerprint") or fly.fingerprint
            if not key:
                return {"error": "the fly has not heard anything to be right about yet"}
            try:
                return app.reward(key, msg.get("reward", "sugar"))
            except (KeyError, ValueError) as error:
                return {"error": str(error)}
        return {"error": f"unknown fly action {action!r}"}

    async def handler(ws) -> None:
        clients.add(ws)
        print(f"client connected ({len(clients)} now)")
        try:
            await ws.send(sim.hello(fly.as_dict()))
            async for raw in ws:
                try:
                    msg = json.loads(raw)
                except (ValueError, TypeError):
                    continue
                cmd = msg.get("cmd")
                if cmd == "trigger":
                    key, ms = msg.get("key", ""), float(msg.get("ms", DEFAULT_MS))
                    if sim.request(key, ms, msg.get("hz")):
                        # Echoed to every page, not just the one that clicked,
                        # so a second screen narrates and traces the same press.
                        push({"type": "fired", "key": key, "ms": ms, "source": "button"})
                elif cmd == "reset":
                    sim.request_reset()
                elif cmd == "speed":
                    sim.speed = max(0.01, min(4.0, float(msg.get("value", DEFAULT_SPEED))))
                elif cmd == "fly":
                    result = fly_command(msg)
                    await ws.send(json.dumps({"type": "flyAck", "action": msg.get("action"),
                                              **result}))
        except websockets.exceptions.ConnectionClosed:
            pass
        finally:
            clients.discard(ws)
            print(f"client gone ({len(clients)} left)")

    threading.Thread(target=worker, daemon=True).start()
    asyncio.create_task(broadcast())
    asyncio.create_task(broadcast_control())

    # Static files, so the page and the socket come from one process.
    from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer

    class Quiet(SimpleHTTPRequestHandler):
        def log_message(self, *a):  # the access log drowns the simulation's
            pass

    httpd = ThreadingHTTPServer(
        ("127.0.0.1", HTTP_PORT),
        functools.partial(Quiet, directory=str(HERE)))
    threading.Thread(target=httpd.serve_forever, daemon=True).start()

    print(f"\n  page    http://127.0.0.1:{HTTP_PORT}")
    print(f"  socket  ws://127.0.0.1:{WS_PORT}")
    print(f"  board   tcp {link.port}, found by udp broadcast on {link.beacon_port}")
    print(f"  {len(sim.brain.stimuli)} stimuli: {', '.join(sim.brain.stimuli)}"
          + (f"  (dropped: {', '.join(sim.brain.missing)})" if sim.brain.missing else "")
          + "\n")

    async with serve(handler, "0.0.0.0", WS_PORT, max_queue=1):
        await asyncio.Future()


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        print("\nstopped")
