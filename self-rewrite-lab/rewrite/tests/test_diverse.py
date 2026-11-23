"""Offline tests for upgrade 1: diverse proposals (rewrite/diverse.py, proposer diverse prompt, loop --diverse).
No model server: the proposer and the gate are stubbed, the prompt-leak test uses the recorded seed answers."""
import json
import os
import shutil
import sys

import pytest

LAB = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path[:0] = [os.path.join(LAB, "ion-loop"), LAB]

from rewrite import diverse as dv, edits, evaluate, gate, loop, proposer, sandbox   # noqa: E402
from arena.run import load as load_split      # noqa: E402

HERE = os.path.dirname(os.path.abspath(__file__))
SEED = open(os.path.join(LAB, "rewrite", "genome", "seed.py"), encoding="utf-8").read()
ANSWERS = json.load(open(os.path.join(HERE, "fixtures", "seed_dev_answers.json"), encoding="utf-8"))

RESULT = {"total": 50.0, "cats": {"basic": 20, "calc": 80, "web": 60},
          "feedback_cats": {"basic": 30, "calc": 70, "web": 50},
          "failures": [{"id": "x", "cat": "calc", "kind": "calc", "q": "QCALC", "got": "2", "trace": ["model: hi"]},
                       {"id": "y", "cat": "basic", "kind": "basic", "q": "QBASIC", "got": "c", "trace": []},
                       {"id": "z", "cat": "web", "kind": "web", "q": "QWEB", "got": "d", "trace": []}]}


# ------------------------------------------------------------------------------------- rotation

def test_kind_rotation_order():
    assert [dv.kind_for(g) for g in range(1, 10)] == ["config", "system_extra", "prepare", "finalize"] * 2 + ["config"]


def test_focus_rotates_over_feedback_categories_with_failures_weakest_first():
    assert [dv.focus_for(g, RESULT) for g in range(1, 7)] == ["basic", "web", "calc"] * 2
    assert dv.focus_for(1, {"cats": {"a": 1}, "failures": []}) is None
    one = dict(RESULT, failures=RESULT["failures"][:1])
    assert {dv.focus_for(g, one) for g in range(1, 5)} == {"calc"}


# ------------------------------------------------------------------------------------- prompt per kind

@pytest.mark.parametrize("kind", dv.KINDS)
def test_prompt_names_the_kind_and_its_example_is_a_valid_reply_of_that_kind(kind):
    p = proposer.build_prompt(SEED, RESULT, [{"change": "c1", "why": "edit: x"}], fmt="edits", kind=kind, focus="web")
    assert f"THIS TIME the kind of change is: {kind}" in p and "c1: edit: x" in p
    assert "QWEB" in p and "QBASIC" not in p and "QCALC" not in p        # only the focus category
    assert "Failures in category web" in p and "rag_k=3" in p
    assert ("valid values" in p) == (kind == "config")
    example = proposer.KIND_TEXT[kind][1]
    assert example in p
    src, change, why = proposer.parse(example, SEED, "edits")
    assert why is None and dv.check_kind(SEED, src, kind) is None
    assert dv.changed_parts(SEED, src) == {kind}
    sandbox.load(src)                                                    # passes the unchanged sandbox


def test_config_menu_lists_valid_values_from_the_sandbox():
    m = proposer.config_menu(SEED)
    assert "rag_k: a whole number 1..6 (now 3)" in m
    assert "extract: one of 'facts-only', 'llm', 'structured' (now \"structured\")" in m
    assert "tools: a list drawn from ['calc', 'doc_search', 'web_search']" in m
    assert "brief: True or False (now False)" in m and "temperature" not in m
    for key in sandbox.RANGES:
        assert f"  {key}:" in m


def test_no_focus_falls_back_to_weakest_first():
    p = proposer.build_prompt(SEED, RESULT, [], fmt="edits", kind="finalize")
    assert p.index("QBASIC") < p.index("QWEB") < p.index("QCALC")


