# selfloop

A measurement harness for continual, self-directed training of a small language model
on a stream of fresh documents (arXiv cs.CL).

## Question it answers

Does a model that keeps training on new documents get measurably better at what
arrives next, without getting worse at what it already knew, and does that beat
simply retrieving the new documents at inference time?

## Design

- **Metric:** bits per token of a paper's abstract given its title (lower is better).
- **Prequential evaluation:** at cycle `t` the candidate trains on week `t` and is judged
  on week `t+1`, which no model has trained on. Then week `t+1` joins the training pool.
- **Gate:** a candidate adapter replaces the incumbent only if it is significantly better
  on the unseen week (paired bootstrap, 95%) and no core set is more than 1% worse than
  the untouched base model.
- **Core sets:** old in-domain papers (2022 cs.CL) and old out-of-domain papers
  (maths, optics, neuroscience, economics).
- **Baselines:** base model, and base model with BM25 retrieval over everything seen so far.
- **Selection policies:** `all`, `random` half, `hard` half (the documents the current
  model predicts worst, a first self-directed policy).

## Run

```
python -m selfloop.fetch                       # download windows and core sets
python -m selfloop.loop --out runs/all         # continual loop, gate on
python -m selfloop.loop --out runs/hard --policy hard
python -m pytest -q
```

Use `--model` for a larger model; everything else stays the same.

## Results so far (SmolLM2-135M, CPU, one seed)

Bits per token on the following, unseen week. Lower is better. Five weekly cycles,
200 fresh cs.CL papers per week (100 for the half-data policies).

| run | what changes | cycles accepted | final candidate | final base+retrieval |
|---|---|---|---|---|
| `all` | fresh data, no anchor replay | 1/5 | 5.223 | 5.300 |
| `anchor` | fresh data + general anchor replay | 5/5 | 5.148 | 5.300 |
| `stale` | 2022 cs.CL data + anchor replay | 3/5 | 5.366 | 5.300 |
| `random` | random half of fresh data + anchor | 5/5 | 5.202 | 5.300 |
| `hard` | hardest half of fresh data + anchor | 2/5 | 5.230 | 5.300 |

Base model on the final week: 5.464.

- Without general replay, every later cycle is rejected for out-of-domain regression
  (about +0.07 bits/token against a limit of +0.042). Anchor replay holds it near +0.02.
- Training on fresh data beats retrieval alone in every cycle, and the gap widens
  (0.04 to 0.15). Training plus retrieval is best throughout.
- About a third of the gain is reachable from old in-domain data (style and domain);
  the rest needs recent data. Stale training stops improving after two cycles.
- Choosing the documents the model predicts worst did not beat a random half on fresh
  data and caused more out-of-domain regression, enough to fail the gate from cycle 2.
  After a rejection the two runs continue from different adapters, so only cycles 0-1
  compare like for like.

Limits: one seed, a 135M model, and a text-prediction metric rather than factual QA.
The bootstrap intervals cover document sampling, not training randomness.

```
python -m selfloop.report runs/all runs/anchor runs/stale runs/random runs/hard
```

## Stage 2: self-edits (prototype, not yet run on the model)

`--train-on self` replaces the chosen documents by texts the incumbent model writes
about them (`selfloop/selfedit.py`, SEAL-style "implications" prompt); `self+raw` trains
on both; `raw` is stage 0b unchanged. Metric, prequential protocol and gate are the
same. Every self-edit is saved to `<out>/selfedits_<t>.jsonl`, and per-document test
scores to `<out>/scores_<t>.npz` so runs can be compared paired:

```
python -m selfloop.loop --out runs/self --anchor 0.5 --train-on self
python -m selfloop.loop --out runs/selfraw --anchor 0.5 --train-on self+raw
python -m selfloop.loop --out runs/fake --anchor 0.5 --train-on self --generator fake
python -m selfloop.compare runs/selfraw runs/anchor2
```

`--generator fake` is a deterministic, model-free generator (the abstract's own
sentences, rotated); it is used by the tests and as a "reformatting only" control.
