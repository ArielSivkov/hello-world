"""Offline tests for the self-rewriting gate: no model and no search index needed."""
import os
import sys

import pytest

LAB = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path[:0] = [os.path.join(LAB, "ion-loop"), LAB]

from rewrite import evaluate, gate, proposer, sandbox   # noqa: E402
from rewrite.isolation import HookWorker              # noqa: E402

SEED = open(os.path.join(LAB, "rewrite", "genome", "seed.py"), encoding="utf-8").read()


def mutate(old, new):
    assert old in SEED
    return SEED.replace(old, new)


def test_seed_loads():
    mod = sandbox.load(SEED)
    assert mod.prepare("שאלה?", None) == "שאלה?"
    assert mod.CONFIG["extract"] == "structured"


@pytest.mark.parametrize("bad, reason", [
    ("import os\n", "import of 'os'"),
    ("from subprocess import run\n", "import from"),
    ("print('hi')\n", "module level"),     # side effect at import time
    ("def g(x):\n    return open(x)\n", "'open'"),
    ("def g(x):\n    return x.__class__\n", "'__class__'"),
    ("def g(x):\n    return eval(x)\n", "'eval'"),
    ("def g(x):\n    while True:\n        pass\n", "while"),
    ("g = lambda x: x\n", "Lambda"),
    ("def g(x):\n    return getattr(x, 'y')\n", "'getattr'"),
    ("def g(x):\n    global CONFIG\n    return x\n", "Global"),
])
def test_sandbox_refuses(bad, reason):
    with pytest.raises(sandbox.Refused, match=reason):
        sandbox.check(SEED + "\n" + bad)


def test_sandbox_contract():
    with pytest.raises(sandbox.Refused, match="missing function finalize"):
        sandbox.check(mutate("def finalize(question, answer):\n    return answer\n", ""))
    with pytest.raises(sandbox.Refused, match="unknown CONFIG keys"):
        sandbox.load(mutate('"rag_phrase": True,', '"rag_phrase": True, "judge": "me",'))
    with pytest.raises(sandbox.Refused, match="must return str"):
        sandbox.load(mutate("def prepare(question, doc):\n    return question",
                            "def prepare(question, doc):\n    return 1"))
    with pytest.raises(sandbox.Refused, match="syntax error"):
        sandbox.check("def prepare(:\n")


def test_hooks_run_in_the_isolated_worker():
    mod = sandbox.load(mutate("def finalize(question, answer):\n    return answer",
                              "def finalize(question, answer):\n    return str(len(answer))"))
    assert mod.finalize("q", "abc") == "3"
    assert not hasattr(mod, "__builtins__")          # the genome's namespace is not in this process


def test_hooks_are_applied_and_a_crash_fails_only_that_task(monkeypatch):
    seen = {}

    def fake_run(q, cfg, doc=None):
        seen["q"] = q
        return "  התשובה: 1879.  ", [("model", "ANSWER: 1879")]

    monkeypatch.setattr(evaluate.agent, "run", fake_run)
    src = mutate(
        "def prepare(question, doc):\n    return question\n\n\ndef finalize(question, answer):\n    return answer",
        "def prepare(question, doc):\n    return question + ' ענה בשנה בלבד.'\n\n\n"
        "def finalize(question, answer):\n    if 'קרוס' in question:\n        return [][1]\n"
        "    return answer.strip()")
    w = HookWorker(src)
    try:
        ans, trace = evaluate.solve(w, None, {"q": "באיזו שנה?"})
        assert seen["q"].endswith("ענה בשנה בלבד.") and ans == "התשובה: 1879."
        assert trace[0][0] == "prepared" and trace[-1][0] == "finalized"
        ans, trace = evaluate.solve(w, None, {"q": "קרוס"})
        assert ans == "" and "finalize failed: IndexError" in trace[-1][1]
        ans, _ = evaluate.solve(w, None, {"q": "שוב?"})                  # the worker lives on
        assert ans == "התשובה: 1879."
    finally:
        w.close()


