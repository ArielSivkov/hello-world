"""Asks a model to rewrite the genome. By default that model is the agent's own model (true self-rewriting);
point REWRITE_PROPOSER_URL / REWRITE_PROPOSER_MODEL at any OpenAI-compatible server to use another one.

Two reply formats (rewrite.loop --format): "full", the complete new file in one code block, and "edits",
only the change (SET lines, SYSTEM_EXTRA, new functions, SEARCH/REPLACE), which rewrite/edits.py applies
to the champion. Both end as a complete candidate file judged by the same sandbox and gate.

The proposer sees: the current genome (or, in diverse mode, an archive parent), its feedback-half dev scores,
feedback-half failures (weakest category first, or in diverse mode the rotating focus category), and the
recent attempts the gate refused. It never sees the gate half, holdout tasks or expected answers.
"""
import json
import os
import re

import requests

from rewrite import edits

URL = os.environ.get("REWRITE_PROPOSER_URL", os.environ.get("ION_BASE_URL", "http://localhost:8080/v1"))
MODEL = os.environ.get("REWRITE_PROPOSER_MODEL", os.environ.get("ION_MODEL", "local"))


def proposers():
    """REWRITE_PROPOSERS="qwen=http://localhost:8080/v1,llama=http://localhost:8081/v1" → [(name, url)].
    Generation g uses proposer g % n, so different model families take turns rewriting the same genome.
    Unset → one proposer: the agent's own model."""
    spec = os.environ.get("REWRITE_PROPOSERS", "").strip()
    if not spec:
        return [("self", URL)]
    out = []
    for part in spec.split(","):
        name, _, url = part.strip().partition("=")
        out.append((name.strip(), url.strip()))
    return out

INSTRUCTIONS = """You are improving the policy file of a small Hebrew question-answering agent.
The agent is a fixed program; this policy file is the only part you may change. An automatic judge
scores every version on a test set and keeps your version only if the total score rises and no
category drops by more than 10 points.

What the policy file controls:
- CONFIG: switches of the agent (keep the same keys; you may change values).
- SYSTEM_EXTRA: text appended to the agent's system prompt.
- prepare(question, doc): returns the question text the agent will see (doc is a long document or None).
- finalize(question, answer): returns the final answer that the judge checks. The judge expects ONE
  short answer: a hedge, a list of guesses or a long answer is marked wrong.

Rules: allowed imports are re, math, json, unicodedata, string, collections, itertools, functools.
No while loops, no lambdas, no classes, no print, no names starting with "_". Keep both functions.

Make ONE focused change that should fix some of the failures shown, without breaking other categories.
Reply with the complete new file in a single ```python code block. Its first line must be a comment:
# CHANGE: <one short sentence describing your change>"""

# Edit format: a short prompt for a small model. It never asks for the whole file, the CONFIG is packed
# onto a few lines, and one concrete reply shows the format. The harness turns the reply into a file.
INSTRUCTIONS_EDITS = """You improve the policy of a small Hebrew question-answering agent. An automatic judge
scores every version and keeps yours only if the total score rises and no category drops by more than 10.

The policy has four parts. CONFIG holds the agent's switches. SYSTEM_EXTRA is text added to the agent's
system prompt. prepare(question, doc) returns the question text the agent sees. finalize(question, answer)
returns the final answer; the judge expects ONE short answer (hedges and lists of guesses are wrong).

Do NOT write the whole file. Write only your change:
line 1:  CHANGE: <one short sentence>
then one or more of these:
  SET <config key> = <new value>        (one line per switch)
  SYSTEM_EXTRA = "<text in English or Hebrew>"
  a ```python block with a complete new def prepare(question, doc) or def finalize(question, answer)
Python rules: imports only from re, math, json, unicodedata, string, collections, itertools, functools.
No while, no lambda, no class, no print, no names starting with _.

Example of a reply in the right format (write your own change, not this one):
CHANGE: cut the answer at the first newline
```python
def finalize(question, answer):
    return answer.strip().split("\\n")[0]
```

Make ONE small change that should fix some of the failures below without breaking other categories."""


def _clean(s, n):
    s = "".join(ch for ch in str(s) if ch.isprintable() or ch == " ")
    return s[:n]


