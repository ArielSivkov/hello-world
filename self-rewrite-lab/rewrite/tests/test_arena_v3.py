"""Arena v3 (rewrite/build_arena_v3.py) and the ARENA switch (rewrite/arenas.py). No model server needed;
the findability spot check reads the local search index and is skipped when it is missing."""
import json
import os
import random
import re
import subprocess
import sys

import pytest

LAB = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path[:0] = [os.path.join(LAB, "ion-loop"), os.path.join(LAB, "ion-loop", "arena"), LAB]

from rewrite import arenas, evaluate, gate   # noqa: E402

V2 = os.path.join(LAB, "ion-loop", "arena")
V3 = os.path.join(V2, "v3")
SPLITS = ("dev", "holdout", "shadow")


def rows(d, split):
    return [json.loads(l) for l in open(os.path.join(d, f"{split}.jsonl"), encoding="utf-8")]


V3_ROWS = {s: rows(V3, s) for s in SPLITS}
V2_ROWS = {s: rows(V2, s) for s in SPLITS}


def test_v3_files_exist_and_are_about_three_times_v2():
    for s in SPLITS:
        assert os.path.getsize(os.path.join(V3, f"{s}.jsonl")) > 0
    n3, n2 = (sum(len(r[s]) for s in SPLITS) for r in (V3_ROWS, V2_ROWS))
    assert 2.5 * n2 <= n3 <= 3.5 * n2, (n2, n3)
    assert 220 <= len(V3_ROWS["dev"]) <= 260 and 140 <= len(V3_ROWS["holdout"]) <= 180
    assert 100 <= len(V3_ROWS["shadow"]) <= 140


def test_same_kinds_as_v2_and_every_kind_in_both_dev_halves():
    kinds = lambda rs: {t["kind"] for s in SPLITS for t in rs[s]}      # noqa: E731
    assert kinds(V3_ROWS) == kinds(V2_ROWS)
    fb, gh = evaluate.dev_halves(V3_ROWS["dev"])
    assert {t["kind"] for t in fb} == {t["kind"] for t in gh} == {t["kind"] for t in V3_ROWS["dev"]}
    for s in SPLITS:
        ids = [t["id"] for t in V3_ROWS[s]]
        assert len(ids) == len(set(ids)), s


def test_splits_are_disjoint_by_question_and_by_entity():
    qs = [t["q"] for s in SPLITS for t in V3_ROWS[s]]
    assert len(qs) == len(set(qs))                                     # no question twice in all of v3
    assert not set(qs) & {t["q"] for s in SPLITS for t in V2_ROWS[s]}  # and none from v2
    seen = {}
    for s in SPLITS:
        for t in V3_ROWS[s]:
            for e in t.get("entities", []):
                assert e not in seen, (e, seen.get(e), s)              # one task per entity in all of v3
                seen[e] = s
    assert len(seen) > 300
    ent = json.load(open(os.path.join(V3, "entities.json"), encoding="utf-8"))
    assert {e for s in SPLITS for e in ent[s]} == set(seen)


def test_entities_are_new_to_v2():
    ent = json.load(open(os.path.join(V2, "entities.json"), encoding="utf-8"))
    old = {p[0] for p in ent["people"]} | {p[0] for p in ent["places"]}
    v2_text = "\n".join(t["q"] for s in SPLITS for t in V2_ROWS[s])   # v2 shadow names are only in its questions
    for s in SPLITS:
        for t in V3_ROWS[s]:
            for e in t.get("entities", []):
                assert e not in old and e not in v2_text, e
                assert e in t["q"], (e, t["q"])


def test_every_lookup_task_names_its_entities():
    for s in SPLITS:
        for t in V3_ROWS[s]:
            if t["cat"] in ("web", "multistep"):
                n = 1 if t["kind"] in ("birth", "death", "founded", "lifespan") else 2
                assert len(t["entities"]) == n, t["id"]


def test_answers_are_consistent():
    for s in SPLITS:
        for t in V3_ROWS[s]:
            assert t["answers"] and all(isinstance(a, str) and a for a in t["answers"]), t["id"]
            if t.get("numeric"):
                assert t["answers"][0].isdigit(), t["id"]
            if t["kind"] == "who-older":
                assert t["answers"][0] in t["entities"] and t["reject"][0] in t["entities"]
            if t["cat"] == "calc":
                assert eval_calc(t["q"]) == int(t["answers"][0]), t["q"]
            if t["cat"] == "longdoc":
                assert t["doc"].count(t["answers"][0]) >= 1


def eval_calc(q):
    n = [int(x) for x in re.findall(r"\d+", q)]
    if "כפול" in q and "ועוד" in q:
        return n[0] + n[1] * n[2]
    if "חלקי" in q:
        return n[0] // n[1] + n[2]
    if q.startswith("כמה זה"):
        return n[0] * n[1]
    if "ארגזים" in q or "כרטיס" in q:
        return n[0] * n[1]
    return n[0] + n[1] - n[2]          # library: b + c - a, in the order the question names them


