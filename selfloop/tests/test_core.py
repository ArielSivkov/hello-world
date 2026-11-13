import numpy as np

from selfloop.data import Doc, parse_atom, sample
from selfloop.retrieval import BM25
from selfloop.stats import bits_per_token, gate, paired_diff

ATOM = """<?xml version="1.0"?><feed xmlns="http://www.w3.org/2005/Atom"><entry>
<id>http://arxiv.org/abs/2610.01234v2</id><published>2026-10-02T10:00:00Z</published>
<title>A  Title
 here</title><summary>{}</summary><category term="cs.CL"/><category term="cs.LG"/>
</entry><entry><id>http://arxiv.org/abs/2610.09999v1</id><title>Short</title><summary>too short</summary></entry></feed>"""


def doc(i, text):
    return Doc(str(i), f"title {i}", text, "", (), "")


def test_parse_atom_strips_version_and_drops_short():
    docs = parse_atom(ATOM.format("word " * 60))
    assert [d.id for d in docs] == ["2610.01234"]
    assert docs[0].title == "A Title here" and docs[0].categories == ("cs.CL", "cs.LG")


def test_sample_is_deterministic_and_order_independent():
    docs = [doc(i, "x") for i in range(20)]
    assert sample(docs, 5, 1) == sample(docs[::-1], 5, 1)
    assert sample(docs, 5, 1) != sample(docs, 5, 2)


def test_bm25_ranks_and_excludes():
    docs = [doc(0, "retrieval augmented generation"), doc(1, "protein folding"), doc(2, "dense retrieval")]
    idx = BM25(docs)
    assert idx.search("protein", 1)[0].id == "1"
    assert "0" not in [d.id for d in idx.search("retrieval generation", 3, exclude="0")]
    assert idx.search("zzz", 3) == []


def test_paired_diff_sign_and_interval():
    rng = np.random.default_rng(0)
    ntok = rng.integers(100, 200, 300).astype(float)
    b = ntok * 2.0 + rng.normal(0, 5, 300)
    a = b - ntok * 0.05
    d = paired_diff(a, b, ntok)
    assert d["lo"] < d["diff"] < d["hi"] < 0
    assert abs(d["diff"] - (bits_per_token(a, ntok) - bits_per_token(b, ntok))) < 1e-12
    noise = paired_diff(b + rng.normal(0, 5, 300), b, ntok)
    assert noise["lo"] < 0 < noise["hi"]


def test_gate():
    good = {"diff": -0.05, "lo": -0.07, "hi": -0.03}
    flat = {"diff": -0.01, "lo": -0.03, "hi": 0.01}
    ok_core = {"c": {"diff": 0.0, "lo": -0.01, "hi": 0.01}}
    bad_core = {"c": {"diff": 0.08, "lo": 0.05, "hi": 0.11}}
    base = {"c": 3.0}
    assert gate(good, ok_core, base)["accept"]
    assert not gate(flat, ok_core, base)["accept"]
    r = gate(good, bad_core, base)
    assert not r["accept"] and "regressed" in r["reasons"][0]
