"""Extract one stimulus-to-motor pathway and pack its skeletons for the browser.

The pathway is not read off the connectivity graph. A graph walk finds plenty of
routes that the model never uses -- the two cells that look like the sugar gate
by synapse count reach MN9 through a single synapse, one of them inhibitory. So
this runs the simulation, records when each neuron first fires, and then walks
backwards from the readout keeping only presynaptic partners that both connect
strongly *and* fired earlier. What comes out is the route the signal actually
took, with a measured time for every step.

Morphology comes from the MaleCNS skeletons (CC BY 4.0, FlyEM / HHMI Janelia /
Google Research), which matters for more than looks: a sugar neuron's soma sits
out in the labellum and is not drawn in the point cloud at all, but its axon is
100% inside the brain, so as a skeleton the input becomes visible.

Each skeleton also carries a per-vertex distance from its root, so the page can
run a light along the branch rather than flashing the cell whole.

Output (viewer/data/):
    pathway.bin     per neuron: quantised vertices, distances, line indices
    pathway.json    the index, with each neuron's first-spike time in ms

    python build_pathway.py --stimulus sugar --readout MN9_L
"""

from __future__ import annotations

import argparse
import collections
import json
import struct
import sys
import urllib.request
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import numpy as np

from lif import core, names
from live_engine import LiveBrain

HERE = Path(__file__).resolve().parent
OUT = HERE / "data"
CACHE = OUT / "skel"
PACK = HERE.parent / "research/drosophila-brain-mlx/data/pack/male_cns_v1"
SKEL = ("https://storage.googleapis.com/flyem-male-cns/v1.0/segmentation"
        "/skeletons-malecns/skeletons-highres-precomputed")

# The readout is the brain's own output -- a descending or motor neuron the
# stimulus actually drives, picked as the earliest strong one measured rather
# than chosen for the story. MN9 is kept for sugar because proboscis extension
# is the behaviour the pathway is named after.
DEFAULT_READOUT = {
    "sugar": "MN9_L",            # proboscis extension, 27 ms
    "water": "DNg67_R",          # 19 ms, the clearest output water reaches
    "smell": "DNb05_R",          # 15 ms, strongest early descending response
    "looming": "DNp01(GF)_R",    # the giant fiber, 5 ms
}

STIMULI = {
    "sugar":   ("Sugar", ["LB3b_R", "LB3c_R"]),
    "water":   ("Water", ["LB3a_R"]),
    "smell":   ("Smell", ["ORN_DM1_R"]),
    "looming": ("Looming", ["LC4_R"]),
}


# ---------------------------------------------------------------- the pathway
def trace(brain: LiveBrain, stim_key: str, readout: str, *, ms: int,
          min_syn: int, fan: int, depth: int):
    """The neurons the signal actually went through, and when each first fired."""
    pack = brain.pack
    row = np.asarray(pack.row_ptr)
    dst = np.asarray(pack.destinations)
    wt = np.asarray(pack.signed_counts)
    N = pack.n_neurons

    first = np.full(N, -1, dtype=np.int32)
    nspk = np.zeros(N, dtype=np.int64)
    brain.reset()
    brain.trigger(stim_key, ms=ms)
    for step in range(ms):                      # 1 ms resolution
        per, _ = brain.step(10)
        f = np.flatnonzero(per > 0)
        nspk[f] += per[f]
        new = f[first[f] < 0]
        first[new] = step + 1

    target = brain.names.select(readout)
    if not target:
        raise SystemExit(f"readout {readout!r} selected no neurons")
    target = target[0]
    if first[target] < 0:
        raise SystemExit(f"{readout} never fired within {ms} ms of {stim_key}; "
                         "nothing to trace")

    active = np.flatnonzero(first >= 0)
    # Presynaptic partners of j, among neurons that fired before j, strongest first.
    def preds(j):
        out = []
        for i in active:
            a, e = row[i], row[i + 1]
            m = dst[a:e] == j
            if not m.any():
                continue
            c = int(wt[a:e][m].sum())
            if c >= min_syn and 0 <= first[i] < first[j]:
                out.append((int(i), c))
        return sorted(out, key=lambda x: -x[1])[:fan]

    driven = set(brain.stimuli[stim_key].indices.tolist())
    keep = {target}
    edges = []
    frontier = [target]
    for _ in range(depth):
        nxt = []
        for j in frontier:
            for i, c in preds(j):
                edges.append((i, j, c))
                if i not in keep:
                    keep.add(i)
                    if i not in driven:
                        nxt.append(i)
        frontier = nxt
        if not frontier:
            break

    # Bring in the driven neurons that feed anything already kept, so the picture
    # starts at the stimulus rather than in the middle of the brain.
    for i in driven:
        a, e = row[i], row[i + 1]
        m = np.isin(dst[a:e], list(keep))
        if m.any() and first[i] >= 0:
            c = int(wt[a:e][m].sum())
            keep.add(i)
            for j in np.unique(dst[a:e][m]):
                edges.append((int(i), int(j), c))

    return sorted(keep), edges, first, nspk, driven


