"""Gated self-improvement, run in cycles of ~10 experiments.

  python3 loop.py --cycle N

Each cycle starts from the current champion config, tries every candidate listed for that cycle in
cycles.py (weakest category first), and keeps a change only if the dev total rises and no category
drops by more than TOLERANCE points. When the cycle ends the champion is scored once on the hidden
holdout split, which is never used for a decision. Conclusions and the next cycle's candidates are
written by the "engineer" (a human or a stronger model) after reading the failure traces.
"""
import copy
import json
import os
import sys
import time

sys.path.insert(0, os.path.dirname(__file__))
from ion.agent import Config          # noqa: E402
from arena.run import evaluate, TAG   # noqa: E402
from cycles import CYCLES             # noqa: E402

TOLERANCE = 10
ROOT = os.path.dirname(os.path.abspath(__file__))
CHAMPION = os.path.join(ROOT, f"champion-{TAG}.json")


def main(n):
    hist = os.path.join(ROOT, f"cycle{n}-{TAG}.jsonl")

    def log(row):
        row["t"] = time.strftime("%Y-%m-%d %H:%M:%S")
        with open(hist, "a", encoding="utf-8") as f:
            f.write(json.dumps(row, ensure_ascii=False) + "\n")
        print(json.dumps(row, ensure_ascii=False), flush=True)

    cfg = Config(**json.load(open(CHAMPION))) if os.path.exists(CHAMPION) else Config()
    cur = evaluate(cfg)
    log({"event": "start", "cycle": n, "config": cfg.__dict__, "score": cur})
    todo = list(CYCLES[n])
    while todo:
        # next: the candidate aimed at the weakest category it can apply to
        order = sorted(cur["cats"], key=lambda c: cur["cats"][c])
        ok = [c for c in todo if c[3](cfg)]
        if not ok:
            for name, *_ in todo:
                log({"event": "skipped", "name": name, "why": "prerequisite not met"})
            break
        pick = min(ok, key=lambda c: min(order.index(t) for t in c[1]))
        todo.remove(pick)
        name, targets, mut, _ = pick
        new_cfg = copy.deepcopy(cfg)
        mut(new_cfg)
        print(f"\n== trying {name}", flush=True)
        new = evaluate(new_cfg)
        regress = {c: (cur["cats"][c], new["cats"][c]) for c in cur["cats"]
                   if new["cats"][c] < cur["cats"][c] - TOLERANCE}
        keep = new["total"] > cur["total"] and not regress
        log({"event": "candidate", "name": name, "before": cur["total"], "after": new["total"],
             "cats": new["cats"], "kinds": new["kinds"], "regressions": regress,
             "avg_steps": new["avg_steps"], "kept": keep})
        if keep:
            cfg, cur = new_cfg, new
    json.dump(cfg.__dict__, open(CHAMPION, "w"), indent=1)
    log({"event": "end", "cycle": n, "config": cfg.__dict__, "dev": cur,
         "holdout": evaluate(cfg, "holdout"), "holdout_baseline": evaluate(Config(), "holdout")})


if __name__ == "__main__":
    main(int(sys.argv[sys.argv.index("--cycle") + 1]))