def test_old_prompt_is_unchanged_without_a_kind():
    p = proposer.build_prompt(SEED, RESULT, [], fmt="edits")
    assert "THIS TIME" not in p and "Example of a reply in the right format" in p


@pytest.fixture
def judge(tmp_path, monkeypatch):
    monkeypatch.setattr(evaluate, "RUNS", str(tmp_path / "runs"))
    monkeypatch.setattr(evaluate.agent, "run", lambda q, cfg, doc=None: (ANSWERS.get(q, ""), [("model", "x")]))
    monkeypatch.setattr(evaluate.agent, "BASE_PROMPT", evaluate.agent.BASE_PROMPT)
    monkeypatch.setattr(evaluate.agent, "BASE_PROMPT_HE", evaluate.agent.BASE_PROMPT_HE)
    return lambda source, split="dev": evaluate.evaluate(source, split, verbose=False)


def test_diverse_prompts_never_show_the_gate_half_or_expected_answers(judge):
    res = judge(SEED)
    fb_half, gate_half = evaluate.dev_halves(load_split("dev"))
    cats = sorted(res["feedback_cats"]) + [None]
    for kind in dv.KINDS:
        for focus in cats:
            p = proposer.build_prompt(SEED, res, [], fmt="edits", kind=kind, focus=focus, n_fail=100)
            for t in gate_half:
                assert t["q"][:60] not in p and t["q"][-22:] not in p, (kind, focus, t["id"])
                for a in t["answers"]:
                    if len(a) >= 4:
                        assert a not in p, (kind, focus, t["id"], a)
            for t in fb_half:          # expected answers of the shown half are never shown either
                for a in t["answers"]:
                    if len(a) >= 4 and a not in SEED:
                        assert a not in p, (kind, focus, t["id"], a)
            assert json.dumps(res["feedback_cats"]) in p and json.dumps(res["cats"]) not in p


# ------------------------------------------------------------------------------------- kind check

@pytest.mark.parametrize("kind, reply, ok", [
    ("config", "CHANGE: a\nSET rag_k = 4", True),
    ("config", 'CHANGE: a\nSET rag_k = 4\nSYSTEM_EXTRA = "x"', False),
    ("config", "CHANGE: a\nSET rag_k = 99", False),          # out of the sandbox range: refused before the gate
    ("system_extra", 'CHANGE: a\nSYSTEM_EXTRA = "Be brief."', True),
    ("system_extra", "CHANGE: a\nSET brief = True", False),
    ("prepare", "CHANGE: a\n```python\nimport re\n\ndef norm(q):\n    return re.sub(r'\\s+', ' ', q)\n\n"
                "def prepare(question, doc):\n    return norm(question)\n```", True),
    ("prepare", "CHANGE: a\n```python\ndef finalize(question, answer):\n    return answer.strip()\n```", False),
    ("finalize", "CHANGE: a\n```python\ndef finalize(question, answer):\n    return answer.strip()\n```", True),
])
def test_wrong_kind_is_an_edit_error(kind, reply, ok):
    src, _, why = proposer.parse(reply, SEED, "edits")
    assert why is None
    bad = dv.check_kind(SEED, src, kind)
    assert (bad is None) == ok, bad
    if not ok:
        assert bad.startswith("edit:") and loop.public_why({"why": bad}) == bad


# ------------------------------------------------------------------------------------- duplicates

def test_normalized_ast_ignores_comments_formatting_and_docstrings(tmp_path):
    a = SEED.replace("return answer", "return answer.strip()")
    b = "# a comment\n" + a.replace("answer.strip()", "answer.strip( )").replace('"calc"', "'calc'")
    b = b.replace("def finalize(question, answer):\n", 'def finalize(question, answer):\n    """doc"""\n')
    assert dv.ast_key(a) == dv.ast_key(b) != dv.ast_key(SEED)
    seen = dv.Seen(str(tmp_path / "seen.json"))
    seen.add(a)
    assert b in seen and SEED not in seen
    assert b in dv.Seen(str(tmp_path / "seen.json"))          # persisted


# ------------------------------------------------------------------------------------- archive