def build_prompt(source, result, refused, n_fail=None, fmt="full", kind=None, focus=None):
    if kind is not None:     # diverse mode (edit format only)
        return build_diverse_prompt(source, result, refused, kind, focus, n_fail if n_fail is not None else 4)
    edit = fmt == "edits"
    n_fail = n_fail if n_fail is not None else (4 if edit else 6)
    trace_chars = 300 if edit else 500
    cats = result.get("feedback_cats", result["cats"])   # the gate half is never described to the proposer
    weakest = sorted(cats, key=lambda c: cats[c])
    fails = sorted(result.get("failures", []), key=lambda f: weakest.index(f["cat"]))[:n_fail]
    shown = edits.compact(source) if edit else source
    parts = [INSTRUCTIONS_EDITS if edit else INSTRUCTIONS,
             f"\nCurrent scores (percent correct per category): {json.dumps(cats)}.",
             "\nCurrent policy:\n```python\n" + shown.strip() + "\n```" if edit else
             "\nCurrent policy file:\n```python\n" + source.strip() + "\n```"]
    if fails:
        lines = []
        for f in fails:
            # the expected answer is never shown: a proposer that sees it can memorise the test set
            lines.append(f"- [{f['cat']}/{f['kind']}] question: {f['q']}\n  the agent answered (wrong): "
                         f"{_clean(f['got'], 150)!r}\n  last steps: " + _clean(" || ".join(f["trace"][-3:]), trace_chars))
        parts.append("\nFailures (weakest categories first):\n" + "\n".join(lines))
    if refused:
        parts.append("\nRecent attempts the judge refused (do not repeat them):\n" +
                     "\n".join(f"- {_clean(r['change'], 160)}: {_clean(r['why'], 200)}" for r in refused[-5:]))
    return "\n".join(parts)


# Diverse mode (rewrite.loop --diverse, upgrade 1): each generation asks for ONE kind of change, with a
# one-line example of a valid reply of that kind. Run 3 (7B) never tried a CONFIG switch or prepare().
INSTRUCTIONS_DIVERSE = """You improve the policy of a small Hebrew question-answering agent. An automatic judge
scores every version and keeps yours only if the total score rises and no category drops by more than 10.

The policy has four parts. CONFIG holds the agent's switches. SYSTEM_EXTRA is text added to the agent's
system prompt. prepare(question, doc) returns the question text the agent sees. finalize(question, answer)
returns the final answer; the judge expects ONE short answer (hedges and lists of guesses are wrong).

Do NOT write the whole file. Line 1 of your reply: CHANGE: <one short sentence>
Python rules: imports only from re, math, json, unicodedata, string, collections, itertools, functools.
No while, no lambda, no class, no print, no names starting with _."""

KIND_TEXT = {
    "config": ("change ONE CONFIG switch. Write one line: SET <key> = <value>. Do not change anything else.",
               'CHANGE: retrieve more passages\nSET rag_k = 4'),
    "system_extra": ("set SYSTEM_EXTRA to ONE sentence (English or Hebrew) for the agent's system prompt. "
                     "Write one line: SYSTEM_EXTRA = \"<sentence>\". Do not change anything else.",
                     'CHANGE: ask for the bare answer\nSYSTEM_EXTRA = "Give only the answer itself, not a full sentence."'),
    "prepare": ("write a new body of prepare(question, doc): it returns the question text the agent sees. "
                "Send one ```python block with def prepare(question, doc) (small helper functions are allowed). "
                "Do not change CONFIG, SYSTEM_EXTRA or finalize.",
                'CHANGE: collapse repeated spaces in the question\n```python\ndef prepare(question, doc):\n'
                '    return " ".join(question.split())\n```'),
    "finalize": ("write a new body of finalize(question, answer): it returns the final answer the judge checks. "
                 "Send one ```python block with def finalize(question, answer) (small helper functions are "
                 "allowed). Do not change CONFIG, SYSTEM_EXTRA or prepare.",
                 'CHANGE: drop a final period\n```python\ndef finalize(question, answer):\n'
                 '    return answer.strip().rstrip(".")\n```'),
}


def config_menu(source):
    """Every CONFIG switch the genome may set, with its valid values (from sandbox.py) and its current value."""
    from rewrite import sandbox
    try:
        types = edits.config_types()
    except Exception:     # noqa: BLE001
        types = {}
    try:
        from rewrite import diverse
        cur = diverse.parts(source)["config"]
    except Exception:     # noqa: BLE001
        cur = {}
    lines = []
    for key in list(cur) + [k for k in types if k not in cur]:
        if key == "temperature":
            continue      # locked to 0 by the sandbox
        now = cur.get(key)
        if key == "tools":
            valid = f"a list drawn from {sorted(sandbox.ALLOWED_TOOLS)}"
        elif key in sandbox.CHOICES:
            valid = "one of " + ", ".join(repr(c) for c in sorted(sandbox.CHOICES[key]))
        elif key in sandbox.RANGES:
            lo, hi = sandbox.RANGES[key]
            valid = f"a whole number {lo}..{hi}"
        elif types.get(key) is bool or isinstance(now, bool):
            valid = "True or False"
        else:
            continue
        lines.append(f"  {key}: {valid}" + (f" (now {edits._py(now)})" if key in cur else ""))
    return "\n".join(lines)


