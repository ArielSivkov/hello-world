"""Asks a model to rewrite the genome. By default that model is the agent's own model (true self-rewriting);
point REWRITE_PROPOSER_URL / REWRITE_PROPOSER_MODEL at any OpenAI-compatible server to use another one.

The proposer sees: the current genome, its dev scores, dev failures from the weakest category, and the
recent attempts the gate refused. It never sees holdout tasks or results.
"""
import json
import os
import re

import requests

URL = os.environ.get("REWRITE_PROPOSER_URL", os.environ.get("ION_BASE_URL", "http://localhost:8080/v1"))
MODEL = os.environ.get("REWRITE_PROPOSER_MODEL", os.environ.get("ION_MODEL", "local"))

INSTRUCTIONS = """You are improving the policy file of a small Hebrew question-answering agent.
The agent is a fixed program; this policy file is the only part you may change. An automatic judge
scores every version on a test set and keeps your version only if the total score rises and no
category drops by more than 10 points.

What the policy file controls:
- CONFIG: switches of the agent (keep the same keys; you may change values).
- SYSTEM_EXTRA: text appended to the agent's system prompt.
- prepare(question, doc): returns the question text the agent will see (doc is a long document or None).
- finalize(question, answer): returns the final answer that the judge checks. The judge accepts an
  answer if it contains one of the expected strings (numbers are matched as whole numbers).

Rules: allowed imports are re, math, json, unicodedata, string, collections, itertools, functools.
No while loops, no lambdas, no classes, no print, no names starting with "_". Keep both functions.

Make ONE focused change that should fix some of the failures shown, without breaking other categories.
Reply with the complete new file in a single ```python code block. Its first line must be a comment:
# CHANGE: <one short sentence describing your change>"""


def build_prompt(source, result, refused, n_fail=6):
    cats = result["cats"]
    weakest = sorted(cats, key=lambda c: cats[c])
    fails = sorted(result.get("failures", []), key=lambda f: weakest.index(f["cat"]))[:n_fail]
    parts = [INSTRUCTIONS,
             f"\nCurrent scores (percent correct per category): {json.dumps(cats)}; total {result['total']}.",
             "\nCurrent policy file:\n```python\n" + source.strip() + "\n```"]
    if fails:
        lines = []
        for f in fails:
            lines.append(f"- [{f['cat']}/{f['kind']}] question: {f['q']}\n  expected: {f['expected']}  "
                         f"got: {f['got']!r}\n  last steps: " + " || ".join(f["trace"][-3:])[:500])
        parts.append("\nFailures (weakest categories first):\n" + "\n".join(lines))
    if refused:
        parts.append("\nRecent attempts the judge refused (do not repeat them):\n" +
                     "\n".join(f"- {r['change']}: {r['why']}" for r in refused[-5:]))
    return "\n".join(parts)


def ask(prompt, seed, temperature=0.7, max_tokens=1800, timeout=900):
    r = requests.post(f"{URL}/chat/completions", timeout=timeout, json={
        "model": MODEL, "messages": [{"role": "user", "content": prompt}],
        "max_tokens": max_tokens, "temperature": temperature, "seed": seed})
    if r.status_code != 200:
        raise RuntimeError(f"proposer {r.status_code}: {r.text[:300]}")
    return r.json()["choices"][0]["message"]["content"]


_BLOCK = re.compile(r"```(?:python|py)?\s*\n(.*?)```", re.S)


def extract(reply):
    """Returns (source, change) or (None, why)."""
    blocks = _BLOCK.findall(reply)
    if not blocks:
        return None, "no python code block in the reply"
    src = max(blocks, key=len).strip() + "\n"
    m = re.match(r"\s*#\s*CHANGE:\s*(.+)", src)
    return src, (m.group(1).strip()[:160] if m else "(no CHANGE line)")
