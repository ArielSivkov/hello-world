"""The continual-learning loop with an acceptance gate.

Evaluation is prequential (test, then train): at cycle t the candidate is
trained on window t and judged on window t+1, which no model has trained on.
Window t+1 then joins the training pool. Nothing is ever tested after being
trained on, so there is no hidden test set to leak.

Selection policies decide which documents the model trains on:
  all     - every document of the new window
  random  - a random half
  hard    - the half the incumbent model predicts worst (self-directed)

Stage 2 (--train-on): what the adapter trains on for the chosen documents
  raw       - the documents themselves (stage 0b, the default)
  self      - only self-edits the incumbent wrote from them (selfedit.py)
  self+raw  - both
The metric, the prequential protocol and the gate are the same in every mode.
"""
from __future__ import annotations

import argparse
import json
import pickle
import random
import shutil
import time
from pathlib import Path

import numpy as np
import torch

from .data import load_jsonl
from .model import load_model, load_tokenizer, new_adapter, score, train
from .retrieval import BM25
from .selfedit import MODES, FakeGenerator, ModelGenerator, build_training_set, save_edits
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
    ap.add_argument("--train-on", default="raw", choices=MODES,
                    help="raw documents, self-edits written by the incumbent, or both")
    ap.add_argument("--generator", default="model", choices=["model", "fake"])
    ap.add_argument("--edit-style", default="implications", choices=["implications", "restate", "qa"])
    ap.add_argument("--edits-per-doc", type=int, default=2)
    ap.add_argument("--edit-tokens", type=int, default=160, help="max new tokens per self-edit")
    ap.add_argument("--cycles", type=int, default=None, help="stop after this many cycles")
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
    # Saved after every piece, so a restart keeps what was already scored (the container is reclaimed when
    # idle, and scoring everything takes longer than one life of the machine).
    store = dict(np.load(cache)) if cache.exists() else {}
    jobs = [(n, d, None) for n, d in cores.items()]
    jobs += [(f"fresh{w}", windows[w], None) for w in range(1, len(windows))]
    jobs += [(f"rag{w}", windows[w], w) for w in range(1, len(windows))]
    base = None
    for key, docs, w in jobs:
        if key + "_nll" in store:
            continue
        if base is None:
            base = load_model(a.model)
        index = BM25([d for win in windows[:w] for d in win]) if w else None
        store[key + "_nll"], store[key + "_ntok"] = score(base, tok, docs, index) if index else score(base, tok, docs)
        tmp = cache.with_name(cache.name + ".tmp.npz")
        np.savez(tmp, **store)
        tmp.replace(cache)
        print(f"base scores: {key} saved", flush=True)
    del base
    get = lambda k: (store[k + "_nll"], store[k + "_ntok"])
    base_core = {n: get(n) for n in cores}
    base_core_bpt = {n: bits_per_token(*v) for n, v in base_core.items()}
    base_fresh = {w: get(f"fresh{w}") for w in range(1, len(windows))}
    base_rag = {w: get(f"rag{w}") for w in range(1, len(windows))}
    print("base core bits/token:", {k: round(v, 4) for k, v in base_core_bpt.items()}, flush=True)

    incumbent: Path | None = None       # adapter directory, None = base model
    pool: list = []                      # documents already used for training
    log = []
    # Resume after a restart: the state is saved at the end of every cycle (the machine was restarted twice
    # in one morning and each restart threw away hours of work).
    state_path = a.out / "state.pkl"
    if state_path.exists():
        st = pickle.loads(state_path.read_bytes())
        log, pool = st["log"], st["pool"]
        incumbent = Path(st["incumbent"]) if st["incumbent"] else None
        print(f"resuming after cycle {len(log) - 1}", flush=True)
    n_cycles = len(windows) - 1 if a.cycles is None else min(a.cycles, len(windows) - 1)
    for t in range(len(log), n_cycles):
        t0 = time.time()
        torch.manual_seed(a.seed + t)    # each cycle reproducible on its own, resumed or not
        new, test = train_windows[t], windows[t + 1]
        if incumbent is None:
            model = new_adapter(load_model(a.model))
            inc = base_fresh[t + 1]
        else:
            model = load_model(a.model, incumbent, trainable=True)
            inc = score(model, tok, test)   # incumbent, before it sees window t
        sel_scores = score(model, tok, new) if a.policy == "hard" else (None, None)
        chosen = select(a.policy, new, *sel_scores, seed=a.seed + t)
        # stage 2: the incumbent (this model, before training) writes the training data
        g0 = time.time()
        gen = None
        if a.train_on != "raw":
            gen = FakeGenerator(a.edit_style) if a.generator == "fake" else \
                ModelGenerator(model, tok, a.edit_style, max_new_tokens=a.edit_tokens)
        items = build_training_set(a.train_on, chosen, gen, a.edits_per_doc, seed=a.seed + t,
                                   test_ids={d.id for d in test})
        if gen is not None:
            save_edits(a.out / f"selfedits_{t}.jsonl", [d for d in items if "#se" in d.id])
        gen_seconds = round(time.time() - g0)
        # replay and anchor amounts follow the number of source documents, as in stage 0b
        replay = random.Random(a.seed + t).sample(pool, min(len(pool), int(a.replay * len(chosen))))
        anchor = random.Random(a.seed + 1000 + t).sample(
            anchor_docs, min(len(anchor_docs), int(a.anchor * len(chosen))))
        loss = train(model, tok, items + replay + anchor, a.epochs, lr=a.lr, seed=a.seed + t)

        cand_fresh = score(model, tok, test)
        cand_core = {n: score(model, tok, d) for n, d in cores.items()}
        index = BM25([d for win in windows[:t + 1] for d in win])
        cand_rag = score(model, tok, test, index)

        ntok = cand_fresh[1]
        # per-document scores, so two runs can be compared paired (selfloop.compare)
        np.savez(a.out / f"scores_{t}.npz", ids=np.array([d.id for d in test]),
                 cand_nll=cand_fresh[0], cand_rag_nll=cand_rag[0], ntok=ntok,
                 base_nll=base_fresh[t + 1][0], base_rag_nll=base_rag[t + 1][0])
        fresh = paired_diff(cand_fresh[0], inc[0], ntok)
        core = {n: paired_diff(cand_core[n][0], base_core[n][0], cand_core[n][1]) for n in cores}
        decision = {"accept": True, "reasons": ["gate disabled"]} if a.no_gate else \
            gate(fresh, core, base_core_bpt)

        row = {
            "cycle": t, "train_window": t, "test_window": t + 1,
            "train_on": a.train_on, "generator": gen.name if gen else None,
            "n_items": len(items), "gen_seconds": gen_seconds,
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

        pool += items   # in raw mode items == chosen, as before
        if decision["accept"]:
            path = a.out / f"adapter_{t}"
            model.save_pretrained(str(path))
            old, incumbent = incumbent, path
        tmp = a.out / "state.pkl.tmp"
        tmp.write_bytes(pickle.dumps({"log": log, "pool": pool,
                                      "incumbent": str(incumbent) if incumbent else None}))
        tmp.replace(state_path)          # atomic: a restart mid-write keeps the previous state
        if decision["accept"] and old is not None:
            shutil.rmtree(old, ignore_errors=True)   # only after the new state points at the new adapter
        del model


if __name__ == "__main__":
    main()