def test_decide_rule():
    cur = {"total": 50.0, "cats": {"a": 50, "b": 50}, "n_correct": 40}
    keep, _, why = gate.decide(cur, {"total": 55.0, "cats": {"a": 70, "b": 40}, "n_correct": 44})
    assert keep and why == "accepted"                                              # -10 is tolerated
    keep, reg, _ = gate.decide(cur, {"total": 60.0, "cats": {"a": 90, "b": 30}, "n_correct": 48})
    assert not keep and reg == {"b": (50, 30)}
    assert not gate.decide(cur, {"total": 50.5, "cats": {"a": 51, "b": 50}, "n_correct": 41})[0]   # margin
    assert not gate.decide(cur, {"error": "timeout"})[0]
    assert not gate.decide(cur, {"total": 99, "cats": {"zz": 99}, "n_correct": 99})[0]
    assert gate.decide(cur, {"garbage": 1})[2].startswith("gate error")            # never raises
    # no ratchet: the seed's floor holds even after the champion drifted down
    seed = {"cats": {"a": 50, "b": 100}}
    drift = {"total": 70.0, "cats": {"a": 50, "b": 90}, "n_correct": 40}
    assert not gate.decide(drift, {"total": 75.0, "cats": {"a": 70, "b": 80}, "n_correct": 45}, seed)[0]


def test_judge_fingerprint_detects_change(tmp_path, monkeypatch):
    (tmp_path / "rewrite").mkdir()
    f = tmp_path / "rewrite" / "judge.py"
    f.write_text("x = 1")
    monkeypatch.setattr(gate, "LAB", str(tmp_path))
    fp = gate.fingerprint()
    gate.verify(fp)
    f.write_text("x = 2")
    with pytest.raises(gate.JudgeChanged):
        gate.verify(fp)
    f.write_text("x = 1")
    (tmp_path / "rewrite" / "__init__.py").write_text("backdoor = 1")      # a NEW file is a change too
    with pytest.raises(gate.JudgeChanged):
        gate.verify(fp)


def test_fingerprint_covers_every_file_the_judge_runs():
    covered = set(gate.protected())
    for rel in ["ion-loop/arena/__init__.py", "ion-loop/ion/__init__.py", "rewrite/__init__.py",
                "rewrite/loop.py", "rewrite/proposer.py", "rewrite/edits.py", "rewrite/check_strict.py",
                "rewrite/hookworker.py", "rewrite/isolation.py", "ion-loop/arena/holdout.jsonl"]:
        assert rel in covered, rel


def test_extract_and_prompt():
    src, change = proposer.extract("text\n```python\n# CHANGE: strip dots\nCONFIG = {}\n```\nmore")
    assert change == "strip dots" and src.startswith("# CHANGE")
    assert proposer.extract("no code")[0] is None
    result = {"total": 50.0, "cats": {"basic": 20, "calc": 80},
              "failures": [{"id": "x", "cat": "calc", "kind": "calc", "q": "Q1", "got": "2",
                            "trace": ["model: hi"]},
                           {"id": "y", "cat": "basic", "kind": "basic", "q": "Q2", "got": "c",
                            "trace": []}]}
    p = proposer.build_prompt(SEED, result, [{"change": "c1", "why": "regression"}])
    assert p.index("Q2") < p.index("Q1")          # weakest category first
    assert "holdout" not in p.lower() and "c1: regression" in p


def test_timeout_kills_a_hanging_genome():
    hang = mutate("def prepare(question, doc):\n    return question",
                  "def prepare(question, doc):\n    n = 0\n    for i in range(10 ** 15):\n        n += i\n"
                  "    return question")
    res = gate.score(hang, "dev", timeout=60)
    assert "error" in res and "timed out" in res["error"]


def test_proposer_pool(monkeypatch):
    monkeypatch.delenv("REWRITE_PROPOSERS", raising=False)
    assert proposer.proposers() == [("self", proposer.URL)]
    monkeypatch.setenv("REWRITE_PROPOSERS", "qwen=http://a:1/v1, llama=http://b:2/v1")
    assert proposer.proposers() == [("qwen", "http://a:1/v1"), ("llama", "http://b:2/v1")]