def res(cats, fb=None, blind=0):
    return {"total": sum(cats.values()) / len(cats), "cats": cats, "feedback_cats": fb or cats,
            "n_correct": 1, "blind_correct": blind, "failures": []}


SEED_RES = res({"a": 80, "b": 60})


def variant(i):
    return SEED.replace('"rag_k": 3', f'"rag_k": {i}') if i <= 6 else SEED.replace('"notes_chars": 450', f'"notes_chars": {100 + i}')


def test_archive_admission_uses_only_the_seed_floor(tmp_path):
    ar = dv.Archive(str(tmp_path / "archive.json"), size=8, tolerance=10)
    ar.set_seed(SEED, SEED_RES)
    ar.set_champion(SEED, SEED_RES)
    assert ar.consider(variant(4), res({"a": 70, "b": 55}), SEED_RES, 1)        # worse, but above the floor
    assert not ar.consider(variant(5), res({"a": 69, "b": 90}), SEED_RES, 2)    # a below 80-10
    assert not ar.consider(variant(6), {"error": "timeout"}, SEED_RES, 3)
    assert not ar.consider(variant(2), res({"a": 90, "b": 90}, blind=3), SEED_RES, 4)   # answers by itself
    assert not ar.consider(variant(1), res({"a": 90}), SEED_RES, 5)              # categories differ
    assert len(ar.entries) == 2


def test_archive_keeps_seed_and_champion_and_evicts_the_weakest(tmp_path):
    ar = dv.Archive(str(tmp_path / "archive.json"), size=3)
    ar.set_seed(SEED, res({"a": 80, "b": 60}, fb={"a": 10, "b": 10}))
    ar.set_champion(SEED, SEED_RES)
    for i, s in ((4, 50), (5, 70), (6, 60)):
        ar.consider(variant(i), res({"a": 80, "b": 60}, fb={"a": s, "b": s}), SEED_RES, i)
    assert len(ar.entries) == 3 and ar.seed_id in ar.ids()
    assert sorted(e["score"] for e in ar.entries) == [10.0, 60.0, 70.0]


def test_parent_selection_weights_are_dgm_like(tmp_path):
    ar = dv.Archive(None, size=8)
    ar.set_seed(SEED, res({"a": 50, "b": 50}))
    ar.consider(variant(4), res({"a": 90, "b": 90}), res({"a": 50, "b": 50}), 1)
    w = ar.weights()
    assert w[1] > w[0]                                   # higher score, higher weight
    ar.entries[1]["children"] = 9
    assert ar.weights()[1] < w[1] / 5                    # many children: explored, picked less
    picks = [ar.select(g)["id"] for g in range(1, 200)]
    assert set(picks) == set(ar.ids())                   # both get picked
    assert sum(e["children"] for e in ar.entries) == 9 + 199


def test_selection_is_deterministic_and_the_archive_resumes(tmp_path):
    path = str(tmp_path / "archive.json")
    ar = dv.Archive(path, size=8)
    ar.set_seed(SEED, SEED_RES)
    for i in (2, 4, 5):
        ar.consider(variant(i), res({"a": 80, "b": 60}, fb={"a": 40 + i, "b": 50}), SEED_RES, i)
    first = ar.select(7)["id"]
    back = dv.Archive(path, size=8)
    assert back.ids() == ar.ids() and back.seed_id == ar.seed_id
    assert [e["children"] for e in back.entries] == [e["children"] for e in ar.entries]
    back.get(first)["children"] -= 1                     # undo the draw: the same generation draws the same parent
    assert back.select(7)["id"] == first


# ------------------------------------------------------------------------------------- loop end to end

