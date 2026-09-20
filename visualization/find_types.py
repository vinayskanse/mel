"""Which cell types does this pack actually carry, and how are they spelled?

The stimulus table in sim_server.py names cells from the literature. The pack
names them from MaleCNS v1.0's own annotations, and the two do not always agree
about punctuation, sidedness or case -- which is why `LiveBrain` drops a
stimulus it cannot resolve instead of refusing to start. This is how you find
out what to write in the table instead.

    python find_types.py JO            # every type whose name contains "JO"
    python find_types.py --class sensory --limit 80
    python find_types.py LB --counts   # with how many neurons each has

Matching is case-insensitive substring, over both the `type` and `instance`
columns, because a stimulus selector is resolved against both in that order.
"""

from __future__ import annotations

import argparse
import sys
from collections import Counter
from pathlib import Path

HERE = Path(__file__).resolve().parent
PACK = HERE.parent / "research/drosophila-brain-mlx/data/pack/male_cns_v1"


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("pattern", nargs="?", default="",
                    help="case-insensitive substring; empty lists everything")
    ap.add_argument("--pack", default=str(PACK))
    ap.add_argument("--class", dest="klass", default="",
                    help="also require this substring in the class column")
    ap.add_argument("--counts", action="store_true", help="show neurons per type")
    ap.add_argument("--limit", type=int, default=60)
    args = ap.parse_args(argv)

    try:
        import pyarrow.parquet as pq
    except ImportError:
        print("pyarrow is needed to read the pack's names sidecar:\n"
              "    pip install pyarrow", file=sys.stderr)
        return 1

    table = pq.read_table(Path(args.pack) / "names.parquet")
    types = table["type"].to_pylist()
    instances = table["instance"].to_pylist()
    classes = table["class"].to_pylist()

    want, klass = args.pattern.lower(), args.klass.lower()
    hits: Counter[tuple[str, str]] = Counter()
    for type_, instance, class_ in zip(types, instances, classes):
        if klass and klass not in (class_ or "").lower():
            continue
        for name in (type_, instance):
            if name and want in name.lower():
                hits[(name, class_ or "")] += 1

    if not hits:
        print(f"nothing matches {args.pattern!r}"
              + (f" in class ~{args.klass!r}" if args.klass else ""))
        return 1

    print(f"{len(hits)} names match {args.pattern!r}"
          + (f" in class ~{args.klass!r}" if args.klass else "")
          + f"; showing {min(len(hits), args.limit)}\n")
    for (name, class_), count in hits.most_common(args.limit):
        print(f"  {name:<28} {class_:<22}" + (f"{count:>6} neurons" if args.counts else ""))
    return 0


if __name__ == "__main__":
    sys.exit(main())
