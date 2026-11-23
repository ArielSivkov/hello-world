"""Diverse proposal search (upgrade 1): mutation-kind rotation, focus rotation, an archive of parents, and
a memory of code already tried.

Run 3 (Qwen 7B) wrote 6 of 6 honest proposals as "simplify basic answers": the prompt always pointed at the
weakest category and never asked for anything but a free change. The literature (Darwin Goedel Machine,
FunSearch, ShinkaEvolve) keeps an archive of variants and asks for different kinds of change. Here:

  - each generation asks for ONE kind of change, cycling KINDS (config, system_extra, prepare, finalize);
  - the failures shown rotate over the feedback-half categories that have failures (not only the weakest);
  - the parent the proposer edits is drawn from an archive of evaluated genomes, DGM style:
    P(parent) ~ sigmoid(score) * 1 / (1 + children);
  - a candidate whose normalized AST was already tried is not evaluated again.

Nothing here decides acceptance. The candidate is still judged against the current champion by the
unchanged gate (gate.decide). Archive admission uses only the seed's floor (no category more than
`tolerance` below the seed) and the blind check; parent scores are the FEEDBACK half, which the proposer
already sees, so parent selection is not an oracle for the gate half.
"""
import ast
import hashlib
import json
import math
import os
import random

KINDS = ("config", "system_extra", "prepare", "finalize")
ALLOWED_PARTS = {"config": {"config"}, "system_extra": {"system_extra"},
                 "prepare": {"prepare", "helpers"}, "finalize": {"finalize", "helpers"}}


def kind_for(gen):
    """Generation 1 asks for a config change, 2 for SYSTEM_EXTRA, 3 for prepare, 4 for finalize, 5 config..."""
    return KINDS[(gen - 1) % len(KINDS)]


def focus_for(gen, result):
    """The feedback-half category whose failures are shown in this generation. Rotates over the categories
    that have feedback failures, weakest first; None when there are no failures."""
    fails = result.get("failures") or []
    cats = result.get("feedback_cats") or result.get("cats") or {}
    with_fail = sorted({f["cat"] for f in fails}, key=lambda c: (cats.get(c, 0), c))
    if not with_fail:
        return None
    return with_fail[(gen - 1) % len(with_fail)]


# ----------------------------------------------------------------------------------------- parts of a genome

def _strip_docstrings(tree):
    for node in ast.walk(tree):
        if isinstance(node, (ast.Module, ast.FunctionDef)) and node.body and isinstance(node.body[0], ast.Expr) \
                and isinstance(node.body[0].value, ast.Constant) and isinstance(node.body[0].value.value, str):
            node.body = node.body[1:] or [ast.Pass()]
    return tree


def parts(source):
    """source -> {"config": dict, "system_extra": str, "prepare": dump, "finalize": dump, "helpers": dump}."""
    tree = _strip_docstrings(ast.parse(source))
    out = {"config": {}, "system_extra": "", "prepare": None, "finalize": None}
    helpers = []
    for node in tree.body:
        if isinstance(node, ast.Assign) and len(node.targets) == 1 and isinstance(node.targets[0], ast.Name) \
                and node.targets[0].id in ("CONFIG", "SYSTEM_EXTRA"):
            try:
                val = ast.literal_eval(node.value)
            except ValueError:
                val = ast.dump(node.value)
            out["config" if node.targets[0].id == "CONFIG" else "system_extra"] = val
        elif isinstance(node, ast.FunctionDef) and node.name in ("prepare", "finalize"):
            out[node.name] = ast.dump(node)
        else:
            helpers.append(ast.dump(node))
    out["helpers"] = sorted(helpers)
    return out


def changed_parts(parent, candidate):
    a, b = parts(parent), parts(candidate)
    return {k for k in a if a[k] != b[k]}


def check_kind(parent, candidate, kind):
    """None if the candidate changes only what `kind` allows, else a reason starting with 'edit:' (the loop
    treats it as a parse error, shown back to the proposer for one more try)."""
    try:
        changed = changed_parts(parent, candidate)
    except (SyntaxError, ValueError, RecursionError, MemoryError):
        return None      # the sandbox will give the real reason
    extra = sorted(changed - ALLOWED_PARTS[kind])
    if extra:
        return (f"edit: this generation asks for a {kind} change only, but the reply also changes "
                f"{', '.join(extra)}; send only the {kind} change")
    if kind == "config":
        try:
            from rewrite import sandbox
            sandbox.validate_config(parts(candidate)["config"])
        except ImportError:
            pass
        except Exception as e:     # noqa: BLE001  sandbox.Refused: a value out of the allowed range
            return f"edit: {e}"
    return None


