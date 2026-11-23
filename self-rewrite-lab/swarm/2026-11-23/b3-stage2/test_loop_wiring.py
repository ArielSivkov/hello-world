"""End-to-end wiring of loop.main with a fake model and a fake generator.

torch, transformers and peft are replaced by stubs, so this runs anywhere. It
checks what the loop feeds to train() in each mode and that the decision still
comes from the unchanged stats.gate; it says nothing about real model quality.
"""
import hashlib
import importlib
import json
import sys
import types
from pathlib import Path

import numpy as np
import pytest

from selfloop.data import Doc, save_jsonl

ABS = ("We study {k} for small models. Our method adds a cache. "
       "It reduces latency by a margin. Results hold on three benchmarks.")


class FakeModel:
    def __init__(self, skill=0.0):
        self.skill, self.training = skill, False

    def save_pretrained(self, path):
        Path(path).mkdir(parents=True, exist_ok=True)
        (Path(path) / "skill").write_text(str(self.skill))


def install_stubs(monkeypatch, calls):
    torch = types.ModuleType("torch")
    torch.manual_seed = lambda s: None
    model = types.ModuleType("selfloop.model")
    model.load_tokenizer = lambda name: object()
    model.load_model = lambda name, adapter=None, trainable=False: \
        FakeModel(float((Path(adapter) / "skill").read_text()) if adapter else 0.0)
    model.new_adapter = lambda m: m

    def score(m, tok, docs, index=None):
        ntok = np.full(len(docs), 100.0)
        noise = np.array([int(hashlib.sha256(d.id.encode()).hexdigest(), 16) % 7 for d in docs])
        fresh = np.array([0.0 if d.id.startswith("core") else m.skill for d in docs])
        return ntok * (5.0 - fresh) + noise - (5.0 if index else 0.0), ntok

    def train(m, tok, docs, epochs, lr, seed):
        calls.append([d.id for d in docs])
        m.skill += 0.002 * len(docs)
        return 1.0

    model.score, model.train = score, train
    monkeypatch.setitem(sys.modules, "torch", torch)
    monkeypatch.setitem(sys.modules, "selfloop.model", model)
    monkeypatch.delitem(sys.modules, "selfloop.loop", raising=False)
    return importlib.import_module("selfloop.loop")


def make_data(d: Path):
    def docs(prefix, n):
        return [Doc(f"{prefix}{i}", f"title {prefix}{i}", ABS.format(k=prefix), "", ("cs.CL",), "")
                for i in range(n)]
    for w in range(3):
        save_jsonl(d / f"window_{w}.jsonl", docs(f"w{w}-", 40))
    save_jsonl(d / "core_domain_old.jsonl", docs("core-d", 30))
    save_jsonl(d / "core_general.jsonl", docs("core-g", 30))
    save_jsonl(d / "anchor_general.jsonl", docs("anc", 60))


@pytest.mark.parametrize("mode", ["raw", "self", "self+raw"])
def test_loop_modes(monkeypatch, tmp_path, mode):
    calls = []
    loop = install_stubs(monkeypatch, calls)
    make_data(tmp_path / "data")
    out = tmp_path / "out"
    monkeypatch.setattr(sys, "argv", ["loop", "--data", str(tmp_path / "data"), "--out", str(out),
                                      "--anchor", "0.5", "--train-on", mode, "--generator", "fake"])
    loop.main()
    log = json.loads((out / "log.json").read_text())
    assert len(log) == 2 and all(r["train_on"] == mode for r in log)
    first = calls[0]
    src = [i for i in first if i.startswith("w0-") and "#" not in i]
    edits = [i for i in first if "#se" in i]
    anchors = [i for i in first if i.startswith("anc")]
    assert len(anchors) == 20                      # anchor follows source docs, as in stage 0b
    if mode == "raw":
        assert len(src) == 40 and not edits
        assert not (out / "selfedits_0.jsonl").exists()
    elif mode == "self":
        assert not src and len(edits) == 80        # no raw document reaches the weights
        assert (out / "selfedits_0.jsonl").exists()
    else:
        assert len(src) == 40 and len(edits) == 80
    # nothing from the window being tested is ever trained on in the same cycle
    assert not any(i.split("#")[0].startswith("w1-") for i in first)
    # replay in cycle 1 is drawn from what cycle 0 trained on (edits in self mode)
    replay = [i for i in calls[1] if i.startswith("w0-")]
    assert len(replay) == 20
    if mode == "self":
        assert all("#se" in i for i in replay)
    for r in log:
        assert set(r["decision"]) == {"accept", "reasons"}
        assert r["decision"]["accept"] == (r["candidate_vs_incumbent"]["hi"] < 0 and not r["decision"]["reasons"])


def test_cycles_flag(monkeypatch, tmp_path):
    calls = []
    loop = install_stubs(monkeypatch, calls)
    make_data(tmp_path / "data")
    monkeypatch.setattr(sys, "argv", ["loop", "--data", str(tmp_path / "data"), "--out",
                                      str(tmp_path / "o"), "--cycles", "1"])
    loop.main()
    assert len(json.loads((tmp_path / "o" / "log.json").read_text())) == 1


def test_compare_two_runs(monkeypatch, tmp_path):
    loop = install_stubs(monkeypatch, [])
    make_data(tmp_path / "data")
    for mode in ("raw", "self+raw"):
        monkeypatch.setattr(sys, "argv", ["loop", "--data", str(tmp_path / "data"), "--out",
                                          str(tmp_path / mode), "--train-on", mode, "--generator", "fake"])
        loop.main()
    from selfloop.compare import compare
    rows = compare(tmp_path / "self+raw", tmp_path / "raw")
    assert [r["cycle"] for r in rows] == [0, 1]
    assert rows[0]["A_vs_B"]["hi"] < 0     # the stub rewards more training items
