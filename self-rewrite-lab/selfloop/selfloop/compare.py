"""Paired comparison of two runs on the same unseen weeks.

  python -m selfloop.compare runs/self runs/anchor

For every cycle both runs logged, prints paired_diff(A, B) in bits/token over
the same test documents (negative: A is better), using the unchanged
stats.paired_diff. Also compares A with base+retrieval.
"""
from __future__ import annotations

import sys
from pathlib import Path

import numpy as np

from .stats import paired_diff


def compare(a: Path, b: Path) -> list[dict]:
    rows = []
    for fa in sorted(a.glob("scores_*.npz"), key=lambda p: int(p.stem.split("_")[1])):
        fb = b / fa.name
        if not fb.exists():
            continue
        za, zb = np.load(fa), np.load(fb)
        if list(za["ids"]) != list(zb["ids"]) or not np.array_equal(za["ntok"], zb["ntok"]):
            raise ValueError(f"{fa.name}: the two runs were not scored on the same documents")
        rows.append({"cycle": int(fa.stem.split("_")[1]),
                     "A_vs_B": paired_diff(za["cand_nll"], zb["cand_nll"], za["ntok"]),
                     "A+ret_vs_B+ret": paired_diff(za["cand_rag_nll"], zb["cand_rag_nll"], za["ntok"]),
                     "A_vs_base+ret": paired_diff(za["cand_nll"], za["base_rag_nll"], za["ntok"])})
    return rows


def main() -> None:
    a, b = Path(sys.argv[1]), Path(sys.argv[2])
    print(f"A={a}  B={b}  (bits/token, negative = A better, 95% paired bootstrap)")
    for r in compare(a, b):
        cells = [f"{k} {v['diff']:+.4f} [{v['lo']:+.4f},{v['hi']:+.4f}]"
                 for k, v in r.items() if k != "cycle"]
        print(f"cycle {r['cycle']}: " + " | ".join(cells))


if __name__ == "__main__":
    main()
