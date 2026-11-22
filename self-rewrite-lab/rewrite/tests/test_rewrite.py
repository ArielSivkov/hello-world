"""Offline tests for the self-rewriting gate: no model and no search index needed."""
import os
import sys

import pytest

LAB = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path[:0] = [os.path.join(LAB, "ion-loop"), LAB]

from rewrite import evaluate, gate, proposer, sandbox   # noqa: E402

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


def test_restricted_builtins_at_runtime():
    # format strings cannot be caught statically; the reduced builtins table still has no I/O
    mod = sandbox.load(mutate("def finalize(question, answer):\n    return answer",
                              "def finalize(question, answer):\n    return str(len(answer))"))
    assert "open" not in mod.__dict__["__builtins__"]
    assert mod.finalize("q", "abc") == "3"


def test_hooks_are_applied_and_a_crash_fails_only_that_task(monkeypatch):
    seen = {}

    def fake_run(q, cfg, doc=None):
        seen["q"] = q
        return "  התשובה: 1879.  ", [("model", "ANSWER: 1879")]

    monkeypatch.setattr(evaluate.agent, "run", fake_run)
    mod = sandbox.load(mutate(
        "def prepare(question, doc):\n    return question\n\n\ndef finalize(question, answer):\n    return answer",
        "def prepare(question, doc):\n    return question + ' ענה בשנה בלבד.'\n\n\n"
        "def finalize(question, answer):\n    if 'קרוס' in question:\n        return [][1]\n"
        "    return answer.strip()"))
    ans, trace = evaluate.solve(mod, None, {"q": "באיזו שנה?"})
    assert seen["q"].endswith("ענה בשנה בלבד.") and ans == "התשובה: 1879."
    assert trace[0][0] == "prepared" and trace[-1][0] == "finalized"
    ans, trace = evaluate.solve(mod, None, {"q": "קרוס"})
    assert ans == "" and "finalize crashed" in trace[-1][1]


def test_decide_rule():
    cur = {"total": 50.0, "cats": {"a": 50, "b": 50}}
    assert gate.decide(cur, {"total": 55.0, "cats": {"a": 70, "b": 40}})[0]        # -10 is tolerated
    keep, reg = gate.decide(cur, {"total": 60.0, "cats": {"a": 90, "b": 30}})
    assert not keep and reg == {"b": (50, 30)}
    assert not gate.decide(cur, {"total": 50.0, "cats": {"a": 50, "b": 50}})[0]    # must strictly rise
    assert not gate.decide(cur, {"error": "timeout"})[0]


def test_judge_fingerprint_detects_change(tmp_path, monkeypatch):
    f = tmp_path / "judge.py"
    f.write_text("x = 1")
    monkeypatch.setattr(gate, "LAB", str(tmp_path))
    monkeypatch.setattr(gate, "PROTECTED", ["judge.py"])
    fp = gate.fingerprint()
    gate.verify(fp)
    f.write_text("x = 2")
    with pytest.raises(gate.JudgeChanged):
        gate.verify(fp)


def test_extract_and_prompt():
    src, change = proposer.extract("text\n```python\n# CHANGE: strip dots\nCONFIG = {}\n```\nmore")
    assert change == "strip dots" and src.startswith("# CHANGE")
    assert proposer.extract("no code")[0] is None
    result = {"total": 50.0, "cats": {"basic": 20, "calc": 80},
              "failures": [{"id": "x", "cat": "calc", "kind": "calc", "q": "Q1", "expected": ["1"], "got": "2",
                            "trace": ["model: hi"]},
                           {"id": "y", "cat": "basic", "kind": "basic", "q": "Q2", "expected": ["b"], "got": "c",
                            "trace": []}]}
    p = proposer.build_prompt(SEED, result, [{"change": "c1", "why": "regression"}])
    assert p.index("Q2") < p.index("Q1")          # weakest category first
    assert "holdout" not in p.lower() and "c1: regression" in p


def test_timeout_kills_a_hanging_genome(monkeypatch):
    # a bounded-looking for loop that never ends in practice: the child process is killed
    hang = mutate("def prepare(question, doc):\n    return question",
                  "def prepare(question, doc):\n    n = 0\n    for i in range(10 ** 15):\n        n += i\n"
                  "    return question")
    res = gate.score(hang, "dev", timeout=3)
    assert "timeout" in res["error"]