@pytest.mark.skipif(not os.path.exists(os.path.join(LAB, "ion-loop", "data", "hewiki.db")),
                    reason="the search index is not here")
def test_lookup_answers_are_findable_spot_check():
    import build_tasks as bt
    from ion.tools import web_search
    lookups = [t for s in SPLITS for t in V3_ROWS[s] if t["cat"] in ("web", "multistep")]
    for t in random.Random(7).sample(lookups, 40):
        ents = t["entities"]
        if t["cat"] == "web":
            assert bt.findable(t["q"], [t["answers"][0]], ents) and t["answers"][0] in web_search(ents[0]), t["id"]
        else:
            assert bt.findable(" ".join(ents), [], ents), t["id"]       # both articles come up for the pair


def test_arena_switch_loads_the_right_files(monkeypatch):
    monkeypatch.delenv("ARENA", raising=False)
    assert arenas.name() == "v2" and arenas.load("dev") == V2_ROWS["dev"]
    from arena.run import load as ion_loop_load       # ion-loop's own loader is untouched: always v2
    assert ion_loop_load("dev") == V2_ROWS["dev"]
    monkeypatch.setenv("ARENA", "v3")
    for s in SPLITS:
        assert arenas.load(s) == V3_ROWS[s]
        assert evaluate.load_split(s) == V3_ROWS[s]
    assert ion_loop_load("dev") == V2_ROWS["dev"]
    pool = evaluate.others_by_kind()                   # the spray check uses the same arena
    assert sum(len(v) for v in pool.values()) == sum(len(V3_ROWS[s]) for s in SPLITS)
    monkeypatch.setenv("ARENA", "v4")
    with pytest.raises(ValueError):
        arenas.name()


def test_the_judge_child_uses_the_arena_of_its_parent():
    out = subprocess.run([sys.executable, "-c", "from rewrite import evaluate; print(len(evaluate.load_split('dev')))"],
                         cwd=LAB, env=dict(os.environ, ARENA="v3"), capture_output=True, text=True, check=True)
    assert int(out.stdout) == len(V3_ROWS["dev"])


def test_cache_key_includes_the_arena(judge_runs):
    runs, run = judge_runs
    run("v2")
    run("v3")
    names = sorted(os.listdir(runs))
    assert len(names) == 2 and names[0].startswith("v2-dev-") and names[1].startswith("v3-dev-")


@pytest.fixture
def judge_runs(tmp_path, monkeypatch):
    seed = open(os.path.join(LAB, "rewrite", "genome", "seed.py"), encoding="utf-8").read()
    monkeypatch.setattr(evaluate, "RUNS", str(tmp_path))
    monkeypatch.setattr(evaluate.agent, "run", lambda q, cfg, doc=None: ("", [("model", "x")]))
    monkeypatch.setattr(evaluate.agent, "BASE_PROMPT", evaluate.agent.BASE_PROMPT)
    monkeypatch.setattr(evaluate.agent, "BASE_PROMPT_HE", evaluate.agent.BASE_PROMPT_HE)

    def run(arena):
        monkeypatch.setenv("ARENA", arena)
        r = evaluate.evaluate(seed, "dev", verbose=False)
        assert r["n_tasks"] == len(evaluate.dev_halves(arenas.load("dev"))[1])
        return r
    return str(tmp_path), run


def test_fingerprint_covers_v3():
    covered = set(gate.protected())
    for s in SPLITS:
        assert f"ion-loop/arena/v3/{s}.jsonl" in covered
    assert "ion-loop/arena/v3/entities.json" in covered
    assert "rewrite/arenas.py" in covered and "rewrite/build_arena_v3.py" in covered


def test_v3_is_rebuilt_byte_for_byte(tmp_path, monkeypatch):
    """The builder is deterministic: rebuilding into a scratch directory gives the committed files."""
    if not os.path.exists(os.path.join(LAB, "ion-loop", "data", "hewiki.db")):
        pytest.skip("the search index is not here")
    from rewrite import build_arena_v3 as b
    monkeypatch.setattr(b, "OUT", str(tmp_path))
    tasks, _, used = b.build()
    b.write(tasks, used)
    for name in [f"{s}.jsonl" for s in SPLITS] + ["entities.json"]:
        assert (tmp_path / name).read_bytes() == open(os.path.join(V3, name), "rb").read(), name


def test_honest_genomes_pass_the_answer_scan_on_v3():
    """The loop refuses any genome whose string constants hold a dev answer (sandbox.contains_test_answer).
    A first draft of v3 had car, fire and red among its answers, and the seed's own prompt contains them,
    so every proposal would have been refused."""
    from rewrite import sandbox
    answers = [a for s in SPLITS for t in V3_ROWS[s] for a in t["answers"]]
    for rel in ["rewrite/genome/seed.py", "rewrite/genome/positive_control.py", "rewrite/tests/attacks/honest_black2_22.py",
                "rewrite/tests/attacks/honest_black3_18.py", "rewrite/tests/attacks/honest_black_15.py"]:
        src = open(os.path.join(LAB, rel), encoding="utf-8").read()
        assert sandbox.contains_test_answer(src, answers) is None, rel
