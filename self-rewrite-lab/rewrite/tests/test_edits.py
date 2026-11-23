"""Offline tests for the edit-based proposal format (rewrite/edits.py) and the loop's use of it."""
import glob
import json
import os
import shutil
import sys

import pytest

LAB = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path[:0] = [os.path.join(LAB, "ion-loop"), LAB]

from rewrite import edits, loop, proposer, sandbox   # noqa: E402

SEED = open(os.path.join(LAB, "rewrite", "genome", "seed.py"), encoding="utf-8").read()
ATTEMPTS = sorted(glob.glob(os.path.join(LAB, "rewrite", "lineage", "*", "attempts", "*.txt")))


def apply(reply, champion=SEED):
    src, change = edits.apply_reply(champion, reply)
    mod = sandbox.load(src)     # every candidate the applier builds must pass the unchanged sandbox
    return src, change, mod


# ------------------------------------------------------------------------------------- valid edits

def test_set_lines_and_system_extra():
    src, change, mod = apply('CHANGE: more passages\nSET rag_k = 5\nSET extract = llm\n'
                             'SET auto_web: false\nSYSTEM_EXTRA = "ענה במספר בלבד."')
    assert change == "more passages"
    assert mod.CONFIG["rag_k"] == 5 and mod.CONFIG["extract"] == "llm" and mod.CONFIG["auto_web"] is False
    assert mod.SYSTEM_EXTRA == "ענה במספר בלבד."
    assert list(mod.CONFIG) == list(sandbox.load(SEED).CONFIG)     # key order and all other keys kept
    assert src.count("\n") == SEED.count("\n")                      # values changed in place


def test_set_value_with_trailing_comment_and_markdown():
    _, change, mod = apply("**CHANGE:** wider notes\n- SET `notes_chars` = 700  # more context\n")
    assert change == "wider notes" and mod.CONFIG["notes_chars"] == 700


def test_bare_assignment_is_used_only_for_config_keys():
    _, _, mod = apply("CHANGE: k\nrag_k = 6\ntotal = 99\n")
    assert mod.CONFIG["rag_k"] == 6


def test_python_block_replaces_function_and_adds_helper_and_import():
    reply = ('CHANGE: strip a final period\n```python\nimport re\n\n'
             'def clean(a):\n    return re.sub(r"\\.$", "", a)\n\n'
             'def finalize(question, answer):\n    return clean(answer.strip())\n```\n'
             'This should help the basic category.')
    src, _, mod = apply(reply)
    assert mod.finalize("q", "  פריז. ") == "פריז"
    assert mod.prepare("שאלה", None) == "שאלה"          # untouched
    assert src.index("import re") < src.index("CONFIG") < src.index("def clean") < src.index("def prepare")


def test_python_block_with_config_subscript_and_system_extra():
    _, change, mod = apply('```python\n# CHANGE: hebrew prompt\nCONFIG["sys_hebrew"] = True\n'
                           'SYSTEM_EXTRA = "Be brief."\n```')
    assert change == "hebrew prompt" and mod.CONFIG["sys_hebrew"] is True and mod.SYSTEM_EXTRA == "Be brief."


def test_set_lines_inside_an_unlabeled_code_block():
    _, _, mod = apply("CHANGE: brief\n```\nSET brief = True\nSET max_steps = 5\n```")
    assert mod.CONFIG["brief"] is True and mod.CONFIG["max_steps"] == 5


def test_partial_config_dict_merges_instead_of_dropping_keys():
    _, _, mod = apply('CHANGE: c\n```python\nCONFIG = {"rag_k": 4, "brief": True}\n```')
    assert mod.CONFIG["rag_k"] == 4 and mod.CONFIG["brief"] and mod.CONFIG["extract"] == "structured"


def test_search_replace_block():
    reply = ('CHANGE: trim\n```\n<<<<<<< SEARCH\ndef finalize(question, answer):\n    return answer\n'
             '=======\ndef finalize(question, answer):\n    return answer.strip()\n>>>>>>> REPLACE\n```')
    _, _, mod = apply(reply)
    assert mod.finalize("q", " x ") == "x"


def test_search_replace_tolerates_indentation_noise():
    _, _, mod = apply('CHANGE: k\n<<<<<<< SEARCH\n"rag_k": 3,\n=======\n    "rag_k": 5,\n>>>>>>> REPLACE\n')
    assert mod.CONFIG["rag_k"] == 5


