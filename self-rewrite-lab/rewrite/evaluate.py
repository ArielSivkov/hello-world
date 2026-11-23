"""Score one genome on one arena split. Run by the gate in its own process; this process is the judge
and never executes genome code: the hooks run in an isolated worker (rewrite/isolation.py).

  python3 -m rewrite.evaluate --genome rewrite/genome/seed.py --split dev --out result.json

The result is written to --out (a path the genome cannot reach), never parsed from stdout.
Per-task results are cached by (judge fingerprint, genome source, task); `ok` is recomputed from the
cached answer on every load, so a cache entry cannot vouch for itself.
"""
import argparse
import hashlib
import json
import zlib
import os
import sys
import time
from collections import defaultdict

LAB = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
ION = os.path.join(LAB, "ion-loop")
sys.path[:0] = [ION, LAB]

from ion import agent                          # noqa: E402
from ion.agent import Config                   # noqa: E402
from arena.run import load as load_split       # noqa: E402
from rewrite import sandbox                    # noqa: E402
from rewrite.check_strict import correct       # noqa: E402
from rewrite.isolation import HookWorker, HookError, HookFailed   # noqa: E402

TAG = os.environ.get("ION_TAG", "qwen2.5-1.5b")
RUNS = os.path.join(LAB, "rewrite", "runs", TAG)
SPLITS = ("dev", "holdout", "shadow")


def dev_halves(tasks):
    """Split dev into a FEEDBACK half (its failures are shown to the proposer) and a GATE half (the decision
    is made on it, and the proposer never sees its questions). Alternating within each task kind, so both
    halves hold every kind. Round 2 of the black agent memorised the questions it was shown; this split is
    what makes that worthless."""
    seen, feedback, gate_half = {}, [], []
    for t in tasks:
        k = t.get("kind", t["cat"])
        (feedback if seen.get(k, 0) % 2 == 0 else gate_half).append(t)
        seen[k] = seen.get(k, 0) + 1
    return feedback, gate_half


def genome_id(source):
    return hashlib.sha1(source.encode()).hexdigest()[:12]


def others_by_kind():
    """Answers of every task, grouped by kind, over all splits (judge side only)."""
    pool = {}
    for split in SPLITS:
        try:
            for t in load_split(split):
                pool.setdefault(t.get("kind", t["cat"]), []).append((t["id"], split, t["answers"]))
        except OSError:
            pass
    return pool


def grade(task, answer, split, pool):
    others = [a for tid, sp, ans in pool.get(task.get("kind", task["cat"]), [])
              if not (tid == task["id"] and sp == split) for a in ans]
    return correct(task, answer, others)


def judge_id():
    from rewrite.gate import fingerprint
    return hashlib.sha1(json.dumps(fingerprint(), sort_keys=True).encode()).hexdigest()[:10]


DECOY = "לא ידוע"     # used only when no other answer exists yet


def solve(worker, cfg, task, decoy=DECOY):
    """decoy: the model's own answer to a DIFFERENT task. The genome cannot tell it from a real answer, and
    it is not a correct answer, so nothing leaks; a policy that is still right with it ignores the model."""
    try:
        q = worker.call("prepare", q=task["q"], doc=task.get("doc"))[:len(task["q"]) + 400]
    except HookFailed as e:     # a hook that raises fails its task, not the run
        return "", [("hook", "prepare failed")], ""     # the genome's own error text is never passed on
    ans, trace = agent.run(q, cfg, doc=task.get("doc"))
    try:
        out = worker.call("finalize", q=task["q"], a=ans)
    except HookFailed as e:
        return "", trace + [("hook", "finalize failed")], ""
    try:      # what does the policy answer when the model's answer is a decoy? (see blind_correct below)
        blind = worker.call("finalize", q=task["q"], a=decoy)
    except HookFailed:
        blind = ""
    if q != task["q"]:
        trace = [("prepared", q[:300])] + trace
    if out != ans:
        trace = trace + [("finalized", f"{ans[:120]!r} -> {out[:120]!r}")]
    return out, trace, blind      # blind is kept apart from the trace: the trace is shown to the proposer


