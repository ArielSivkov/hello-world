"""The gate: measures a genome in a separate process and decides whether it replaces the champion.

The judge is out of the genome's reach by construction (sandbox.py), and the fingerprint of every
file the judge depends on is checked before each decision, so a change to the judge stops the run.
"""
import hashlib
import json
import os
import subprocess
import sys
import tempfile

LAB = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
PROTECTED = [
    "ion-loop/arena/check.py", "ion-loop/arena/run.py", "ion-loop/arena/dev.jsonl",
    "ion-loop/arena/holdout.jsonl", "ion-loop/ion/agent.py", "ion-loop/ion/tools.py", "ion-loop/ion/llm.py",
    "rewrite/gate.py", "rewrite/sandbox.py", "rewrite/evaluate.py",
]


class JudgeChanged(Exception):
    pass


def fingerprint():
    out = {}
    for rel in PROTECTED:
        with open(os.path.join(LAB, rel), "rb") as f:
            out[rel] = hashlib.sha256(f.read()).hexdigest()
    return out


def verify(expected):
    now = fingerprint()
    changed = [k for k in expected if now.get(k) != expected[k]]
    if changed:
        raise JudgeChanged(f"judge files changed during the run: {changed}")


def score(source, split="dev", timeout=3600, log=None):
    """Run rewrite.evaluate in a child process. Returns the result dict, or {"error": ...}."""
    with tempfile.NamedTemporaryFile("w", suffix=".py", delete=False, encoding="utf-8") as f:
        f.write(source)
        path = f.name
    try:
        p = subprocess.run([sys.executable, "-m", "rewrite.evaluate", "--genome", path, "--split", split],
                           cwd=LAB, capture_output=True, text=True, timeout=timeout)
    except subprocess.TimeoutExpired:
        return {"error": f"timeout after {timeout}s"}
    finally:
        os.unlink(path)
    if log:
        log.write(p.stdout + p.stderr)
        log.flush()
    for line in reversed(p.stdout.splitlines()):
        if line.startswith("RESULT "):
            return json.loads(line[7:])
    tail = (p.stderr or p.stdout).strip().splitlines()[-3:]
    return {"error": "evaluation failed: " + " | ".join(tail)[:400]}


def decide(cur, new, tolerance=10):
    """Same rule as ion-loop: the total must rise and no category may drop by more than `tolerance`."""
    if "error" in new:
        return False, {}
    regress = {c: (cur["cats"][c], new["cats"].get(c, 0)) for c in cur["cats"]
               if new["cats"].get(c, 0) < cur["cats"][c] - tolerance}
    return new["total"] > cur["total"] and not regress, regress