def test_json_ops():
    reply = ('CHANGE: json\n```json\n{"ops": [{"op": "set_config", "key": "notes_n", "value": 3},\n'
             '{"op": "set_system_extra", "text": "Answer briefly."},\n'
             '{"op": "replace_function", "name": "prepare", "body": "return question.strip()"}]}\n```')
    _, _, mod = apply(reply)
    assert mod.CONFIG["notes_n"] == 3 and mod.SYSTEM_EXTRA == "Answer briefly."
    assert mod.prepare("  q ", None) == "q"


def test_json_config_shape():
    _, _, mod = apply('```json\n{"CONFIG": {"verify": true}}\n```')
    assert mod.CONFIG["verify"] is True


def test_edits_compose_on_an_evolved_champion():
    first, _, _ = apply('CHANGE: a\nSET rag_k = 4\n```python\nimport re\n\ndef finalize(question, answer):\n'
                        '    return re.sub(r"\\s+", " ", answer)\n```')
    second, _, mod = apply('CHANGE: b\nSYSTEM_EXTRA = "x"\n```python\nimport re\n\ndef prepare(question, doc):\n'
                           '    return question + " "\n```', champion=first)
    assert second.count("import re") == 1 and mod.CONFIG["rag_k"] == 4 and mod.SYSTEM_EXTRA == "x"
    assert mod.finalize("q", "a  b") == "a b" and mod.prepare("q", None) == "q "


def test_unclosed_fence_from_a_truncated_reply():
    _, _, mod = apply("CHANGE: t\n```python\ndef finalize(question, answer):\n    return answer.strip()\n")
    assert mod.finalize("q", " a ") == "a"


# ------------------------------------------------------------------------------------- malformed edits

@pytest.mark.parametrize("reply, reason", [
    ("", "empty reply"),
    ("I think we should improve the prepare function.", "no edits found"),
    ("CHANGE: x\nSET judge = True", "unknown CONFIG key 'judge'"),
    ("CHANGE: x\nSET rag_k = many", "cannot read the value"),
    ("CHANGE: x\nSET rag_k = 2.5", "whole number"),
    ("CHANGE: x\nSET fewshot = 1", "True or False"),
    ("CHANGE: x\nSET extract = magic", "must be one of"),
    ("CHANGE: x\nSET tools = ['calc', 'shell']", "unknown tools"),
    ("CHANGE: x\nSET doc_chars = 999999999", "out of range"),
    ("CHANGE: x\n```python\ndef finalize(answer):\n    return answer\n```", "exactly 2 arguments"),
    ("CHANGE: x\n```python\ndef finalize(question, answer)\n    return answer\n```", "syntax error"),
    ("CHANGE: x\n```python\nfor i in range(3):\n    pass\n```", "only def, imports and assignments"),
    ("CHANGE: x\n```python\nCONFIG = dict(rag_k=4)\n```", "plain dict literal"),
    ("CHANGE: x\n```json\n{\"ops\": [{\"op\": \"delete_file\"}]}\n```", "unknown op"),
    ("CHANGE: x\n```json\n{ops: []}\n```", "invalid JSON"),
    ("CHANGE: x\n<<<<<<< SEARCH\ndef nothing():\n=======\nx = 1\n>>>>>>> REPLACE", "does not match"),
    ("CHANGE: x\n<<<<<<< SEARCH\n):\n=======\n): \n>>>>>>> REPLACE", "matches 2 places"),
    ("CHANGE: x\nSYSTEM_EXTRA = \"" + "א" * 2100 + "\"", "longer than 2000"),
])
def test_malformed_edits_are_refused_with_a_reason(reply, reason):
    with pytest.raises(edits.EditError, match=reason):
        edits.apply_reply(SEED, reply)


def test_sandbox_still_judges_what_the_applier_builds():
    # the applier does not enforce the sandbox rules: a forbidden import is applied, then refused there
    src, _ = edits.apply_reply(SEED, "CHANGE: x\n```python\nimport os\n\ndef finalize(question, answer):\n"
                                     "    return os.getcwd()\n```")
    with pytest.raises(sandbox.Refused, match="import of 'os'"):
        sandbox.check(src)


