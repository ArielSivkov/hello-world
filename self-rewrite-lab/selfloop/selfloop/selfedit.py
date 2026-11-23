"""Stage 2: self-edits. The model writes the training data for its own next update.

For every document chosen for training, a generator produces a few short texts
(implications, restatements, question/answer pairs). Each one becomes a Doc with
the original title and the generated text in place of the abstract, so the
existing `model.train` trains on P(generated text | title) and the existing
`model.score` / `stats.gate` judge the result on the unseen next week exactly as
for raw documents. Nothing here touches the metric or the gate.

Generators are pluggable:
  fake   - deterministic, no model, no torch (tests and dry runs)
  model  - the incumbent model itself (base + current adapter), i.e. SEAL's
           inner loop without the RL outer loop

Leakage rule: a generator only ever sees documents of the training window.
`build_training_set` refuses source documents whose id is in the test window.
"""
from __future__ import annotations

import hashlib
import json
import re
from dataclasses import asdict, replace
from pathlib import Path
from typing import Protocol

from .data import Doc

MODES = ("raw", "self", "self+raw")

# SEAL's knowledge-incorporation prompt asks for "implications" of a passage
# (Zweiger et al. 2025, arXiv:2506.10943). A 135M base model is not instruction
# tuned, so the prompt is a plain-text continuation with a fixed format.
PROMPTS = {
    "implications": "Title: {title}\nAbstract: {abstract}\n\nImplications of this paper:\n1.",
    "restate": "Title: {title}\nAbstract: {abstract}\n\nThe same paper, explained in other words:\n",
    "qa": "Title: {title}\nAbstract: {abstract}\n\nQuestions and answers about this paper:\nQ:",
}


class Generator(Protocol):
    name: str

    def generate(self, doc: Doc, n: int, seed: int) -> list[str]:
        """Return up to n generated texts for `doc`."""


_SENT = re.compile(r"(?<=[.!?])\s+(?=[A-Z0-9])")


def sentences(text: str) -> list[str]:
    return [s.strip() for s in _SENT.split(text) if s.strip()]


class FakeGenerator:
    """Deterministic stand-in: rotates and relabels the abstract's own sentences.

    Output depends only on (doc, n, seed, style), never on a model, so tests are
    exact. It is not meant to be a good self-edit, only a well-formed one.
    """

    def __init__(self, style: str = "implications"):
        self.style = style
        self.name = f"fake-{style}"

    def generate(self, doc: Doc, n: int, seed: int) -> list[str]:
        sents = sentences(doc.abstract) or [doc.abstract]
        h = int(hashlib.sha256(f"{doc.id}|{seed}".encode()).hexdigest(), 16)
        out = []
        for k in range(n):
            start = (h + k) % len(sents)
            picked = sents[start:] + sents[:start]
            body = " ".join(picked[: max(1, len(sents) // 2)])
            out.append(f"{self.style.capitalize()} {k + 1}: {body}")
        return out


class ModelGenerator:
    """The model writes its own training data (sampling from the incumbent).

    `model` is the same object the loop is about to train; generation runs in
    eval mode with no gradient, before training starts, so it is the incumbent
    (base + current adapter) that writes the data.
    """

    def __init__(self, model, tok, style: str = "implications", max_new_tokens: int = 160,
                 temperature: float = 0.7, top_p: float = 0.9, max_prompt_tokens: int = 384):
        self.model, self.tok, self.style = model, tok, style
        self.max_new_tokens, self.temperature, self.top_p = max_new_tokens, temperature, top_p
        self.max_prompt_tokens = max_prompt_tokens
        self.name = f"model-{style}"

    def generate(self, doc: Doc, n: int, seed: int) -> list[str]:
        import torch  # local import: the rest of this module needs no torch

        prompt = PROMPTS[self.style].format(title=doc.title, abstract=doc.abstract)
        ids = self.tok(prompt, return_tensors="pt", add_special_tokens=False).input_ids
        ids = ids[:, -self.max_prompt_tokens:]
        if self.tok.bos_token_id is not None:
            ids = torch.cat([torch.tensor([[self.tok.bos_token_id]]), ids], 1)
        was_training = self.model.training
        self.model.eval()
        torch.manual_seed(seed)
        with torch.no_grad():
            out = self.model.generate(
                input_ids=ids.repeat(n, 1), attention_mask=torch.ones_like(ids).repeat(n, 1),
                do_sample=True, temperature=self.temperature, top_p=self.top_p,
                max_new_tokens=self.max_new_tokens, pad_token_id=self.tok.pad_token_id)
        if was_training:
            self.model.train()
        return [self.tok.decode(o[ids.shape[1]:], skip_special_tokens=True) for o in out]


def clean(text: str, min_chars: int = 40) -> str | None:
    """Keep the first block of generated text; drop it if too short or a copy of the prompt."""
    text = text.split("\n\n")[0]
    text = re.sub(r"\s+", " ", text).strip()
    if len(text) < min_chars or text.lower().startswith(("title:", "abstract:")):
        return None
    return text


def self_edit_docs(doc: Doc, gen: Generator, n: int, seed: int) -> list[Doc]:
    """Turn one source document into up to n training Docs, with provenance."""
    out, seen = [], set()
    for k, raw in enumerate(gen.generate(doc, n, seed)):
        text = clean(raw)
        if text is None or text in seen or text == doc.abstract:
            continue
        seen.add(text)
        out.append(replace(doc, id=f"{doc.id}#se{k}", abstract=text,
                           categories=doc.categories + (f"self-edit:{gen.name}",)))
    return out


def build_training_set(mode: str, chosen: list[Doc], gen: Generator | None, n: int, seed: int,
                       test_ids: set[str] = frozenset()) -> list[Doc]:
    """The documents the adapter trains on this cycle (before replay and anchor)."""
    if mode not in MODES:
        raise ValueError(mode)
    leaked = [d.id for d in chosen if d.id in test_ids]
    if leaked:
        raise ValueError(f"self-edit source documents from the test window: {leaked[:5]}")
    if mode == "raw":
        return list(chosen)
    if gen is None:
        raise ValueError("self-edit mode needs a generator")
    edits = [e for i, d in enumerate(chosen) for e in self_edit_docs(d, gen, n, seed * 100003 + i)]
    return edits if mode == "self" else list(chosen) + edits


def save_edits(path: Path, docs: list[Doc]) -> None:
    """Every self-generated text is kept on disk so it can be audited or removed."""
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w") as f:
        for d in docs:
            f.write(json.dumps(asdict(d), ensure_ascii=False) + "\n")