def run_diverse(tmp_path, monkeypatch, replies, scores, generations=4, archive=8, retries=1, diverse=True):
    lab = tmp_path / "lab"
    if not (lab / "rewrite" / "genome" / "seed.py").exists():
        (lab / "rewrite" / "genome").mkdir(parents=True)
        shutil.copy(os.path.join(LAB, "rewrite", "genome", "seed.py"), lab / "rewrite" / "genome" / "seed.py")
    monkeypatch.setattr(loop, "LAB", str(lab))
    monkeypatch.setattr(loop, "SEED", str(lab / "rewrite" / "genome" / "seed.py"))
    monkeypatch.setattr(loop, "RUN", "test")
    prompts, scored = [], []

    def ask(prompt, seed, temperature=0.7, **kw):
        prompts.append(prompt)
        return replies.pop(0)

    fails = [{"id": "f1", "cat": "a", "kind": "a", "q": "QA", "got": "x", "trace": []},
             {"id": "f2", "cat": "b", "kind": "b", "q": "QB", "got": "y", "trace": []}]

    def score(source, split="dev", timeout=0, log=None):
        if split != "dev":
            return {"total": 0, "cats": {}}
        scored.append(source)
        for needle, r in scores:
            if needle in source:
                return dict(r, genome="g", failures=fails)
        return {"total": 50.0, "cats": {"a": 50, "b": 50}, "feedback_cats": {"a": 40, "b": 60}, "genome": "g",
                "n_correct": 50, "feedback_correct": 50, "passed": [], "failures": fails}

    monkeypatch.setattr(proposer, "ask", ask)
    monkeypatch.setattr(loop.gate, "score", score)
    monkeypatch.setattr(loop.gate, "verify", lambda fp: None)

    class A:
        tolerance, temperature, timeout, margin, format = 10, 0.7, 10, 2, "edits"
    A.generations, A.retries, A.diverse, A.archive = generations, retries, diverse, archive
    loop.main(A)
    out = lab / "rewrite" / "lineage" / "test"
    rows = [json.loads(l) for l in open(out / "history.jsonl", encoding="utf-8")]
    return out, rows, prompts, scored


def ok(total, cats, fb=None, n=50, fbn=50):
    return {"total": total, "cats": cats, "feedback_cats": fb or cats, "n_correct": n, "feedback_correct": fbn,
            "passed": []}


def test_loop_rotates_kinds_and_archives(tmp_path, monkeypatch):
    replies = [
        "CHANGE: more passages\nSET rag_k = 4",                                         # gen 1 config
        'CHANGE: wrong kind\nSET brief = True',                                         # gen 2 asks system_extra
        'CHANGE: be brief\nSYSTEM_EXTRA = "Be brief."',                                 # gen 2 retry
        "CHANGE: strip\n```python\ndef prepare(question, doc):\n    return question.strip()\n```",   # gen 3
        "CHANGE: strip\n```python\ndef finalize(question, answer):\n    return answer.strip()\n```",  # gen 4
    ]
    scores = [("question.strip()", ok(10.0, {"a": 10, "b": 10})),
              ('SYSTEM_EXTRA = "Be brief."', ok(60.0, {"a": 60, "b": 60}, n=55, fbn=52)),
              ('"rag_k": 4', ok(52.0, {"a": 45, "b": 59}))]
    out, rows, prompts, scored = run_diverse(tmp_path, monkeypatch, replies, scores, generations=4)
    att = [r for r in rows if r["event"] == "attempt"]
    assert [r["kind"] for r in att] == ["config", "system_extra", "prepare", "finalize"]
    assert [r["focus"] for r in att] == ["a", "b", "a", "b"]                   # focus rotates too
    assert "THIS TIME the kind of change is: config" in prompts[0] and "valid values" in prompts[0]
    assert "Failures in category a" in prompts[0] and "QB" not in prompts[0]
    assert "asks for a system_extra change only" in prompts[2]                  # the wrong-kind retry
    assert att[0]["archived"] and not att[0]["kept"]                            # above the seed floor, no gain
    assert att[1]["kept"] and att[1]["archived"]                                # judged against the champion
    assert not att[2]["kept"] and not att[2]["archived"]                        # below the seed floor
    assert att[3]["archived"]
    arch = json.load(open(out / "archive.json", encoding="utf-8"))
    champ = open(out / "champion.py", encoding="utf-8").read()
    assert 'SYSTEM_EXTRA = "Be brief."' in champ and arch["champion"] == dv.ast_key(champ)[:12]
    assert len(arch["entries"]) == 4 and arch["seed"] == dv.ast_key(SEED)[:12]
    assert sum(e["children"] for e in arch["entries"]) == 4
    assert rows[-1]["event"] == "end" and len(rows[-1]["archive"]) == 4
    assert all(r["parent"] in [e["id"] for e in arch["entries"]] for r in att)


