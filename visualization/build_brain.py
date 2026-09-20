"""Fetch the MaleCNS v1.0 neuropil meshes and pack them for the browser.

Source: gs://flyem-male-cns/rois/fullbrain-roi-v5/mesh/ -- 84 brain neuropil
compartments in neuroglancer_legacy_mesh format, CC BY 4.0, FlyEM / HHMI Janelia
/ Google Research. Nothing here is redistributed; this downloads at build time.

Legacy ngmesh layout, little endian, no header beyond the count:
    uint32   vertex count n
    float32  n * 3 vertex coordinates, in nanometres
    uint32   remainder, triangle indices in triples

Output (viewer/data/):
    brain.bin    every compartment's quantised vertices and indices, concatenated
    brain.json   the index: name, colour, byte ranges, and the bbox to dequantise with

Vertices are welded onto a grid (--grid, in nanometres) before packing, which is
what keeps the payload small: the raw meshes are ~135 MB and the fly's compartments
are far smoother than their triangle count suggests.
"""

from __future__ import annotations

import argparse
import json
import struct
import sys
import urllib.request
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import numpy as np

BUCKET = "https://storage.googleapis.com/flyem-male-cns"
MESH = f"{BUCKET}/rois/fullbrain-roi-v5/mesh"
LIST = ("https://storage.googleapis.com/storage/v1/b/flyem-male-cns/o"
        "?prefix=rois/fullbrain-roi-v5/mesh/&fields=items(name)")

HERE = Path(__file__).resolve().parent
OUT = HERE / "data"
CACHE = OUT / "ngmesh"

# The sugar pathway's territory. Labellar sweet neurons project to the SEZ --
# gnathal ganglion, prow and saddle -- and MN9, the proboscis motor neuron the
# model reads out, sits in GNG. These get lit differently in the viewer.
SEZ = {"GNG", "PRW", "SAD"}
# Mushroom body: calyx, peduncle and the lobes. Where reward learning would live.
MB = {"CA(L)", "CA(R)", "PED(L)", "PED(R)",
      "aL(L)", "aL(R)", "aL(L)_", "aL(R)_", "bL(L)", "bL(R)", "gL(L)", "gL(R)",
      "a'L(L)", "a'L(R)", "b'L(L)", "b'L(R)"}
AL = {"AL(L)", "AL(R)"}                     # antennal lobes, smell
OPTIC = {"ME(L)", "ME(R)", "LO(L)", "LO(R)", "LOP(L)", "LOP(R)",
         "LA(L)", "LA(R)", "AME(L)", "AME(R)"}


def group_of(name: str) -> str:
    if name in SEZ:
        return "sez"
    if name in MB:
        return "mb"
    if name in AL:
        return "al"
    if name in OPTIC:
        return "optic"
    return "other"


def compartments() -> list[str]:
    with urllib.request.urlopen(LIST, timeout=60) as r:
        items = json.load(r)["items"]
    return sorted(i["name"].split("/")[-1][: -len(".ngmesh")]
                  for i in items if i["name"].endswith(".ngmesh"))


def fetch(name: str) -> bytes:
    """The compartment's raw ngmesh, cached on disk so a rerun costs nothing."""
    path = CACHE / f"{name}.ngmesh"
    if path.exists() and path.stat().st_size > 4:
        return path.read_bytes()
    url = f"{MESH}/{urllib.parse.quote(name)}.ngmesh"
    with urllib.request.urlopen(url, timeout=300) as r:
        data = r.read()
    path.write_bytes(data)
    return data


def parse(data: bytes) -> tuple[np.ndarray, np.ndarray]:
    """float32[n, 3] vertices in nanometres and uint32[m, 3] triangles."""
    if len(data) < 4:
        raise ValueError("mesh is too short to hold a vertex count")
    n = struct.unpack_from("<I", data, 0)[0]
    need = 4 + 12 * n
    if len(data) < need or (len(data) - need) % 12:
        raise ValueError(f"mesh of {len(data)} bytes does not hold {n} vertices "
                         "and a whole number of triangles")
    verts = np.frombuffer(data, "<f4", count=3 * n, offset=4).reshape(-1, 3)
    tris = np.frombuffer(data, "<u4", offset=need).reshape(-1, 3)
    if tris.size and tris.max() >= n:
        raise ValueError(f"triangle indexes vertex {int(tris.max())} of {n}")
    return verts, tris