def test_parse_reports_no_change_and_errors():
    src, change, why = proposer.parse("CHANGE: same\nSET rag_k = 3", SEED, "edits")
    assert src is None and change == "same" and "changes nothing" in why
    src, change, why = proposer.parse("CHANGE: bad\nSET rag_k = x", SEED, "edits")
    assert src is None and change == "bad" and why.startswith("edit: ")
    src, change, why = proposer.parse("CHANGE: ok\nSET rag_k = 4", SEED, "edits")
    assert src is not None and why is None


# ------------------------------------------------------------------------------------- the real replies

@pytest.mark.skipif(not ATTEMPTS, reason="no recorded attempts")
@pytest.mark.parametrize("path", ATTEMPTS, ids=os.path.basename)
def test_real_replies_never_crash_the_parser(path):
    reply = open(path, encoding="utf-8").read()
    for fmt in ("full", "edits"):
        src, change, why = proposer.parse(reply, SEED, fmt)
        assert isinstance(change, str) and change
        assert (src is None) == (why is not None)
        if src is not None and fmt == "edits":
            sandbox.load(src)


REAL = os.path.join(LAB, "rewrite", "lineage", "qwen2.5-1.5b", "attempts")


@pytest.mark.skipif(not os.path.exists(os.path.join(REAL, "a003.txt")), reason="stage 1 attempts missing")
def test_real_replies_get_a_useful_reason():
    read = lambda n: open(os.path.join(REAL, n), encoding="utf-8").read()     # noqa: E731
    # a001: the whole file echoed back, CHANGE line outside the block. Full mode now finds the CHANGE line.
    assert proposer.extract(read("a001.txt"))[1].startswith("Restructure the question")
    assert "changes nothing" in proposer.parse(read("a001.txt"), SEED, "edits")[2]
    # a002: only a comment in the block (full mode refused it as "missing function prepare()")
    assert "no edits found" in proposer.parse(read("a002.txt"), SEED, "edits")[2]
    # a003: the file again, with a CHANGE comment; reformatted but equal
    assert "changes nothing" in proposer.parse(read("a003.txt"), SEED, "edits")[2]


# ------------------------------------------------------------------------------------- prompt and loop

RESULT = {"total": 50.0, "cats": {"basic": 20, "calc": 80},
          "failures": [{"id": "x", "cat": "calc", "kind": "calc", "q": "Q1", "expected": ["1"], "got": "2",
                        "trace": ["model: hi"]},
                       {"id": "y", "cat": "basic", "kind": "basic", "q": "Q2", "expected": ["b"], "got": "c",
                        "trace": []}]}


def test_edit_prompt_is_short_and_shows_an_example():
    p = proposer.build_prompt(SEED, RESULT, [{"change": "c1", "why": "edit: no edits found"}], fmt="edits")
    full = proposer.build_prompt(SEED, RESULT, [], fmt="full")
    assert "Example of a reply" in p and "SET <config key>" in p and "c1: edit: no edits found" in p
    assert p.index("Q2") < p.index("Q1") and "holdout" not in p.lower()
    assert len(p.splitlines()) < len(full.splitlines())
    assert "rag_k=3" in p and '"rag_k": 3' not in p        # CONFIG packed onto a few lines
    # the example in the prompt is itself a valid reply
    example = p[p.index("CHANGE: cut"):p.index("Make ONE")]
    assert apply(example)[2].finalize("q", "a\nb") == "a"
    assert "previous reply could not be used: boom" in proposer.retry_prompt(p, "boom")


def run_loop(tmp_path, monkeypatch, replies, scores, fmt="edits", retries=1):
    """Run rewrite.loop.main offline: scripted proposer replies, scripted gate scores."""
    lab = tmp_path / "lab"
    (lab / "rewrite" / "genome").mkdir(parents=True)
    shutil.copy(os.path.join(LAB, "rewrite", "genome", "seed.py"), lab / "rewrite" / "genome" / "seed.py")
    monkeypatch.setattr(loop, "LAB", str(lab))
    monkeypatch.setattr(loop, "SEED", str(lab / "rewrite" / "genome" / "seed.py"))
    monkeypatch.setattr(loop, "TAG", "test")
    monkeypatch.setattr(loop, "RUN", "test")
    prompts = []

    def ask(prompt, seed, temperature=0.7, **kw):
        prompts.append(prompt)
        return replies.pop(0)

    def score(source, split="dev", timeout=0, log=None):
        if split != "dev":
            return {"total": 0, "cats": {}}
        for needle, res in scores:
            if needle in source:
                return dict(res, genome="g", n_correct=int(res["total"]))
        return {"total": 50.0, "cats": {"a": 50, "b": 50}, "genome": "g", "n_correct": 50}

    monkeypatch.setattr(proposer, "ask", ask)
    monkeypatch.setattr(loop.gate, "score", score)

    class A:
        generations, tolerance, temperature, timeout, margin = 2, 10, 0.7, 10, 2
    A.format, A.retries = fmt, retries
    loop.main(A)
    rows = [json.loads(l) for l in open(lab / "rewrite" / "lineage" / "test" / "history.jsonl", encoding="utf-8")]
    return lab, rows, prompts


