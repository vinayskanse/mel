"""A resumable lane over the fused Metal kernels, for driving a live display.

`engine_fused.run` materialises the whole stimulus up front and builds fresh
state inside the call, which is what makes its parity testable but also means it
cannot be stopped and continued. A live panel needs the opposite: state that
persists between calls so a button pressed now lands on the brain the last chunk
left behind.

This wraps the same two kernels -- `engine_metal.propagate` and
`engine_fused._state_kernel` -- in the same order, rather than reimplementing the
tick. The arithmetic is therefore the benchmarked lane's arithmetic; what differs
is only who owns the state and where the Poisson draws come from.

Two deliberate differences from the published model, both consequences of a drive
that can be switched on and off mid-run:

  * `rfc_reload` is rebuilt whenever the driven set changes. model.py sets it to
    zero for the run's Poisson targets once, so a driven neuron is never
    refractory; here a neuron is exempt only while it is actually being driven,
    and returns to the normal 2.2 ms refractory period when its stimulus stops.
  * Draws are generated per chunk from a numpy Generator, not from the one
    pre-materialised bit pattern a parity test needs. Runs are reproducible for a
    given seed and button-press schedule, but a schedule typed by hand is not.

Neither changes the tick body, so a run with a constant drive matches the fused
lane's behaviour; they matter only across a change of stimulus.
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field

import mlx.core as mx
import numpy as np

from lif import core, names
from lif.engine_fused import _state_kernel
from lif.engine_metal import propagate, silenced_row_end


@dataclass
class Stimulus:
    """A named set of neurons that a button can drive."""

    key: str
    label: str
    description: str
    indices: np.ndarray          # model indices
    rate_hz: float = 100.0
    until: float = 0.0           # biological seconds; the drive stops at this time
    slots: np.ndarray = field(default=None, repr=False)   # its columns in the draw matrix
    types: list = field(default_factory=list)             # the names that matched, for the panel

    @property
    def size(self) -> int:
        return len(self.indices)


class LiveBrain:
    """The connectome, stepping in chunks, with a drive that can change mid-run."""

    def __init__(self, pack_dir, stimuli: dict[str, tuple[str, str, list[str], float]],
                 readouts: dict[str, list[str]], edge_split: int = 1, seed: int = 0):
        self.pack = core.load_pack(pack_dir)
        self.names = names.load(self.pack)
        if self.names is None:
            raise SystemExit("pack has no names sidecar; run "
                             "python -m lif.compile_pack_malecns --names-only")
        self.rng = np.random.default_rng(seed)
        N = self.pack.n_neurons

        # ---- stimuli ------------------------------------------------------
        # Every neuron any button can drive gets a permanent column in the draw
        # matrix, so the kernel's target_slot map is built once. A stimulus that
        # is off simply draws zeros into its columns.
        self.stimuli: dict[str, Stimulus] = {}
        self.missing: dict[str, list] = {}
        target_list: list[int] = []
        claimed: set[int] = set()
        for key, (label, desc, sel, rate) in stimuli.items():
            idx, used = self._resolve(sel)
            if not idx:
                # A stimulus whose cell types this pack does not carry is
                # dropped, not fatal. The table in sim_server names the
                # auditory and bitter cells on a reading of the literature
                # rather than from this pack's own annotations, and a pack
                # that spells one of them differently should cost that one
                # button, not the whole brain.
                self.missing[key] = list(sel)
                print(f"  stimulus {key!r}: no neurons match {sel}; dropped")
                continue
            if claimed.intersection(idx):
                # One stimulus slot per neuron is a kernel constraint, not a
                # preference: target_slot maps each neuron to exactly one
                # column of the draw matrix.
                self.missing[key] = list(sel)
                print(f"  stimulus {key!r}: its neurons are already driven by "
                      f"another stimulus; dropped")
                continue
            claimed.update(idx)
            slots = np.arange(len(target_list), len(target_list) + len(idx), dtype=np.int32)
            target_list.extend(idx)
            self.stimuli[key] = Stimulus(key, label, desc, np.array(idx, np.int32),
                                         rate, slots=slots, types=used)

        if not self.stimuli:
            raise SystemExit("no stimulus resolved to any neuron; check the pack's names sidecar")
        self.targets = targets = np.array(target_list, dtype=np.int32)
        self.n_slots = len(targets)

        slot = np.full(N, -1, dtype=np.int32)
        slot[targets] = np.arange(self.n_slots, dtype=np.int32)
        self.target_slot = mx.array(slot)

        # ---- readouts -----------------------------------------------------
        self.readouts = {k: np.array(sorted({i for n in sel for i in self.names.select(n)}),
                                     dtype=np.int32)
                         for k, sel in readouts.items()}

        # ---- constants and fixed kernel inputs ----------------------------
        cf = core.constants_f32()
        self.k = {f"c_{n}": mx.array([float(cf[n])], dtype=mx.float32)
                  for n in ("v0_term", "couple_g", "decay_v", "decay_g", "v_th",
                            "w_syn", "w_ext", "v_0")}
        self.n_neurons = mx.array([N], dtype=mx.uint32)
        self.n_src = mx.array([N], dtype=mx.uint32)
        self.row_end = silenced_row_end(self.pack, None)
        self.edge_split = edge_split

        self.tick = 0
        self._driven_key = None
        self.reset()

    def _resolve(self, sel) -> tuple[list[int], list[str]]:
        """Model indices for a selector, and which names actually produced them.

        A selector is a list of cell-type names, or a list of such lists. The
        list-of-lists form is "try these, then those": it is how a stimulus can
        name the receptor it would rather drive and the second-order cell it
        will settle for, and have the pack decide which of the two it has. The
        first group that matches anything wins outright -- a partial match is
        still that group's answer, so a pack carrying JO-B_R but not JO-B_L
        drives one side rather than silently falling through to the next group.
        """
        groups = sel if sel and isinstance(sel[0], (list, tuple)) else [sel]
        for group in groups:
            hits = {i for name in group for i in self.names.select(name)}
            if hits:
                used = [n for n in group if self.names.select(n)]
                return sorted(hits), used
        return [], []

    # ---- state ------------------------------------------------------------
    def reset(self) -> None:
        N = self.pack.n_neurons
        self.v = mx.full((N,), core.V_0, dtype=mx.float32)
        self.g = mx.zeros((N,), dtype=mx.float32)
        self.rfc = mx.zeros((N,), dtype=mx.int32)
        self.counts = mx.zeros((N,), dtype=mx.int32)
        self.ring = [mx.zeros((N,), dtype=mx.uint8) for _ in range(core.DELAY_TICKS)]
        self.tick = 0
        for s in self.stimuli.values():
            s.until = 0.0
        self._set_rfc_reload(frozenset())
        mx.eval(self.v, self.g, self.rfc, self.counts, *self.ring)

    def _set_rfc_reload(self, driven: frozenset[str]) -> None:
        """Poisson targets are exempt from the refractory period, as model.py has
        it -- but only the ones actually being driven right now."""
        if driven == self._driven_key:
            return
        rl = np.full(self.pack.n_neurons, core.RFC_TICKS, dtype=np.int32)
        for key in driven:
            rl[self.stimuli[key].indices] = 0
        self.rfc_reload = mx.array(rl)
        self._driven_key = driven

    # ---- drive ------------------------------------------------------------
    @property
    def t_bio(self) -> float:
        return self.tick * core.DT / 1000.0

    def trigger(self, key: str, ms: float, rate_hz: float | None = None) -> Stimulus:
        s = self.stimuli[key]
        if rate_hz is not None:
            s.rate_hz = float(rate_hz)
        s.until = self.t_bio + ms / 1000.0
        return s

    def active(self) -> list[Stimulus]:
        t = self.t_bio
        return [s for s in self.stimuli.values() if s.until > t]

    def _draws(self, n_ticks: int) -> mx.array:
        """uint8[n_ticks, n_slots]: the external spikes for this chunk.

        A stimulus contributes its Poisson draws only for the ticks before its
        deadline, so a 200 ms press that expires mid-chunk stops mid-chunk.
        """
        out = np.zeros((n_ticks, self.n_slots), dtype=np.uint8)
        t0 = self.t_bio
        for s in self.stimuli.values():
            if s.until <= t0:
                continue
            live = int(round(min(n_ticks, (s.until - t0) * 1000.0 / core.DT)))
            if live <= 0:
                continue
            p = s.rate_hz * core.DT / 1000.0
            out[:live, s.slots[0]:s.slots[-1] + 1] = (
                self.rng.random((live, s.size)) < p)
        return mx.array(out)

    # ---- the tick loop ----------------------------------------------------
    def step(self, n_ticks: int) -> tuple[np.ndarray, float]:
        """Advance n_ticks and return each neuron's spike count over them, uint8,
        plus the wall-clock seconds it took."""
        self._set_rfc_reload(frozenset(s.key for s in self.active()))
        draws = self._draws(n_ticks)

        start = time.perf_counter()
        v, g, rfc, counts = self.v, self.g, self.rfc, self.counts
        fired = []
        for j in range(n_ticks):
            s = (self.tick + j) % core.DELAY_TICKS
            contrib = propagate(self.ring[s], self.pack, self.n_src,
                                self.edge_split, row_end=self.row_end)
            v, g, rfc, counts, spike = _state_kernel(
                inputs=[v, g, rfc, counts, contrib, draws[j], self.target_slot,
                        self.rfc_reload, self.n_neurons, self.k["c_v0_term"],
                        self.k["c_couple_g"], self.k["c_decay_v"], self.k["c_decay_g"],
                        self.k["c_v_th"], self.k["c_w_syn"], self.k["c_w_ext"],
                        self.k["c_v_0"]],
                output_shapes=[(self.pack.n_neurons,)] * 5,
                output_dtypes=[mx.float32, mx.float32, mx.int32, mx.int32, mx.uint8],
                grid=(self.pack.n_neurons, 1, 1),
                threadgroup=(256, 1, 1),
            )
            self.ring[s] = spike
            fired.append(spike)

        # One reduction for the chunk rather than an accumulator per tick: the
        # fused lane's whole point is that a tick is two dispatches, and a third
        # full-width op per tick would be a measurable share of it.
        per_neuron = mx.sum(mx.stack(fired), axis=0).astype(mx.uint8)
        self.v, self.g, self.rfc, self.counts = v, g, rfc, counts
        mx.eval(self.v, self.g, self.rfc, self.counts, per_neuron, *self.ring)
        out = np.asarray(per_neuron)
        self.tick += n_ticks
        return out, time.perf_counter() - start

    def rates(self, per_neuron: np.ndarray, n_ticks: int) -> dict[str, float]:
        """Mean firing rate in Hz of each readout population over the chunk."""
        seconds = n_ticks * core.DT / 1000.0
        return {k: float(per_neuron[idx].sum()) / len(idx) / seconds
                for k, idx in self.readouts.items()}