# ---------------------------------------------------------------- skeletons
def fetch_skeleton(body: int) -> bytes:
    path = CACHE / f"{body}.skel"
    if path.exists() and path.stat().st_size > 8:
        return path.read_bytes()
    with urllib.request.urlopen(f"{SKEL}/{body}", timeout=300) as r:
        data = r.read()
    path.write_bytes(data)
    return data


def parse_skeleton(data: bytes):
    """float32[n, 3] vertices in nanometres and uint32[m, 2] edges."""
    nv, ne = struct.unpack_from("<II", data, 0)
    need = 8 + 12 * nv + 8 * ne
    if len(data) < need:
        raise ValueError(f"skeleton is {len(data)} bytes, header wants {need}")
    verts = np.frombuffer(data, "<f4", count=3 * nv, offset=8).reshape(-1, 3)
    edges = np.frombuffer(data, "<u4", count=2 * ne, offset=8 + 12 * nv).reshape(-1, 2)
    return verts, edges


def weld(verts, edges, grid):
    """Snap onto a grid and merge, as build_brain.py does for the meshes. A
    traced skeleton carries ~130,000 vertices for one neuron, which is far more
    than a screen can show."""
    if grid <= 0:
        return verts, edges
    keys = np.round(verts / grid).astype(np.int64)
    _, firstv, inv = np.unique(keys, axis=0, return_index=True, return_inverse=True)
    v = verts[firstv]
    e = inv[edges]
    e = e[e[:, 0] != e[:, 1]]
    e = np.unique(np.sort(e, axis=1), axis=0)
    return v, e


