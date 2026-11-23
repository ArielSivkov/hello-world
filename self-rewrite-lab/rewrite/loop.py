"""Self-rewriting loop, stage 1: the system rewrites its own policy source code.

  python3 -m rewrite.loop --generations 10

Each generation: the proposer writes a complete new genome (--format full), or only the change, which
rewrite/edits.py applies to the champion to produce the complete file (--format edits) → static
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
RUN = os.environ.get("REWRITE_RUN", f"{TAG}-strict")     # the judge changed on 23.11; older runs stay in lineage/<TAG>/
SEED = os.path.join(LAB, "rewrite", "genome", "seed.py")


def public_why(row):
    """What the next proposer is told about a refusal. Coarse on purpose: the red team (r2, ed9/ed9b) used
    "contains an answer of the test set" and "+k tasks" as an oracle for dev answers. Format and syntax
    errors are passed on, since the proposer needs them to write a valid reply."""
    why = str(row.get("why", ""))
    if why.startswith("edit:") or (why.startswith("sandbox:") and "answer of the test set" not in why):
        return why
    return "not accepted"      # crash, refusal or no improvement look the same (red team r3: one bit a round)


def short_diff(a, b, limit=60):
    d = list(difflib.unified_diff(a.splitlines(), b.splitlines(), "champion", "candidate", lineterm="", n=1))
    return "\n".join(d[:limit]) + ("\n..." if len(d) > limit else "")


def main(args):
    out = os.path.join(LAB, "rewrite", "lineage", RUN)
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
    for attempt in range(3):      # a transient failure (e.g. the worker cannot start) is retried, not fatal
        cur = gate.score(champ, "dev", args.timeout, runlog)
        if "error" not in cur:
            break
        time.sleep(30)
    else:
        sys.exit(f"champion does not evaluate: {cur['error']}")
    seed_src = open(SEED, encoding="utf-8").read()
    seed_dev = cur if champ == seed_src else gate.score(seed_src, "dev", args.timeout, runlog)
    sys.path.insert(0, os.path.join(LAB, "ion-loop"))
    from arena.run import load as load_split
    dev_answers = [a for t in load_split("dev") for a in t["answers"]]
    prev = [json.loads(l) for l in open(hist_path, encoding="utf-8")] if os.path.exists(hist_path) else []
    start_gen = 1 + max([r.get("gen", 0) for r in prev] or [0])
    accepted_n = sum(1 for r in prev if r.get("event") == "attempt" and r.get("kept"))
    refused = [{"change": r["change"], "why": public_why(r)} for r in prev if r.get("event") == "attempt" and not r["kept"]]
    log({"event": "start", "gen": start_gen - 1, "genome": cur["genome"], "dev": cur["total"], "cats": cur["cats"]})

    for gen in range(start_gen, start_gen + args.generations):
        pool = proposer.proposers()
        who, url = pool[gen % len(pool)]
        row = {"event": "attempt", "gen": gen, "proposer": who, "kept": False, "format": args.format}
        prompt = proposer.build_prompt(champ, cur, refused, fmt=args.format)
        src, no_reply = None, None
        for k in range(1 + args.retries):     # a reply that cannot be parsed is retried with the error
            try:
                reply = proposer.ask(prompt, seed=gen + 1000 * k, temperature=args.temperature, url=url)
            except Exception as e:     # noqa: BLE001
                if k == 0:
                    no_reply = f"proposer error: {e}"[:300]
                break      # on a retry, keep the parse error of the first reply
            name = f"a{gen:03d}.txt" if k == 0 else f"a{gen:03d}-retry{k}.txt"
            open(os.path.join(out, "attempts", name), "w", encoding="utf-8").write(proposer.scrub(reply))
            src, change, why = proposer.parse(reply, champ, args.format)
            if src is not None:
                break
            row.setdefault("parse_errors", []).append(why)
            prompt = proposer.retry_prompt(prompt, why)
        if no_reply:     # as before: a server error is logged but is not a refused proposal
            row.update(change="(no reply)", why=no_reply)
            log(row)
            continue
        row["change"] = change
        if src is None:
            row["why"] = why
        elif src.strip() == champ.strip():
            row["why"] = "identical to the champion"
        else:
            row["diff"] = short_diff(champ, src)
            try:
                sandbox.check(src)
                hit = sandbox.contains_test_answer(src, dev_answers)
                if hit:
                    raise sandbox.Refused(hit)
            except sandbox.Refused as e:
                row["why"] = f"sandbox: {e}"
            else:
                try:
                    new = gate.score(src, "dev", args.timeout, runlog)
                    gate.verify(judge)
                    keep, regress, why = gate.decide(cur, new, seed_dev, args.tolerance, args.margin)
                except gate.JudgeChanged:
                    raise
                except Exception as e:     # noqa: BLE001  a broken candidate is a refusal, never a crash
                    new, keep, regress, why = {}, False, {}, f"loop error: {type(e).__name__}"
                row.update(before=cur["total"], after=new.get("total"), cats=new.get("cats"),
                           n_correct=new.get("n_correct"), genome=new.get("genome"), regressions=regress,
                           kept=keep, why=why)
                if keep:
                    accepted_n += 1
                    champ, cur = src, new
                    open(champ_path, "w", encoding="utf-8").write(src)
                    open(os.path.join(out, f"g{accepted_n:03d}.py"), "w", encoding="utf-8").write(src)
        if not row["kept"]:
            refused.append({"change": row["change"], "why": public_why(row)})
        log(row)

    gate.verify(judge)
    end = {"event": "end", "gen": start_gen + args.generations - 1, "accepted_total": accepted_n,
           "dev": cur["total"], "cats": cur["cats"], "dev_seed": seed_dev["total"]}
    for split in ("holdout", "shadow"):      # measured once, never used for a decision or shown to a proposer
        if os.path.exists(os.path.join(LAB, "ion-loop", "arena", f"{split}.jsonl")):
            for who, src in (("champion", champ), ("seed", seed_src)):
                r = gate.score(src, split, args.timeout, runlog)
                end[f"{split}_{who}"] = {k: r.get(k) for k in ("total", "cats", "n_correct", "error") if k in r}
    log(end)


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--generations", type=int, default=10)
    ap.add_argument("--tolerance", type=int, default=10)
    ap.add_argument("--margin", type=int, default=2, help="minimum rise in correct dev tasks")
    ap.add_argument("--temperature", type=float, default=0.7)
    ap.add_argument("--timeout", type=int, default=3600, help="seconds per evaluation")
    ap.add_argument("--format", choices=["full", "edits"], default="edits",
                    help="full: the proposer returns the whole file; edits: it returns only the change "
                         "(SET lines, SYSTEM_EXTRA, new functions), applied to the champion by rewrite/edits.py")
    ap.add_argument("--retries", type=int, default=1, help="extra tries when a reply cannot be parsed")
    main(ap.parse_args())
