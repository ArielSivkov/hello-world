"""Download the data for the experiment: weekly fresh windows and fixed core sets."""
from __future__ import annotations

import argparse
from datetime import date, timedelta
from pathlib import Path

from .data import fetch_window, sample, save_jsonl

CORE = {
    # in-domain but old: checks the model does not forget the field's past
    "core_domain_old": [("cs.CL", "20220301", "20220314")],
    # out of domain and old: checks general ability is not traded away
    "core_general": [("math.CO", "20220301", "20220310"), ("physics.optics", "20220301", "20220310"),
                     ("q-bio.NC", "20220301", "20220331"), ("econ.GN", "20220301", "20220331")],
}

# General text used as replay to hold general ability in place. Its categories are
# deliberately different from the core test categories, so it is not teaching to the test.
ANCHOR = {
    "anchor_general": [("astro-ph.GA", "20220401", "20220410"), ("cond-mat.mtrl-sci", "20220401", "20220407"),
                       ("stat.ME", "20220401", "20220420"), ("cs.DS", "20220401", "20220430")],
}


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", type=Path, default=Path("data"))
    ap.add_argument("--category", default="cs.CL")
    ap.add_argument("--first-monday", default="2026-09-28")
    ap.add_argument("--windows", type=int, default=6)
    ap.add_argument("--per-window", type=int, default=200)
    ap.add_argument("--core-size", type=int, default=120)
    ap.add_argument("--anchor-size", type=int, default=400)
    ap.add_argument("--seed", type=int, default=0)
    a = ap.parse_args()

    start = date.fromisoformat(a.first_monday)
    seen: set[str] = set()
    for w in range(a.windows):
        path = a.out / f"window_{w}.jsonl"
        if path.exists():
            continue
        s, e = start + timedelta(weeks=w), start + timedelta(weeks=w, days=6)
        docs = fetch_window(a.category, s.strftime("%Y%m%d"), e.strftime("%Y%m%d"), limit=600)
        docs = [d for d in docs if d.id not in seen]
        seen.update(d.id for d in docs)
        picked = sample(docs, a.per_window, a.seed + w)
        save_jsonl(path, picked)
        print(f"window {w} {s}..{e}: fetched {len(docs)}, kept {len(picked)}", flush=True)

    for name, parts in {**CORE, **ANCHOR}.items():
        path = a.out / f"{name}.jsonl"
        if path.exists():
            continue
        docs = []
        per = (a.anchor_size if name in ANCHOR else a.core_size) // len(parts)
        for i, (cat, s, e) in enumerate(parts):
            got = fetch_window(cat, s, e, limit=300)
            docs += sample(got, per, a.seed + 100 + i)
            print(f"{name}/{cat}: fetched {len(got)}", flush=True)
        save_jsonl(path, docs)


if __name__ == "__main__":
    main()