def weld(verts: np.ndarray, tris: np.ndarray, grid: float):
    """Snap vertices onto a grid of `grid` nm, merge the duplicates, drop the
    triangles that collapse to a line or a point."""
    if grid <= 0:
        return verts, tris
    keys = np.round(verts / grid).astype(np.int64)
    _, first, inverse = np.unique(keys, axis=0, return_index=True, return_inverse=True)
    out_v = verts[first]
    out_t = inverse[tris]
    keep = ((out_t[:, 0] != out_t[:, 1])
            & (out_t[:, 1] != out_t[:, 2])
            & (out_t[:, 0] != out_t[:, 2]))
    return out_v, out_t[keep]


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--grid", type=float, default=900.0,
                    help="weld vertices onto a grid this many nanometres across "
                         "(0 keeps every vertex; the fly's brain is ~800,000 nm wide)")
    ap.add_argument("--jobs", type=int, default=8)
    args = ap.parse_args()

    OUT.mkdir(parents=True, exist_ok=True)
    CACHE.mkdir(parents=True, exist_ok=True)

    names = compartments()
    print(f"{len(names)} brain neuropil compartments")

    with ThreadPoolExecutor(max_workers=args.jobs) as pool:
        raw = list(pool.map(fetch, names))
    print(f"fetched {sum(len(b) for b in raw) / 1e6:.1f} MB of ngmesh "
          f"(cached in {CACHE.relative_to(HERE)})")

    meshes = []
    raw_v = raw_t = 0
    for name, data in zip(names, raw, strict=True):
        v, t = parse(data)
        raw_v += len(v)
        raw_t += len(t)
        v, t = weld(v, t, args.grid)
        if not len(t):
            print(f"  skip {name}: nothing survived welding")
            continue
        meshes.append((name, v, t))

    # One bounding box for the whole brain, so the viewer can dequantise every
    # compartment against a single transform and they stay in register.
    lo = np.min([v.min(axis=0) for _, v, _ in meshes], axis=0)
    hi = np.max([v.max(axis=0) for _, v, _ in meshes], axis=0)
    span = np.maximum(hi - lo, 1e-6)

    blob = bytearray()
    index = []
    for name, v, t in meshes:
        q = np.clip(np.round((v - lo) / span * 65535.0), 0, 65535).astype("<u2")
        idx_dtype = "<u2" if len(v) <= 65536 else "<u4"
        i = t.astype(idx_dtype)
        v_off = len(blob)
        blob += q.tobytes()
        i_off = len(blob)
        blob += i.tobytes()
        index.append({
            "name": name,
            "group": group_of(name),
            "vertexOffset": v_off, "vertexCount": int(len(v)),
            "indexOffset": i_off, "indexCount": int(t.size),
            "indexBytes": 2 if idx_dtype == "<u2" else 4,
        })

    (OUT / "brain.bin").write_bytes(blob)
    (OUT / "brain.json").write_text(json.dumps({
        "source": "MaleCNS v1.0 fullbrain-roi-v5, FlyEM/HHMI Janelia + Google Research, CC BY 4.0",
        "units": "nanometres",
        "quantization": {"origin": lo.tolist(), "span": span.tolist(), "bits": 16},
        "gridNm": args.grid,
        "compartments": index,
    }, indent=1))

    kept_v = sum(c["vertexCount"] for c in index)
    kept_t = sum(c["indexCount"] // 3 for c in index)
    print(f"welded on a {args.grid:g} nm grid: "
          f"{raw_v:,} -> {kept_v:,} vertices ({kept_v / raw_v:.1%}), "
          f"{raw_t:,} -> {kept_t:,} triangles ({kept_t / raw_t:.1%})")
    print(f"wrote data/brain.bin {len(blob) / 1e6:.2f} MB and data/brain.json "
          f"({len(index)} compartments)")
    print(f"brain bounding box, nm: {np.round(lo).astype(int).tolist()} "
          f"to {np.round(hi).astype(int).tolist()}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