# ----------------------------------------------------------------------------------------- duplicates

def ast_key(source):
    """Normalized AST: comments, formatting, quotes and docstrings do not count."""
    try:
        tree = _strip_docstrings(ast.parse(source))
    except (SyntaxError, ValueError, RecursionError, MemoryError):
        return hashlib.sha1(source.strip().encode("utf-8", "replace")).hexdigest()
    return hashlib.sha1(ast.dump(tree).encode()).hexdigest()


class Seen:
    """AST keys of every genome already evaluated (or refused by the sandbox), persisted as a JSON list."""

    def __init__(self, path):
        self.path = path
        self.keys = set()
        if path and os.path.exists(path):
            try:
                self.keys = set(json.load(open(path, encoding="utf-8")))
            except (OSError, ValueError):
                self.keys = set()

    def __contains__(self, source):
        return ast_key(source) in self.keys

    def add(self, source):
        k = ast_key(source)
        if k not in self.keys:
            self.keys.add(k)
            if self.path:
                _write_json(self.path, sorted(self.keys))


# ----------------------------------------------------------------------------------------- archive

def _write_json(path, data):
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False)
    os.replace(tmp, path)


def feedback_score(result):
    """Mean percent of the FEEDBACK half (what the proposer already sees); cats only if that is missing."""
    cats = result.get("feedback_cats") or result.get("cats") or {}
    return round(sum(cats.values()) / len(cats), 1) if cats else 0.0


def above_seed_floor(result, seed, tolerance=10, blind_max=1):
    """The archive's admission rule: like gate.decide's floor against the seed, nothing more. It never
    decides acceptance (gate.decide against the champion does)."""
    try:
        if not result or "error" in result or set(result["cats"]) != set(seed["cats"]):
            return False
        if any(result["cats"][c] < seed["cats"][c] - tolerance for c in seed["cats"]):
            return False
        return result.get("blind_correct", 0) <= max(seed.get("blind_correct", 0), blind_max)
    except Exception:     # noqa: BLE001
        return False


class Archive:
    """Up to `size` evaluated genomes. Each entry: id, gen, source, result, score, children.
    The seed and the current champion are never evicted."""

    def __init__(self, path, size=8, tolerance=10, lam=10.0):
        self.path, self.size, self.tolerance, self.lam = path, max(1, size), tolerance, lam
        self.entries, self.champion_id, self.seed_id = [], None, None
        if path and os.path.exists(path):
            data = json.load(open(path, encoding="utf-8"))
            self.entries = data.get("entries", [])
            self.champion_id, self.seed_id = data.get("champion"), data.get("seed")

    def save(self):
        if self.path:
            _write_json(self.path, {"entries": self.entries, "champion": self.champion_id, "seed": self.seed_id})

    def ids(self):
        return [e["id"] for e in self.entries]

    def get(self, gid):
        return next((e for e in self.entries if e["id"] == gid), None)

    def _put(self, source, result, gen):
        gid = ast_key(source)[:12]
        if self.get(gid) is None:
            self.entries.append({"id": gid, "gen": gen, "source": source, "result": result,
                                 "score": feedback_score(result), "children": 0})
        return gid

    def set_seed(self, source, result):
        self.seed_id = self._put(source, result, 0)
        self.save()

    def set_champion(self, source, result, gen=0):
        self.champion_id = self._put(source, result, gen)
        self._evict()
        self.save()

    def consider(self, source, result, seed, gen):
        """Add an evaluated candidate if it is above the seed's floor. Returns True if it is in the archive."""
        if not above_seed_floor(result, seed, self.tolerance):
            return False
        gid = self._put(source, result, gen)
        self._evict()
        self.save()
        return self.get(gid) is not None

    def _evict(self):
        keep = {self.seed_id, self.champion_id}
        while len(self.entries) > self.size:
            loose = [e for e in self.entries if e["id"] not in keep]
            if not loose:
                break
            worst = min(loose, key=lambda e: (e["score"], -e["gen"]))
            self.entries.remove(worst)

    def weights(self):
        if not self.entries:
            return []
        scores = sorted(e["score"] for e in self.entries)
        mid = scores[len(scores) // 2]
        return [1 / (1 + math.exp(-self.lam * (e["score"] - mid) / 100)) / (1 + e["children"])
                for e in self.entries]

    def select(self, gen):
        """DGM parent selection, seeded by the generation so a resumed run draws the same parent."""
        rng = random.Random(1000003 * gen + 17)
        e = rng.choices(self.entries, weights=self.weights(), k=1)[0]
        e["children"] += 1
        self.save()
        return e