def root_distance(verts, edges):
    """Path length from the most peripheral vertex, along the skeleton.

    Used to run a light down the branch. It is a distance along real traced
    geometry; which end it starts from is a drawing choice, so the root is taken
    as the vertex furthest from the centre of the arbor -- for these cells the
    soma or the axon's far tip, either of which reads as "the far end".
    """
    n = len(verts)
    if n == 0:
        return np.zeros(0, np.float32)
    adj = collections.defaultdict(list)
    for a, b in edges:
        d = float(np.linalg.norm(verts[a] - verts[b]))
        adj[int(a)].append((int(b), d))
        adj[int(b)].append((int(a), d))
    root = int(np.argmax(np.linalg.norm(verts - verts.mean(axis=0), axis=1)))

    import heapq
    dist = np.full(n, np.inf, dtype=np.float64)
    dist[root] = 0.0
    q = [(0.0, root)]
    while q:
        d, u = heapq.heappop(q)
        if d > dist[u]:
            continue
        for v, wgt in adj[u]:
            nd = d + wgt
            if nd < dist[v]:
                dist[v] = nd
                heapq.heappush(q, (nd, v))
    # Disconnected fragments (traced skeletons have them) sit at the far end.
    finite = np.isfinite(dist)
    dist[~finite] = dist[finite].max() if finite.any() else 0.0
    top = dist.max() or 1.0
    return (dist / top).astype(np.float32)


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--stimulus", default="sugar", choices=list(STIMULI))
    ap.add_argument("--readout", default=None,
                    help="default: the DEFAULT_READOUT for this stimulus")
    ap.add_argument("--name", default=None, help="output basename (default: pathway_<stimulus>)")
    ap.add_argument("--ms", type=int, default=120, help="how long to watch for the readout")
    ap.add_argument("--min-syn", type=int, default=20)
    ap.add_argument("--fan", type=int, default=3, help="presynaptic partners kept per neuron")
    ap.add_argument("--depth", type=int, default=3)
    ap.add_argument("--grid", type=float, default=700.0, help="skeleton weld grid, nm")
    ap.add_argument("--jobs", type=int, default=6)
    args = ap.parse_args()
    if args.readout is None:
        args.readout = DEFAULT_READOUT[args.stimulus]
    stem = args.name or f"pathway_{args.stimulus}"

    OUT.mkdir(parents=True, exist_ok=True)
    CACHE.mkdir(parents=True, exist_ok=True)

    label, types = STIMULI[args.stimulus]
    brain = LiveBrain(PACK, {args.stimulus: (label, "", types, 100.0)},
                      {args.readout: [args.readout]}, edge_split=1)
    pack, nm = brain.pack, brain.names
    lab = nm.labels()

    print(f"tracing {args.stimulus} -> {args.readout} ...")
    keep, edges, first, nspk, driven = trace(
        brain, args.stimulus, args.readout,
        ms=args.ms, min_syn=args.min_syn, fan=args.fan, depth=args.depth)
    print(f"  {len(keep)} neurons on the path, {len(edges)} connections")

    bodies = [int(pack.neuron_ids[i]) for i in keep]
    print(f"fetching {len(bodies)} skeletons ...")
    with ThreadPoolExecutor(max_workers=args.jobs) as pool:
        raw = list(pool.map(fetch_skeleton, bodies))
    print(f"  {sum(len(b) for b in raw) / 1e6:.1f} MB raw")

    quant = json.loads((OUT / "brain.json").read_text())["quantization"]
    lo = np.array(quant["origin"])
    span = np.array(quant["span"])

    blob = bytearray()
    index = []
    raw_v = kept_v = 0
    for i, body, data in zip(keep, bodies, raw, strict=True):
        v, e = parse_skeleton(data)
        raw_v += len(v)
        v, e = weld(v, e, args.grid)
        if len(e) == 0:
            print(f"  skip {lab.get(body, body)}: nothing survived welding")
            continue
        kept_v += len(v)
        d = root_distance(v, e)

        unit = np.clip((v - lo) / span, 0, 1)
        q = np.rint(unit * 65535).astype("<u2")
        dq = np.rint(d * 65535).astype("<u2")
        idx = e.astype("<u4")

        v_off = len(blob); blob += q.tobytes()
        d_off = len(blob); blob += dq.tobytes()
        e_off = len(blob); blob += idx.tobytes()
        index.append({
            "body": body,
            "name": lab.get(body, str(body)),
            "firstMs": int(first[i]),
            "spikes": int(nspk[i]),
            "driven": bool(i in driven),
            "readout": bool(lab.get(body, "") == args.readout),
            "vertexOffset": v_off, "vertexCount": int(len(v)),
            "distOffset": d_off,
            "edgeOffset": e_off, "edgeCount": int(len(e)),
        })

    index.sort(key=lambda c: (c["firstMs"], c["name"]))
    (OUT / f"{stem}.bin").write_bytes(blob)
    (OUT / f"{stem}.json").write_text(json.dumps({
        "source": "MaleCNS v1.0 skeletons, FlyEM/HHMI Janelia + Google Research, CC BY 4.0",
        "stimulus": args.stimulus, "stimulusLabel": label,
        "stimulusTypes": types, "readout": args.readout,
        "quantization": quant,
        "gridNm": args.grid,
        "neurons": index,
        "connections": [{"from": int(pack.neuron_ids[a]), "to": int(pack.neuron_ids[b]),
                         "syn": int(c)} for a, b, c in edges],
    }, indent=1))

    print(f"welded on a {args.grid:g} nm grid: {raw_v:,} -> {kept_v:,} vertices "
          f"({kept_v / max(raw_v, 1):.1%})")
    print(f"wrote data/{stem}.bin {len(blob) / 1e6:.2f} MB, "
          f"data/{stem}.json ({len(index)} neurons)")
    print("\n  ms  name             spikes")
    for c in index:
        tag = " <- driven" if c["driven"] else (" <- readout" if c["readout"] else "")
        print(f"  {c['firstMs']:>3}  {c['name']:<16} {c['spikes']:>6}{tag}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
