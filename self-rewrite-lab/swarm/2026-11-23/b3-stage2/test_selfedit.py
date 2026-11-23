"""Stage 2 self-edits, offline: fake generator only, no torch, no model."""
import hashlib
from pathlib import Path

import pytest

from selfloop.data import Doc, load_jsonl
from selfloop.selfedit import (FakeGenerator, build_training_set, clean, save_edits,
                               self_edit_docs, sentences)

ROOT = Path(__file__).resolve().parents[1]
ABS = ("We study retrieval for small models. Our method adds a cache. "
       "It reduces latency by a margin. Results hold on three benchmarks.")


def doc(i, text=ABS):
    return Doc(str(i), f"title {i}", text, "2026-10-01", ("cs.CL",), f"http://arxiv.org/abs/{i}")


def test_sentences():
    assert len(sentences(ABS)) == 4


def test_fake_generator_is_deterministic_and_seeded():
    g = FakeGenerator()
    assert g.generate(doc(1), 3, 7) == g.generate(doc(1), 3, 7)
    assert len(g.generate(doc(1), 3, 7)) == 3
    outs = {tuple(g.generate(doc(1), 2, s)) for s in range(10)}
    assert len(outs) > 1   # the seed matters


def test_self_edit_docs_keep_title_and_provenance():
    es = self_edit_docs(doc(5), FakeGenerator(), 2, 0)
    assert [e.id for e in es] == ["5#se0", "5#se1"]
    for e in es:
        assert e.title == "title 5" and e.url == "http://arxiv.org/abs/5"
        assert e.categories == ("cs.CL", "self-edit:fake-implications")
        assert e.abstract != ABS


def test_clean_drops_junk():
    assert clean("too short") is None
    assert clean("Title: copy of the prompt that goes on and on for a while") is None
    assert clean("A real implication that is long enough to keep.\n\nTitle: next") == \
        "A real implication that is long enough to keep."


class Echo:
    name = "echo"

    def __init__(self, outs):
        self.outs = outs

    def generate(self, d, n, seed):
        return self.outs[:n]


def test_duplicates_and_copies_are_dropped():
    g = Echo(["same implication that is long enough to keep", "same implication that is long enough to keep", ABS])
    assert [e.abstract for e in self_edit_docs(doc(1), g, 3, 0)] == ["same implication that is long enough to keep"]


def test_modes():
    chosen = [doc(i) for i in range(4)]
    g = FakeGenerator()
    assert build_training_set("raw", chosen, None, 2, 0) == chosen
    self_only = build_training_set("self", chosen, g, 2, 0)
    assert len(self_only) == 8 and all("#se" in d.id for d in self_only)
    both = build_training_set("self+raw", chosen, g, 2, 0)
    assert both[:4] == chosen and both[4:] == self_only
    assert build_training_set("self", chosen, g, 2, 0) == self_only   # reproducible
    with pytest.raises(ValueError):
        build_training_set("self", chosen, None, 2, 0)
    with pytest.raises(ValueError):
        build_training_set("bogus", chosen, g, 2, 0)


def test_no_generation_from_the_test_window():
    chosen = [doc(i) for i in range(4)]
    with pytest.raises(ValueError, match="test window"):
        build_training_set("self", chosen, FakeGenerator(), 2, 0, test_ids={"2"})


def test_save_and_reload(tmp_path):
    es = build_training_set("self", [doc(1), doc(2)], FakeGenerator(), 2, 0)
    save_edits(tmp_path / "e.jsonl", es)
    assert load_jsonl(tmp_path / "e.jsonl") == es


def test_on_real_window_files():
    w0 = load_jsonl(ROOT / "data" / "window_0.jsonl")
    w1 = load_jsonl(ROOT / "data" / "window_1.jsonl")
    es = build_training_set("self", w0, FakeGenerator(), 2, 0, test_ids={d.id for d in w1})
    assert len(es) >= len(w0)            # at least one usable edit per paper
    assert {e.id.split("#")[0] for e in es} <= {d.id for d in w0}


# The judge must not move: same files as the stage 0b harness, byte for byte.
JUDGE = {
    "selfloop/stats.py": "2886ce09b223252c3285fcbb80c69d8d0c05bc3d77021c82ab783ad2df89f4b2",
}


def test_judge_unchanged():
    for rel, want in JUDGE.items():
        got = hashlib.sha256((ROOT / rel).read_bytes()).hexdigest()
        assert got == want, f"{rel} changed"