def build_diverse_prompt(source, result, refused, kind, focus=None, n_fail=4, trace_chars=300):
    """The prompt of one diverse generation: the kind of change asked for, an example reply of that kind, and
    failures from the focus category of the FEEDBACK half (never the gate half, never an expected answer)."""
    what, example = KIND_TEXT[kind]
    cats = result.get("feedback_cats", result["cats"])   # the gate half is never described to the proposer
    fails = list(result.get("failures", []))
    if focus is not None:
        picked = [f for f in fails if f["cat"] == focus]
    else:
        weakest = sorted(cats, key=lambda c: cats[c])
        picked = sorted(fails, key=lambda f: weakest.index(f["cat"]) if f["cat"] in weakest else 99)
    parts = [INSTRUCTIONS_DIVERSE,
             f"\nTHIS TIME the kind of change is: {kind}. Your task: {what}",
             "\nExample of a valid reply of this kind (write your own change, not this one):\n" + example]
    if kind == "config":
        parts.append("\nThe switches and their valid values:\n" + config_menu(source))
    parts += [f"\nCurrent scores (percent correct per category): {json.dumps(cats)}.",
              "\nCurrent policy:\n```python\n" + edits.compact(source).strip() + "\n```"]
    if picked:
        lines = []
        for f in picked[:n_fail]:
            # the expected answer is never shown: a proposer that sees it can memorise the test set
            lines.append(f"- [{f['cat']}/{f['kind']}] question: {f['q']}\n  the agent answered (wrong): "
                         f"{_clean(f['got'], 150)!r}\n  last steps: " + _clean(" || ".join(f["trace"][-3:]), trace_chars))
        head = f"Failures in category {focus} (this generation's focus)" if focus else "Failures"
        parts.append(f"\n{head}:\n" + "\n".join(lines))
    if refused:
        parts.append("\nRecent attempts the judge refused (do not repeat them):\n" +
                     "\n".join(f"- {_clean(r['change'], 160)}: {_clean(r['why'], 200)}" for r in refused[-5:]))
    parts.append(f"\nMake ONE {kind} change that should fix some of these failures without breaking other categories.")
    return "\n".join(parts)


def ask(prompt, seed, temperature=0.7, max_tokens=1800, timeout=900, url=None):
    r = requests.post(f"{url or URL}/chat/completions", timeout=timeout, json={
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
    m = re.match(r"\s*#\s*CHANGE:\s*(.+)", src) or re.search(r"^\s*#?\s*CHANGE:\s*(.+)$", reply, re.M)
    return src, (m.group(1).strip()[:160] if m else "(no CHANGE line)")


def scrub(text):
    """Model replies may hold lone surrogates or Unicode line separators (red team r2: U+2028 poisoned the
    champion; a surrogate crashed the attempt log)."""
    text = (text or "").encode("utf-8", "replace").decode("utf-8")
    return text.replace("\r\n", "\n").replace("\u2028", "\n").replace("\u2029", "\n").replace("\x85", "\n")


def parse(reply, champion, fmt="full"):
    """Returns (source, change, why): source is the complete candidate file, or None with `why` set.
    Never raises: a reply that breaks the parser is a refused reply, not a crashed loop."""
    try:
        return _parse(scrub(reply), champion, fmt)
    except Exception as e:     # noqa: BLE001
        return None, "(unparseable)", f"edit: the reply could not be parsed ({type(e).__name__})"


def _parse(reply, champion, fmt):
    if fmt == "full":
        src, change = extract(reply)
        return (src, change, None) if src is not None else (None, "(unparseable)", change)
    try:
        src, change = edits.apply_reply(champion, reply)
    except edits.EditError as e:
        m = edits._CHANGE.search(reply or "")
        return None, (m.group(1).strip()[:160] if m else "(unparseable)"), f"edit: {e}"
    if src.strip() == champion.strip():
        return None, change, ("edit: the reply changes nothing (the values are already set, or the file was "
                              "copied back); send only the lines that change")
    return src, change, None


def retry_prompt(prompt, why):
    """The same prompt with the parse error of the previous reply, for one more try."""
    return (prompt + f"\n\nYour previous reply could not be used: {why}\n"
            "Reply again, following the format exactly.")