def test_loop_retries_a_parse_failure_once_and_accepts_an_edit(tmp_path, monkeypatch):
    replies = ["I would improve things.",                                   # gen 1: unparseable
               "CHANGE: more passages\nSET rag_k = 5",                      # gen 1 retry: accepted
               "CHANGE: nope\nSET rag_k = lots", "still nothing"]           # gen 2: fails twice
    lab, rows, prompts = run_loop(tmp_path, monkeypatch, replies,
                                  [('"rag_k": 5', {"total": 60.0, "cats": {"a": 60, "b": 60}})])
    g1, g2 = rows[1], rows[2]
    assert g1["kept"] and g1["change"] == "more passages" and g1["parse_errors"][0].startswith("edit: no edits")
    assert "could not be used: edit: no edits found" in prompts[1]
    assert not g2["kept"] and len(g2["parse_errors"]) == 2 and g2["why"].startswith("edit: no edits")
    assert "more passages" not in prompts[2] and "rag_k=5" in prompts[2]     # gen 2 sees the new champion
    champ = (lab / "rewrite" / "lineage" / "test" / "champion.py").read_text(encoding="utf-8")
    assert '"rag_k": 5' in champ and (lab / "rewrite" / "lineage" / "test" / "g001.py").exists()
    assert (lab / "rewrite" / "lineage" / "test" / "attempts" / "a001-retry1.txt").exists()
    assert rows[-1]["event"] == "end" and rows[-1]["accepted_total"] == 1


def test_loop_full_format_still_works(tmp_path, monkeypatch):
    full = "```python\n" + SEED.replace("return answer", "return answer.strip()") + "```"
    lab, rows, _ = run_loop(tmp_path, monkeypatch, [full, "no code"],
                            [("answer.strip()", {"total": 55.0, "cats": {"a": 55, "b": 55}})],
                            fmt="full", retries=0)
    assert rows[1]["kept"] and rows[1]["format"] == "full"
    assert not rows[2]["kept"] and rows[2]["why"] == "no python code block in the reply"


def test_echo_of_the_compact_view_changes_nothing_and_an_edited_echo_applies():
    shown = edits.compact(SEED)
    assert "changes nothing" in proposer.parse("```python\n" + shown + "```", SEED, "edits")[2]
    edited = shown.replace("rag_k=3", "rag_k=4").replace("return answer", "return answer.strip()")
    _, _, mod = apply("CHANGE: e\n```python\n" + edited + "```")
    assert mod.CONFIG["rag_k"] == 4 and mod.CONFIG["tools"] == ["calc"] and mod.finalize("q", " a ") == "a"


@pytest.mark.skipif(not os.path.exists(os.path.join(REAL, "a005.txt")), reason="stage 1 attempts a004-a005 missing")
@pytest.mark.parametrize("name", ["a004.txt", "a005.txt"])
def test_real_partial_replies_are_refused_in_full_mode_but_applied_in_edit_mode(name):
    # the 1.5B model already answers with only the changed function; full mode throws that away
    reply = open(os.path.join(REAL, name), encoding="utf-8").read()
    src, _, _ = proposer.parse(reply, SEED, "full")
    with pytest.raises(sandbox.Refused, match="missing function|CONFIG must be a dict"):
        sandbox.load(src)     # a004: no finalize(); a005: no CONFIG (stage 1 logged "evaluation failed")
    src, change, why = proposer.parse(reply, SEED, "edits")
    assert why is None and change.startswith("Simplif")
    mod = sandbox.load(src)
    assert mod.CONFIG == sandbox.load(SEED).CONFIG and mod.prepare("A B", "d") != "A B"
