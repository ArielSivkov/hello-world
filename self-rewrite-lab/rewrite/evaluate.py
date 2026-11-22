"""Score one genome on one arena split. Meant to run in its own process (the gate kills it on timeout).

  python3 -m rewrite.evaluate --genome rewrite/genome/seed.py --split dev

The last stdout line is `RESULT <json>`. Per-task results are cached by (genome source, task),
so a rerun of the same genome is free and an interrupted run resumes.
"""
import argparse
import hashlib
import json
import os
import sys
import time
from collections import defaultdict

LAB = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
ION = os.path.join(LAB, "ion-loop")
sys.path[:0] = [ION, LAB]

from ion import agent                     # noqa: E402
from ion.agent import Config              # noqa: E402
from arena.run import load as load_split  # noqa: E402
from arena.check import correct           # noqa: E402
from rewrite import sandbox               # noqa: E402

TAG = os.environ.get("ION_TAG", "qwen2.5-1.5b")
RUNS = os.path.join(LAB, "rewrite", "runs", TAG)


def genome_id(source):
    return hashlib.sha1(source.encode()).hexdigest()[:12]


def apply(mod):
    """Install the genome into the agent. Returns the Config to run with."""
    if mod.SYSTEM_EXTRA:
        agent.BASE_PROMPT = agent.BASE_PROMPT + "\n" + mod.SYSTEM_EXTRA
        agent.BASE_PROMPT_HE = agent.BASE_PROMPT_HE + "\n" + mod.SYSTEM_EXTRA
    return Config(**mod.CONFIG)


def solve(mod, cfg, task):
    try:
        q = mod.prepare(task["q"], task.get("doc"))
    except Exception as e:     # noqa: BLE001  a crashing hook fails the task, not the run
        return "", [("hook", f"prepare crashed: {type(e).__name__}: {e}"[:200])]
    ans, trace = agent.run(q, cfg, doc=task.get("doc"))
    try:
        out = mod.finalize(task["q"], ans)
    except Exception as e:     # noqa: BLE001
        return "", trace + [("hook", f"finalize crashed: {type(e).__name__}: {e}"[:200])]
    if q != task["q"]:
        trace = [("prepared", q[:300])] + trace
    if out != ans:
        trace = trace + [("finalized", f"{ans[:120]!r} -> {out[:120]!r}")]
    return out, trace


def evaluate(source, split="dev", verbose=True):
    mod = sandbox.load(source)
    cfg = apply(mod)
    os.makedirs(RUNS, exist_ok=True)
    path = os.path.join(RUNS, f"{split}-{genome_id(source)}.jsonl")
    done = {}
    if os.path.exists(path):
        for line in open(path, encoding="utf-8"):
            r = json.loads(line)
            done[r["id"]] = r
    tasks = load_split(split)
    with open(path, "a", encoding="utf-8") as f:
        for t in tasks:
            if t["id"] in done:
                continue
            t0 = time.time()
            ans, trace = solve(mod, cfg, t)
            r = {"id": t["id"], "cat": t["cat"], "kind": t.get("kind", t["cat"]), "ok": correct(t, ans),
                 "answer": ans, "secs": round(time.time() - t0, 1), "trace": trace}
            done[t["id"]] = r
            f.write(json.dumps(r, ensure_ascii=False) + "\n")
            f.flush()
            if verbose:
                print(f"  {'✓' if r['ok'] else '✗'} {t['id']:<14} {r['secs']:>5}s  {ans[:60]!r}", flush=True)
    by, kinds = defaultdict(list), defaultdict(list)
    for t in tasks:
        r = done[t["id"]]
        by[r["cat"]].append(r["ok"])
        kinds[r["kind"]].append(r["ok"])
    cats = {c: round(100 * sum(v) / len(v)) for c, v in sorted(by.items())}
    result = {"genome": genome_id(source), "split": split,
              "total": round(sum(cats.values()) / len(cats), 1), "cats": cats,
              "kinds": {k: f"{sum(v)}/{len(v)}" for k, v in sorted(kinds.items())}}
    if split == "dev":     # the proposer may learn from dev failures; holdout failures never leave this process
        task_by_id = {t["id"]: t for t in tasks}
        result["failures"] = [
            {"id": r["id"], "cat": r["cat"], "kind": r["kind"], "q": task_by_id[r["id"]]["q"][:300],
             "expected": task_by_id[r["id"]]["answers"][:3], "got": r["answer"][:150],
             "trace": [f"{k}: {str(v)[:160]}" for k, v in r["trace"]][-6:]}
            for r in (done[t["id"]] for t in tasks) if not r["ok"]]
    return result


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--genome", required=True)
    ap.add_argument("--split", default="dev", choices=["dev", "holdout"])
    ap.add_argument("--quiet", action="store_true")
    a = ap.parse_args()
    res = evaluate(open(a.genome, encoding="utf-8").read(), a.split, verbose=not a.quiet)
    print("RESULT " + json.dumps(res, ensure_ascii=False), flush=True)