def evaluate(source, split="dev", verbose=True):
    sandbox.check(source)
    worker = HookWorker(source)          # raises HookError (refused) if the genome cannot even start
    try:
        cfg_dict = sandbox.validate_config(worker.config)
        extra = sandbox.validate_extra(worker.system_extra)
        if extra:
            agent.BASE_PROMPT = agent.BASE_PROMPT + "\n" + extra
            agent.BASE_PROMPT_HE = agent.BASE_PROMPT_HE + "\n" + extra
        cfg = Config(**cfg_dict)
        os.makedirs(RUNS, exist_ok=True)
        path = os.path.join(RUNS, f"{split}-{judge_id()}-{genome_id(source)}.jsonl")
        tasks = load_split(split)
        pool = others_by_kind()
        by_id = {t["id"]: t for t in tasks}
        done = {}
        if os.path.exists(path):
            for line in open(path, encoding="utf-8"):
                r = json.loads(line)
                if r.get("id") in by_id:
                    r["ok"] = grade(by_id[r["id"]], r.get("answer", ""), split, pool)
                    done[r["id"]] = r
        with open(path, "a", encoding="utf-8") as f:
            for t in tasks:
                if t["id"] in done:
                    continue
                t0 = time.time()
                prior = [r["answer"] for r in done.values() if r["id"] != t["id"] and r.get("answer")]
                decoy = prior[zlib.crc32(t["id"].encode()) % len(prior)] if prior else DECOY
                ans, trace, blind = solve(worker, cfg, t, decoy)
                r = {"id": t["id"], "cat": t["cat"], "kind": t.get("kind", t["cat"]), "ok": grade(t, ans, split, pool),
                     "answer": ans, "blind": blind[:200], "secs": round(time.time() - t0, 1), "trace": trace}
                done[t["id"]] = r
                f.write(json.dumps(r, ensure_ascii=False) + "\n")
                f.flush()
                if verbose:
                    print(f"  {'✓' if r['ok'] else '✗'} {t['id']:<14} {r['secs']:>5}s  {ans[:60]!r}", flush=True)
    finally:
        worker.close()
    # Tasks the policy gets right even when the model's answer is empty: the policy is answering by itself
    # (black agent round 3 hid lookup tables of antonyms, translations and years behind chr(ord(c)+1)).
    blind_ok = 0
    for t in tasks:
        blind = done[t["id"]].get("blind", "")
        blind_ok += bool(blind) and grade(t, blind, split, pool)
    shown = tasks
    if split == "dev":
        shown, tasks = dev_halves(tasks)      # metrics below are on the gate half only
    by, kinds = defaultdict(list), defaultdict(list)
    for t in tasks:
        r = done[t["id"]]
        by[t["cat"]].append(r["ok"])
        kinds[t.get("kind", t["cat"])].append(r["ok"])
    cats = {c: round(100 * sum(v) / len(v)) for c, v in sorted(by.items())}
    result = {"genome": genome_id(source), "split": split, "n_correct": sum(done[t["id"]]["ok"] for t in tasks),
              "n_tasks": len(tasks), "total": round(sum(cats.values()) / len(cats), 1), "cats": cats,
              "kinds": {k: f"{sum(v)}/{len(v)}" for k, v in sorted(kinds.items())},
              "passed": sorted(t["id"] for t in tasks if done[t["id"]]["ok"]),
              "blind_correct": blind_ok}
    if split == "dev":
        # failures the proposer may learn from, from the FEEDBACK half only: the question and what the agent
        # did, never the expected answer
        result["feedback_correct"] = sum(done[t["id"]]["ok"] for t in shown)
        fb = defaultdict(list)
        for t in shown:
            fb[t["cat"]].append(done[t["id"]]["ok"])
        result["feedback_cats"] = {c: round(100 * sum(v) / len(v)) for c, v in sorted(fb.items())}
        result["failures"] = [
            {"id": t["id"], "cat": t["cat"], "kind": t.get("kind", t["cat"]), "q": t["q"][:300],
             "got": done[t["id"]]["answer"][:150],
             "trace": [f"{k}: {str(v)[:160]}" for k, v in done[t["id"]]["trace"]][-6:]}
            for t in shown if not done[t["id"]]["ok"]]
    return result


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--genome", required=True)
    ap.add_argument("--split", default="dev", choices=SPLITS)
    ap.add_argument("--out", help="write the result JSON here (the gate passes a private path)")
    ap.add_argument("--quiet", action="store_true")
    a = ap.parse_args()
    try:
        res = evaluate(open(a.genome, encoding="utf-8").read(), a.split, verbose=not a.quiet)
    except sandbox.Refused as e:
        res = {"refused": f"sandbox: {e}"}
    except HookError as e:
        res = {"refused": f"hook: {e}"}
    if a.out:
        with open(a.out, "w", encoding="utf-8") as f:
            json.dump(res, f, ensure_ascii=False)
    else:
        print(json.dumps(res, ensure_ascii=False))
