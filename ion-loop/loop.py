"""The gated self-improvement loop.

  1. measure  — run the arena on the dev split, find the weakest category
  2. propose  — take the next untried candidate change that targets that category
  3. judge    — rerun the arena; keep the change only if the total rises and no category
                 drops by more than TOLERANCE points; otherwise roll back
  4. repeat until no candidate is left; then score baseline vs. final on the hidden holdout split,
     which the loop never looks at while deciding.

Candidates are written by an "engineer" (a human or a stronger model). The small model is only examined.
"""
import copy
import json
import os
import sys
import time

sys.path.insert(0, os.path.dirname(__file__))
from ion.agent import Config          # noqa: E402
from arena.run import evaluate, TAG   # noqa: E402

TOLERANCE = 10      # allows one basic task (8 points) to flip; larger drops reject the change
HISTORY = os.path.join(os.path.dirname(__file__), f"history-{TAG}.jsonl")


def add_tool(name):
    def f(c):
        c.tools = c.tools + [name]
    return f


def setattr_(k, v):
    def f(c):
        setattr(c, k, v)
    return f


def both(*fs):
    def f(c):
        for g in fs:
            g(c)
    return f


# name, categories it targets, mutation, prerequisite (predicate on config)
CANDIDATES = [
    ("tool:calc", ["calc", "multistep"], add_tool("calc"), lambda c: True),
    ("tool:calc+guard", ["calc", "multistep"], both(add_tool("calc"), setattr_("tool_guard", True)),
     lambda c: "calc" not in c.tools),
    ("reflex:web_notes", ["web", "multistep"], setattr_("auto_web", True), lambda c: True),
    ("tool:web_search", ["web", "multistep"], add_tool("web_search"), lambda c: not c.auto_web),
    ("loop:decompose-llm", ["multistep"], setattr_("decompose", "llm"), lambda c: c.auto_web and not c.decompose),
    ("loop:decompose-entities", ["multistep"], setattr_("decompose", "entities"), lambda c: c.auto_web and not c.decompose),
    ("rag:auto", ["longdoc"], setattr_("auto_rag", True), lambda c: True),
    ("tool:doc_search", ["longdoc"], add_tool("doc_search"), lambda c: not c.auto_rag),
    ("prompt:fewshot", ["calc", "web", "multistep", "longdoc"], setattr_("fewshot", True), lambda c: bool(c.tools)),
    ("loop:verify", ["multistep", "calc", "web"], setattr_("verify", True), lambda c: bool(c.tools)),
    ("loop:plan", ["multistep"], setattr_("plan", True), lambda c: bool(c.tools)),
    ("steps:6", ["multistep"], setattr_("max_steps", 6), lambda c: bool(c.tools)),
    ("doc:inline-more", ["longdoc"], setattr_("doc_chars", 5000), lambda c: True),
    ("sampling:temp0.7", ["basic", "web", "multistep", "calc", "longdoc"], setattr_("temperature", 0.7), lambda c: True),
]


def log(row):
    row["t"] = time.strftime("%Y-%m-%d %H:%M:%S")
    with open(HISTORY, "a", encoding="utf-8") as f:
        f.write(json.dumps(row, ensure_ascii=False) + "\n")
    print(json.dumps(row, ensure_ascii=False), flush=True)


def main():
    cfg = Config()
    base = cur = evaluate(cfg)
    log({"event": "baseline", "score": cur})
    tried = set()
    while True:
        # weakest category that still has an applicable untried candidate
        pick = None
        for cat in sorted(cur["cats"], key=lambda c: cur["cats"][c]):
            for name, targets, mut, pre in CANDIDATES:
                if name not in tried and cat in targets and pre(cfg):
                    pick = (cat, name, mut)
                    break
            if pick:
                break
        if not pick:
            break
        cat, name, mut = pick
        tried.add(name)
        new_cfg = copy.deepcopy(cfg)
        mut(new_cfg)
        print(f"\n== weakest: {cat} ({cur['cats'][cat]}) → trying {name}", flush=True)
        new = evaluate(new_cfg)
        regress = {c: (cur["cats"][c], new["cats"][c]) for c in cur["cats"]
                   if new["cats"][c] < cur["cats"][c] - TOLERANCE}
        keep = new["total"] > cur["total"] and not regress
        log({"event": "candidate", "name": name, "target": cat, "before": cur["total"],
             "after": new["total"], "cats": new["cats"], "regressions": regress,
             "avg_steps": new["avg_steps"], "kept": keep})
        if keep:
            cfg, cur = new_cfg, new
    log({"event": "final-dev", "config": cfg.__dict__, "score": cur})
    # the hidden split: only now, only for the baseline and the final config
    hb = evaluate(Config(), "holdout")
    hf = evaluate(cfg, "holdout")
    log({"event": "holdout", "baseline": hb, "final": hf})
    json.dump(cfg.__dict__, open(os.path.join(os.path.dirname(__file__), f"champion-{TAG}.json"), "w"), indent=1)


if __name__ == "__main__":
    main()
