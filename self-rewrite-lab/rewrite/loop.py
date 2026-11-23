"""Self-rewriting loop, stage 1: the system rewrites its own policy source code.

  python3 -m rewrite.loop --generations 10

Each generation: the proposer writes a complete new genome (rewrite/genome/*.py contract) → static
sandbox check → dev score in a child process → the gate keeps it only if the total rises and no
category drops by more than --tolerance. The holdout split is scored once at the end, for the seed and
the final champion, and is never used for a decision or shown to the proposer.

State lives in rewrite/lineage/<ION_TAG>/: champion.py, g000.py (seed), gNNN.py (each accepted
generation), attempts/ (every proposal, accepted or not) and history.jsonl.
"""
import argparse
import difflib
import json
import os
import shutil
import sys
import time

LAB = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path[:0] = [os.path.join(LAB, "ion-loop"), LAB]

from rewrite import gate, proposer, sandbox   # noqa: E402

TAG = os.environ.get("ION_TAG", "qwen2.5-1.5b")
SEED = os.path.join(LAB, "rewrite", "genome", "seed.py")


def short_diff(a, b, limit=60):
    d = list(difflib.unified_diff(a.splitlines(), b.splitlines(), "champion", "candidate", lineterm="", n=1))
    return "\n".join(d[:limit]) + ("\n..." if len(d) > limit else "")


def main(args):
    out = os.path.join(LAB, "rewrite", "lineage", TAG)
    os.makedirs(os.path.join(out, "attempts"), exist_ok=True)
    champ_path = os.path.join(out, "champion.py")
    if not os.path.exists(champ_path):
        shutil.copy(SEED, champ_path)
        shutil.copy(SEED, os.path.join(out, "g000.py"))
    hist_path = os.path.join(out, "history.jsonl")
    runlog = open(os.path.join(out, "eval.log"), "a", encoding="utf-8")

    def log(row):
        row["t"] = time.strftime("%Y-%m-%d %H:%M:%S")
        with open(hist_path, "a", encoding="utf-8") as f:
            f.write(json.dumps(row, ensure_ascii=False) + "\n")
        brief = {k: v for k, v in row.items() if k not in ("diff", "failures")}
        print(json.dumps(brief, ensure_ascii=False), flush=True)

    judge = gate.fingerprint()
    champ = open(champ_path, encoding="utf-8").read()
    cur = gate.score(champ, "dev", args.timeout, runlog)
    if "error" in cur:
        sys.exit(f"champion does not evaluate: {cur['error']}")
    prev = [json.loads(l) for l in open(hist_path, encoding="utf-8")] if os.path.exists(hist_path) else []
    start_gen = 1 + max([r.get("gen", 0) for r in prev] or [0])
    accepted_n = sum(1 for r in prev if r.get("event") == "attempt" and r.get("kept"))
    refused = [{"change": r["change"], "why": r["why"]} for r in prev if r.get("event") == "attempt" and not r["kept"]]
    log({"event": "start", "gen": start_gen - 1, "genome": cur["genome"], "dev": cur["total"], "cats": cur["cats"]})

    for gen in range(start_gen, start_gen + args.generations):
        pool = proposer.proposers()
        who, url = pool[gen % len(pool)]
        row = {"event": "attempt", "gen": gen, "proposer": who, "kept": False}
        try:
            reply = proposer.ask(proposer.build_prompt(champ, cur, refused), seed=gen,
                                 temperature=args.temperature, url=url)
        except Exception as e:     # noqa: BLE001
            row.update(change="(no reply)", why=f"proposer error: {e}"[:300])
            log(row)
            continue
        src, change = proposer.extract(reply)
        open(os.path.join(out, "attempts", f"a{gen:03d}.txt"), "w", encoding="utf-8").write(reply)
        row["change"] = change if src else "(unparseable)"
        if src is None:
            row["why"] = change
        elif src.strip() == champ.strip():
            row["why"] = "identical to the champion"
        else:
            row["diff"] = short_diff(champ, src)
            try:
                sandbox.check(src)
            except sandbox.Refused as e:
                row["why"] = f"sandbox: {e}"
            else:
                new = gate.score(src, "dev", args.timeout, runlog)
                gate.verify(judge)
                keep, regress = gate.decide(cur, new, args.tolerance)
                row.update(before=cur["total"], after=new.get("total"), cats=new.get("cats"),
                           genome=new.get("genome"), regressions=regress, kept=keep)
                if "error" in new:
                    row["why"] = new["error"]
                elif keep:
                    row["why"] = "accepted"
                    accepted_n += 1
                    champ, cur = src, new
                    open(champ_path, "w", encoding="utf-8").write(src)
                    open(os.path.join(out, f"g{accepted_n:03d}.py"), "w", encoding="utf-8").write(src)
                else:
                    row["why"] = (f"regression {regress}" if regress else
                                  f"total {cur['total']} -> {new['total']} (must rise)")
        if not row["kept"]:
            refused.append({"change": row["change"], "why": row["why"]})
        log(row)

    gate.verify(judge)
    seed = open(SEED, encoding="utf-8").read()
    log({"event": "end", "gen": start_gen + args.generations - 1, "accepted_total": accepted_n,
         "dev": cur["total"], "cats": cur["cats"],
         "holdout": gate.score(champ, "holdout", args.timeout, runlog),
         "holdout_seed": gate.score(seed, "holdout", args.timeout, runlog)})


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--generations", type=int, default=10)
    ap.add_argument("--tolerance", type=int, default=10)
    ap.add_argument("--temperature", type=float, default=0.7)
    ap.add_argument("--timeout", type=int, default=3600, help="seconds per evaluation")
    main(ap.parse_args())
