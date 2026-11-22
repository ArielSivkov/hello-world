"""The continual-learning loop with an acceptance gate.

Evaluation is prequential (test, then train): at cycle t the candidate is
trained on window t and judged on window t+1, which no model has trained on.
Window t+1 then joins the training pool. Nothing is ever tested after being
trained on, so there is no hidden test set to leak.

Selection policies decide which documents the model trains on:
  all     - every document of the new window
  random  - a random half
  hard    - the half the incumbent model predicts worst (self-directed)
"""
from __future__ import annotations

import argparse
import json
import random
import shutil
import time
from pathlib import Path

import numpy as np
import torch

from .data import load_jsonl
from .model import load_model, load_tokenizer, new_adapter, score, train
from .retrieval import BM25
from .stats import bits_per_token, gate, paired_diff


def select(policy: str, docs, nll, ntok, seed: int):
    if policy == "all":
        return list(docs)
    half = len(docs) // 2
    if policy == "random":
        order = list(range(len(docs)))
        random.Random(seed).shuffle(order)
    elif policy == "hard":
        order = list(np.argsort(-(nll / ntok)))
    else:
        raise ValueError(policy)
    return [docs[i] for i in order[:half]]


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--data", type=Path, default=Path("data"))
    ap.add_argument("--out", type=Path, required=True)
    ap.add_argument("--model", default="models/SmolLM2-135M")
    ap.add_argument("--policy", default="all", choices=["all", "random", "hard"])
    ap.add_argument("--replay", type=float, default=0.5, help="old docs per new doc")
    ap.add_argument("--train-dir", type=Path, default=None,
                    help="take training windows from here instead of --data (staleness control)")
    ap.add_argument("--anchor", type=float, default=0.0, help="general anchor docs per new doc")
    ap.add_argument("--epochs", type=int, default=2)
    ap.add_argument("--lr", type=float, default=2e-4)
    ap.add_argument("--no-gate", action="store_true", help="accept every candidate")
    ap.add_argument("--seed", type=int, default=0)
    a = ap.parse_args()

    torch.manual_seed(a.seed)
    a.out.mkdir(parents=True, exist_ok=True)
    windows = [load_jsonl(p) for p in sorted(a.data.glob("window_*.jsonl"))]
    cores = {n: load_jsonl(a.data / f"{n}.jsonl") for n in ("core_domain_old", "core_general")}
    anchor_docs = load_jsonl(a.data / "anchor_general.jsonl") if a.anchor > 0 else []
    train_windows = windows if a.train_dir is None else \
        [load_jsonl(p) for p in sorted(a.train_dir.glob("window_*.jsonl"))]
    tok = load_tokenizer(a.model)

    # base-model scores never change, so they are cached and shared across runs
    cache = a.data / f"base_scores_{Path(a.model).name}.npz"
    if cache.exists():
        z = np.load(cache)
        get = lambda k: (z[k + "_nll"], z[k + "_ntok"])
    else:
        base = load_model(a.model)
        store = {}
        def put(k, v):
            store[k + "_nll"], store[k + "_ntok"] = v
        for n, d in cores.items():
            put(n, score(base, tok, d))
        for w in range(1, len(windows)):
            put(f"fresh{w}", score(base, tok, windows[w]))
            put(f"rag{w}", score(base, tok, windows[w], BM25([d for win in windows[:w] for d in win])))
        del base
        np.savez(cache, **store)
        get = lambda k: (store[k + "_nll"], store[k + "_ntok"])
    base_core = {n: get(n) for n in cores}
    base_core_bpt = {n: bits_per_token(*v) for n, v in base_core.items()}
    base_fresh = {w: get(f"fresh{w}") for w in range(1, len(windows))}
    base_rag = {w: get(f"rag{w}") for w in range(1, len(windows))}
    print("base core bits/token:", {k: round(v, 4) for k, v in base_core_bpt.items()}, flush=True)

    incumbent: Path | None = None       # adapter directory, None = base model
    pool: list = []                      # documents already used for training
    log = []
    for t in range(len(windows) - 1):
        t0 = time.time()
        new, test = train_windows[t], windows[t + 1]
        if incumbent is None:
            model = new_adapter(load_model(a.model))
            inc = base_fresh[t + 1]
        else:
            model = load_model(a.model, incumbent, trainable=True)
            inc = score(model, tok, test)   # incumbent, before it sees window t
        sel_scores = score(model, tok, new) if a.policy == "hard" else (None, None)
        chosen = select(a.policy, new, *sel_scores, seed=a.seed + t)
        replay = random.Random(a.seed + t).sample(pool, min(len(pool), int(a.replay * len(chosen))))
        anchor = random.Random(a.seed + 1000 + t).sample(
            anchor_docs, min(len(anchor_docs), int(a.anchor * len(chosen))))
        loss = train(model, tok, chosen + replay + anchor, a.epochs, lr=a.lr, seed=a.seed + t)

        cand_fresh = score(model, tok, test)
        cand_core = {n: score(model, tok, d) for n, d in cores.items()}
        index = BM25([d for win in windows[:t + 1] for d in win])
        cand_rag = score(model, tok, test, index)

        ntok = cand_fresh[1]
        fresh = paired_diff(cand_fresh[0], inc[0], ntok)
        core = {n: paired_diff(cand_core[n][0], base_core[n][0], cand_core[n][1]) for n in cores}
        decision = {"accept": True, "reasons": ["gate disabled"]} if a.no_gate else \
            gate(fresh, core, base_core_bpt)

        row = {
            "cycle": t, "train_window": t, "test_window": t + 1,
            "n_train": len(chosen), "n_replay": len(replay), "n_anchor": len(anchor), "train_loss": round(loss, 4),
            "bpt": {
                "base": bits_per_token(*base_fresh[t + 1]),
                "base+retrieval": bits_per_token(*base_rag[t + 1]),
                "incumbent": bits_per_token(*inc),
                "candidate": bits_per_token(*cand_fresh),
                "candidate+retrieval": bits_per_token(*cand_rag),
            },
            "candidate_vs_incumbent": fresh,
            "candidate_vs_base": paired_diff(cand_fresh[0], base_fresh[t + 1][0], ntok),
            "candidate_vs_base+retrieval": paired_diff(cand_fresh[0], base_rag[t + 1][0], ntok),
            "candidate+retrieval_vs_base+retrieval": paired_diff(cand_rag[0], base_rag[t + 1][0], ntok),
            "core_vs_base": core,
            "decision": decision,
            "seconds": round(time.time() - t0),
        }
        log.append(row)
        (a.out / "log.json").write_text(json.dumps(log, indent=1))
        print(json.dumps({k: row[k] for k in ("cycle", "bpt", "candidate_vs_incumbent",
                                               "core_vs_base", "decision", "seconds")}), flush=True)

        pool += chosen
        if decision["accept"]:
            path = a.out / f"adapter_{t}"
            model.save_pretrained(str(path))
            if incumbent is not None:
                shutil.rmtree(incumbent, ignore_errors=True)
            incumbent = path
        del model


if __name__ == "__main__":
    main()
