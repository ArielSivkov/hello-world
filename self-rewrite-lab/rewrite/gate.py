"""The gate: measures a genome in a separate judge process and decides whether it replaces the champion.

The judge process (rewrite/evaluate.py) never executes genome code; hooks run in an isolated worker.
Hardened after swarm/2026-11-23 (red team + black agent):
  - the result comes back through a private file, never stdout, and is schema-checked here;
  - the fingerprint covers every Python file the judge or the loop runs, the arena data and the index;
  - the judge child runs in its own session and is killed as a group on timeout;
  - no ratchet: no category may fall more than `tolerance` below the champion OR the seed;
  - the gate half must rise by itself, and all of dev by a margin, with no loss on the feedback half;
  - at most one task that passed may break (no trading categories against each other);
  - the policy may not answer by itself: finalize(question, <decoy>) must not be right on more than one task;
  - dev decisions are made on the gate half only; the proposer sees failures of the feedback half;
  - decide() never raises.
"""
import glob
import hashlib
import json
import os
import shutil
import signal
import subprocess
import sys
import tempfile

LAB = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
PATTERNS = ["ion-loop/ion/*.py", "ion-loop/arena/*.py", "ion-loop/arena/*.jsonl", "ion-loop/arena/*.json",
            "ion-loop/arena/v1/*", "rewrite/*.py", "rewrite/genome/seed.py"]
BIG = ["ion-loop/data/hewiki.db"]
_big_cache = {}


class JudgeChanged(Exception):
    pass


def protected():
    files = set()
    for pat in PATTERNS:
        files.update(os.path.relpath(p, LAB) for p in glob.glob(os.path.join(LAB, pat)))
    return sorted(files)


def _sha(path):
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for block in iter(lambda: f.read(1 << 20), b""):
            h.update(block)
    return h.hexdigest()


def fingerprint():
    out = {rel: _sha(os.path.join(LAB, rel)) for rel in protected()}
    for rel in BIG:
        p = os.path.join(LAB, rel)
        if os.path.exists(p):
            st = os.stat(p)
            key = (p, st.st_size, st.st_mtime_ns)
            if key not in _big_cache:
                _big_cache[key] = _sha(p)
            out[rel] = _big_cache[key]
    return out


def verify(expected):
    now = fingerprint()
    changed = sorted(k for k in set(expected) | set(now) if now.get(k) != expected.get(k))
    if changed:
        raise JudgeChanged(f"judge files changed during the run: {changed[:10]}")


def _valid(res, split, source):
    from rewrite.evaluate import genome_id
    if not isinstance(res, dict):
        return "malformed result"
    if "refused" in res:
        return str(res["refused"])[:300]
    cats = res.get("cats")
    if res.get("split") != split or res.get("genome") != genome_id(source):
        return "result does not match the request"
    if not isinstance(cats, dict) or not cats or not all(
            isinstance(v, int) and not isinstance(v, bool) and 0 <= v <= 100 for v in cats.values()):
        return "malformed result"
    if not isinstance(res.get("n_correct"), int) or not isinstance(res.get("n_tasks"), int) or \
            not isinstance(res.get("passed"), list):
        return "malformed result"
    return None


def score(source, split="dev", timeout=3600, log=None):
    """Judge one genome in a child process. Returns the result dict, or {"error": <fixed short reason>}."""
    priv = tempfile.mkdtemp(prefix="gate-")
    os.chmod(priv, 0o700)
    gpath, opath = os.path.join(priv, "genome.py"), os.path.join(priv, "result.json")
    with open(gpath, "w", encoding="utf-8") as f:
        f.write(source)
    p = subprocess.Popen([sys.executable, "-m", "rewrite.evaluate", "--genome", gpath, "--split", split,
                          "--out", opath, "--quiet"], cwd=LAB, stdout=subprocess.PIPE,
                         stderr=subprocess.STDOUT, start_new_session=True)
    try:
        out, _ = p.communicate(timeout=timeout)
    except subprocess.TimeoutExpired:
        os.killpg(p.pid, signal.SIGKILL)
        p.wait()
        shutil.rmtree(priv, ignore_errors=True)
        return {"error": f"timeout after {timeout}s"}
    if log:
        log.write(out.decode(errors="replace")[-20000:])
        log.flush()
    try:
        res = json.load(open(opath, encoding="utf-8"))
    except (OSError, ValueError):
        res = None
    finally:
        shutil.rmtree(priv, ignore_errors=True)
    if res is None:
        return {"error": f"the judge failed (exit {p.returncode})"}   # no free text: it could carry test data
    bad = _valid(res, split, source)
    if bad:
        return {"error": bad}
    res["total"] = round(sum(res["cats"].values()) / len(res["cats"]), 1)   # recomputed, never trusted
    return res


def decide(cur, new, seed=None, tolerance=10, margin=2, max_broken=1, blind_max=1):
    """Returns (keep, regressions, reason). Never raises."""
    try:
        if "error" in new:
            return False, {}, new["error"]
        if set(new["cats"]) != set(cur["cats"]):
            return False, {}, "categories differ"
        floor = {c: cur["cats"][c] - tolerance for c in cur["cats"]}
        if seed:
            floor = {c: max(floor[c], seed["cats"][c] - tolerance) for c in floor}
        regress = {c: (cur["cats"][c], new["cats"][c]) for c in floor if new["cats"][c] < floor[c]}
        if regress:
            return False, regress, f"regression {regress}"
        if new.get("blind_correct", 0) > max(cur.get("blind_correct", 0), blind_max):
            return False, {}, (f"the policy answers {new['blind_correct']} tasks without the model "
                               f"(finalize given a decoy answer); at most {blind_max} allowed")
        broken = sorted(set(cur.get("passed", [])) - set(new.get("passed", [])))
        if len(broken) > max_broken:     # no trading: a win may not be paid for by breaking working tasks
            return False, {}, f"{len(broken)} tasks that passed now fail (at most {max_broken} allowed)"
        gain = new["n_correct"] - cur["n_correct"]                   # gate half: never shown to the proposer
        fb = new.get("feedback_correct", 0) - cur.get("feedback_correct", 0)
        # The gate half must rise by itself (memorising the shown feedback questions cannot do that), and the
        # rise over all of dev must reach the margin, with no loss on the feedback half.
        if new["total"] <= cur["total"] or gain < 1 or fb < 0 or gain + fb < margin:
            return False, {}, (f"total {cur['total']} -> {new['total']}, gate half {gain:+d}, feedback half "
                               f"{fb:+d} (needs gate +1 and +{margin} overall)")
        return True, {}, "accepted"
    except Exception as e:     # noqa: BLE001
        return False, {}, f"gate error: {type(e).__name__}"
