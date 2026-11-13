"""Metric and significance testing.

The metric is bits per token of a paper's abstract given its title. Lower is
better. Comparisons are paired over documents and use a bootstrap interval.
"""
from __future__ import annotations

import math

import numpy as np

LN2 = math.log(2.0)


def bits_per_token(nll: np.ndarray, ntok: np.ndarray) -> float:
    return float(nll.sum() / ntok.sum() / LN2)


def paired_diff(nll_a, nll_b, ntok, n_boot: int = 2000, seed: int = 0) -> dict:
    """Difference a - b in bits/token with a 95% paired bootstrap interval.

    Negative means `a` is better than `b`. Both were scored on the same
    documents and the same target tokens, so `ntok` is shared.
    """
    nll_a, nll_b, ntok = (np.asarray(x, dtype=np.float64) for x in (nll_a, nll_b, ntok))
    rng = np.random.default_rng(seed)
    idx = rng.integers(0, len(ntok), size=(n_boot, len(ntok)))
    tok = ntok[idx].sum(1)
    diffs = (nll_a[idx].sum(1) - nll_b[idx].sum(1)) / tok / LN2
    lo, hi = np.percentile(diffs, [2.5, 97.5])
    return {"diff": bits_per_token(nll_a, ntok) - bits_per_token(nll_b, ntok),
            "lo": float(lo), "hi": float(hi)}


def gate(fresh: dict, cores: dict[str, dict], core_base_bpt: dict[str, float],
         max_core_regress: float = 0.01) -> dict:
    """Decide whether a candidate replaces the incumbent.

    fresh: paired_diff(candidate, incumbent) on documents neither has trained on.
    cores: per core set, paired_diff(candidate, BASE model). Comparing against
    the base, not the incumbent, stops small regressions from accumulating.
    """
    reasons = []
    if not fresh["hi"] < 0:
        reasons.append(f"no significant gain on fresh data (upper bound {fresh['hi']:+.4f})")
    for name, d in cores.items():
        limit = max_core_regress * core_base_bpt[name]
        if d["hi"] > limit:
            reasons.append(f"core '{name}' regressed (upper bound {d['hi']:+.4f} > {limit:.4f})")
    return {"accept": not reasons, "reasons": reasons}
