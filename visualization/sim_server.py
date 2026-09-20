"""Serve the live brain: static files over HTTP, spikes over a WebSocket.

    python sim_server.py            # http://127.0.0.1:8010, ws://127.0.0.1:8011

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
import struct
import threading
import time
from pathlib import Path

import numpy as np
import websockets
from websockets.asyncio.server import serve

from live_engine import LiveBrain

HERE = Path(__file__).resolve().parent
PACK = HERE.parent / "research/drosophila-brain-mlx/data/pack/male_cns_v1"

HTTP_PORT = 8010
WS_PORT = 8011

# 10 ms of biological time per chunk: the bin the repository's own activity film
# uses, and about 8 ms of wall clock here, so the display keeps up.
CHUNK_TICKS = 100
DEFAULT_SPEED = 0.25          # 4x slow motion; the spread is too quick to read at 1.0

# label, what it is, the cell types to drive, default rate
STIMULI = {
    "sugar":  ("Sugar", "Sweet taste, right labellum. LB3b/LB3c are matched to "
                        "Gr64f sugar neurons.", ["LB3b_R", "LB3c_R"], 100.0),
    "water":  ("Water", "Water taste, right labellum.", ["LB3a_R"], 100.0),
    "smell":  ("Smell", "Olfactory receptor neurons of glomerulus DM1, right antenna.",
               ["ORN_DM1_R"], 100.0),
    "looming": ("Looming", "LC4 visual projection neurons, right eye: an approaching object.",
                ["LC4_R"], 100.0),
}
READOUTS = {
    "MN9_L": ["MN9_L"],       # proboscis extension, left
    "MN9_R": ["MN9_R"],       # proboscis extension, right
    "DNp01": ["DNp01"],       # the giant fibers, escape
}


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

    def request(self, key: str, ms: float, rate: float | None) -> None:
        with self._lock:
            self._pending.append((key, ms, rate))

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

    def hello(self) -> str:
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
                         "size": s.size, "rateHz": s.rate_hz}
                        for s in self.brain.stimuli.values()],
        })


async def main() -> None:
    print("loading the connectome ...")
    t0 = time.perf_counter()
    sim = Simulation()
    print(f"  ready in {time.perf_counter() - t0:.1f}s")

    loop = asyncio.get_running_loop()
    clients: set = set()
    latest: asyncio.Queue = asyncio.Queue(maxsize=1)

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

    async def broadcast() -> None:
        while True:
            buf = await latest.get()
            if clients:
                await asyncio.gather(*(c.send(buf) for c in list(clients)),
                                     return_exceptions=True)

    async def handler(ws) -> None:
        clients.add(ws)
        print(f"client connected ({len(clients)} now)")
        try:
            await ws.send(sim.hello())
            async for raw in ws:
                try:
                    msg = json.loads(raw)
                except (ValueError, TypeError):
                    continue
                cmd = msg.get("cmd")
                if cmd == "trigger":
                    sim.request(msg.get("key", ""), float(msg.get("ms", 500)),
                                msg.get("hz"))
                elif cmd == "reset":
                    sim.request_reset()
                elif cmd == "speed":
                    sim.speed = max(0.01, min(4.0, float(msg.get("value", DEFAULT_SPEED))))
        except websockets.exceptions.ConnectionClosed:
            pass
        finally:
            clients.discard(ws)
            print(f"client gone ({len(clients)} left)")

    threading.Thread(target=worker, daemon=True).start()
    asyncio.create_task(broadcast())

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
    print(f"  {len(STIMULI)} stimuli: {', '.join(STIMULI)}\n")

    async with serve(handler, "127.0.0.1", WS_PORT, max_queue=1):
        await asyncio.Future()


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        print("\nstopped")
