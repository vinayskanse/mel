"""Pack the MaleCNS soma positions for the browser, in the neuropil meshes' frame.

`somaLocation` in the annotation table is in 8 nm voxels; the ROI meshes are in
nanometres. Measured on this release: multiplying the soma coordinates by 8 puts
the 122,214 somas of definitely-brain superclasses inside the mesh bounding box
on all three axes, so the factor is 8 and it is applied here.

Somas outside that box are not an error -- ascending neurons have their cell
bodies in the ventral nerve cord and send axons up into the brain, and the brain
ROI meshes cover the brain only.

Reads the annotation table fetched by drosophila-brain-mlx/tools/fetch_male_cns.sh
and quantises against viewer/data/brain.json, so somas and neuropils land in register.

Output (viewer/data/):
    somas.bin    uint16[n, 3] positions, then uint8[n] group codes
    somas.json   the index: count, byte ranges, group names, and the bodyId list
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

import numpy as np
import pyarrow.feather as feather

HERE = Path(__file__).resolve().parent
OUT = HERE / "data"
ANNOT = (HERE.parent / "research/drosophila-brain-mlx/data/raw/male_cns"
         / "body-annotations-male-cns-v1.0-minconf-0.5.feather")

VOXEL_NM = 8.0   # somaLocation is in 8 nm voxels; verified against the ROI meshes

# Coarse groups, so the viewer can colour the cloud by what a neuron is for
# without shipping the whole annotation table to the browser.
GROUPS = ["other", "optic", "central", "visual_projection",
          "descending", "ascending", "motor", "sensory", "vnc"]


def group_codes(superclass: np.ndarray) -> np.ndarray:
    code = np.zeros(len(superclass), dtype=np.uint8)
    s = np.array([str(x) for x in superclass], dtype=object)

    def mark(mask, name):
        code[mask & (code == 0)] = GROUPS.index(name)

    mark(s == "descending_neuron", "descending")
    mark(s == "ascending_neuron", "ascending")
    mark(np.isin(s, ["vnc_motor", "motor"]), "motor")
    mark(np.isin(s, ["vnc_sensory", "sensory"]), "sensory")
    mark(s == "visual_projection", "visual_projection")
    mark(s == "ol_intrinsic", "optic")
    mark(s == "cb_intrinsic", "central")
    mark(np.array([x.startswith("vnc") for x in s]), "vnc")
    return code


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--annotations", type=Path, default=ANNOT)
    args = ap.parse_args()

    if not args.annotations.exists():
        raise SystemExit(f"{args.annotations} not found -- run "
                         "research/drosophila-brain-mlx/tools/fetch_male_cns.sh first")
    brain_json = OUT / "brain.json"
    if not brain_json.exists():
        raise SystemExit(f"{brain_json} not found -- run build_brain.py first")

    quant = json.loads(brain_json.read_text())["quantization"]
    lo = np.array(quant["origin"])
    span = np.array(quant["span"])

    table = feather.read_table(args.annotations,
                               columns=["bodyId", "somaLocation", "superclass"])
    column = table["somaLocation"]
    placed = column.is_valid().to_numpy(zero_copy_only=False)

    nm = (column.drop_null().combine_chunks().flatten()
          .to_numpy(zero_copy_only=False).reshape(-1, 3) * VOXEL_NM)
    body = table["bodyId"].to_numpy()[placed]
    code = group_codes(np.array(table["superclass"].to_pylist(), dtype=object)[placed])

    # The same 16-bit transform the meshes use. Somas outside the brain ROI box
    # (the ventral nerve cord's) would clamp onto its faces and draw a false
    # slab, so they are dropped here and reported rather than squashed.
    unit = (nm - lo) / span
    inside = np.all((unit >= 0) & (unit <= 1), axis=1)
    dropped = int((~inside).sum())
    nm, body, code, unit = nm[inside], body[inside], code[inside], unit[inside]

    q = np.clip(np.round(unit * 65535.0), 0, 65535).astype("<u2")

    blob = bytearray()
    pos_off = len(blob)
    blob += q.tobytes()
    code_off = len(blob)
    blob += code.astype(np.uint8).tobytes()

    (OUT / "somas.bin").write_bytes(blob)
    (OUT / "somas.json").write_text(json.dumps({
        "source": "MaleCNS v1.0 body annotations, FlyEM/HHMI Janelia + Google Research, CC BY 4.0",
        "voxelNm": VOXEL_NM,
        "count": int(len(q)),
        "positionOffset": pos_off, "groupOffset": code_off,
        "groups": GROUPS,
        "quantization": quant,
    }, indent=1))
    np.save(OUT / "soma_body_ids.npy", body.astype(np.int64))

    counts = {GROUPS[i]: int((code == i).sum()) for i in range(len(GROUPS))}
    print(f"{int(placed.sum()):,} of {table.num_rows:,} bodies have a soma position")
    print(f"{dropped:,} dropped as outside the brain ROI box "
          "(ventral nerve cord somas: ascending, motor and vnc neurons)")
    print(f"wrote data/somas.bin {len(blob) / 1e6:.2f} MB, {len(q):,} points")
    print("  by group: " + ", ".join(f"{k}={v:,}" for k, v in counts.items() if v))
    print(f"wrote data/soma_body_ids.npy ({len(body):,} bodyIds, "
          "the map from point index to the simulation's neurons)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