def test_duplicate_skips_evaluation_after_a_restart(tmp_path, monkeypatch):
    out, rows, _, _ = run_diverse(tmp_path, monkeypatch, ["CHANGE: a\nSET rag_k = 4"], [], generations=1, archive=0)
    assert rows[1]["kind"] == "config" and not rows[1]["kept"] and "duplicate" not in rows[1]
    replies = ['CHANGE: s\nSYSTEM_EXTRA = "One."',
               "CHANGE: p\n```python\ndef prepare(question, doc):\n    return question.strip()\n```",
               "CHANGE: f\n```python\ndef finalize(question, answer):\n    return answer.strip()\n```",
               "CHANGE: again\nSET rag_k = 4  # more", "CHANGE: again\nSET rag_k=4"]
    out, rows, prompts, scored = run_diverse(tmp_path, monkeypatch, replies, [], generations=4, archive=0)
    att = [r for r in rows if r["event"] == "attempt"]
    assert [r["gen"] for r in att] == [1, 2, 3, 4, 5]                          # resumed at generation 2
    last = att[-1]
    assert last["kind"] == "config" and last["duplicate"] and last["why"].startswith("duplicate:")
    assert "already tried" in prompts[-1] and len(last["parse_errors"]) == 2
    assert not any('"rag_k": 4' in s for s in scored)                         # never evaluated again
    assert loop.public_why(last).startswith("duplicate:")
    assert not (out / "archive.json").exists() and len(json.load(open(out / "seen.json"))) == 5


def test_archive_survives_a_restart(tmp_path, monkeypatch):
    out, _, _, _ = run_diverse(tmp_path, monkeypatch, ["CHANGE: a\nSET rag_k = 4"], [], generations=1)
    before = json.load(open(out / "archive.json", encoding="utf-8"))
    assert len(before["entries"]) == 2
    out, rows, _, _ = run_diverse(tmp_path, monkeypatch, ['CHANGE: s\nSYSTEM_EXTRA = "One."'], [], generations=1)
    after = json.load(open(out / "archive.json", encoding="utf-8"))
    assert [e["id"] for e in after["entries"][:2]] == [e["id"] for e in before["entries"]]
    assert sum(e["children"] for e in after["entries"]) == 2 and len(after["entries"]) == 3
    assert rows[-2]["gen"] == 2 and rows[-2]["kind"] == "system_extra"


def test_no_diverse_keeps_the_old_behaviour(tmp_path, monkeypatch):
    replies = ['CHANGE: be brief\nSYSTEM_EXTRA = "Be brief."', "CHANGE: k\nSET rag_k = 4"]
    out, rows, prompts, _ = run_diverse(tmp_path, monkeypatch, replies, [], generations=2, diverse=False)
    att = [r for r in rows if r["event"] == "attempt"]
    assert all("kind" not in r and "parent" not in r for r in att)
    assert "THIS TIME" not in prompts[0] and "Example of a reply in the right format" in prompts[0]
    assert not (out / "archive.json").exists() and not (out / "seen.json").exists()


def test_cli_defaults_enable_diverse():
    for argv, want in (([], (True, 8)), (["--no-diverse"], (False, 8)), (["--archive", "0"], (True, 0)),
                       (["--diverse", "--archive", "3"], (True, 3))):
        a = loop.parser().parse_args(argv)
        assert (a.diverse, a.archive) == want


def test_judge_files_are_untouched_by_upgrade_1():
    for f in ("gate.py", "evaluate.py", "sandbox.py", "check_strict.py", "isolation.py", "hookworker.py"):
        assert f"rewrite/{f}" in gate.protected()
    assert "rewrite/diverse.py" in gate.protected()      # the new module is fingerprinted like the rest
