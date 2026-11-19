"""Run a Config over a task split. Results are cached per (config, task) so reruns are free."""
import hashlib
import json
import os
import sys
import time
from collections import defaultdict

HERE = os.path.dirname(__file__)
sys.path.insert(0, os.path.join(HERE, ".."))
from ion.agent import Config, run          # noqa: E402
from arena.check import correct            # noqa: E402

RUNS = os.path.join(HERE, "..", "runs")


def load(split):
    return [json.loads(l) for l in open(os.path.join(HERE, f"{split}.jsonl"), encoding="utf-8")]


def evaluate(cfg: Config, split="dev", verbose=True):
    os.makedirs(RUNS, exist_ok=True)
    h = hashlib.sha1(cfg.key().encode()).hexdigest()[:10]
    path = os.path.join(RUNS, f"{split}-{h}.jsonl")
    done = {}
    if os.path.exists(path):
        for l in open(path, encoding="utf-8"):
            r = json.loads(l)
            done[r["id"]] = r
    with open(path, "a", encoding="utf-8") as f:
        for t in load(split):
            if t["id"] in done:
                continue
            t0 = time.time()
            ans, trace = run(t["q"], cfg, doc=t.get("doc"))
            r = {"id": t["id"], "cat": t["cat"], "ok": correct(t, ans), "answer": ans,
                 "steps": sum(1 for k, _ in trace if k == "model"),
                 "secs": round(time.time() - t0, 1), "trace": trace}
            done[t["id"]] = r
            f.write(json.dumps(r, ensure_ascii=False) + "\n"); f.flush()
            if verbose:
                print(f"  {'✓' if r['ok'] else '✗'} {t['id']:<14} {r['secs']:>5}s  {ans[:60]!r}", flush=True)
    by = defaultdict(list)
    for r in done.values():
        by[r["cat"]].append(r["ok"])
    cats = {c: round(100 * sum(v) / len(v)) for c, v in sorted(by.items())}
    total = round(sum(cats.values()) / len(cats), 1)      # macro average over categories
    return {"total": total, "cats": cats, "run": h,
            "avg_steps": round(sum(r["steps"] for r in done.values()) / len(done), 2)}


if __name__ == "__main__":
    tools = [a for a in sys.argv[1:] if not a.startswith("-")]
    print(json.dumps(evaluate(Config(tools=tools)), ensure_ascii=False))
