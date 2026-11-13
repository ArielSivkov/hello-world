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
