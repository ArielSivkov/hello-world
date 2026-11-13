"""Model loading, scoring and LoRA training."""
from __future__ import annotations

import random
from pathlib import Path

import numpy as np
import torch
from peft import LoraConfig, PeftModel, get_peft_model
from transformers import AutoModelForCausalLM, AutoTokenizer

from .data import Doc
from .retrieval import BM25

MAX_TARGET = 256   # abstract tokens that are scored / trained on
MAX_CTX_DOC = 200  # tokens kept per retrieved document


def load_tokenizer(name: str):
    tok = AutoTokenizer.from_pretrained(name)
    if tok.pad_token_id is None:
        tok.pad_token = tok.eos_token
    return tok


def load_model(name: str, adapter: Path | None = None, trainable: bool = False):
    model = AutoModelForCausalLM.from_pretrained(name, dtype=torch.float32)
    if adapter is not None:
        model = PeftModel.from_pretrained(model, str(adapter), is_trainable=trainable)
    return model.train() if trainable else model.eval()


def new_adapter(model, rank: int = 16):
    cfg = LoraConfig(r=rank, lora_alpha=2 * rank, lora_dropout=0.05, task_type="CAUSAL_LM",
                     target_modules=["q_proj", "k_proj", "v_proj", "o_proj"])
    return get_peft_model(model, cfg)


def _encode(tok, doc: Doc, context: list[Doc] | None):
    """Return (prefix_ids, target_ids). Only target tokens are scored."""
    prefix = ""
    if context:
        parts = []
        for c in context:
            ids = tok(c.abstract, add_special_tokens=False).input_ids[:MAX_CTX_DOC]
            parts.append(f"Title: {c.title}\nAbstract: {tok.decode(ids)}")
        prefix = "Related papers:\n\n" + "\n\n".join(parts) + "\n\nNew paper:\n"
    prefix += f"Title: {doc.title}\nAbstract:"
    p = tok(prefix, add_special_tokens=False).input_ids
    if tok.bos_token_id is not None:
        p = [tok.bos_token_id] + p
    t = tok(" " + doc.abstract, add_special_tokens=False).input_ids[:MAX_TARGET]
    return p, t


def _batches(items, size):
    for i in range(0, len(items), size):
        yield items[i:i + size]


def _collate(tok, pairs):
    n = max(len(p) + len(t) for p, t in pairs)
    ids = torch.full((len(pairs), n), tok.pad_token_id, dtype=torch.long)
    labels = torch.full((len(pairs), n), -100, dtype=torch.long)
    mask = torch.zeros((len(pairs), n), dtype=torch.long)
    for i, (p, t) in enumerate(pairs):
        seq = p + t
        ids[i, :len(seq)] = torch.tensor(seq)
        mask[i, :len(seq)] = 1
        labels[i, len(p):len(seq)] = torch.tensor(t)
    return ids, mask, labels


@torch.no_grad()
def score(model, tok, docs: list[Doc], index: BM25 | None = None, k: int = 3,
          batch_size: int = 8) -> tuple[np.ndarray, np.ndarray]:
    """Per-document (negative log-likelihood of the abstract, token count)."""
    model.eval()
    pairs = [_encode(tok, d, index.search(d.title, k, exclude=d.id) if index else None) for d in docs]
    order = sorted(range(len(pairs)), key=lambda i: -(len(pairs[i][0]) + len(pairs[i][1])))
    nll, ntok = np.zeros(len(docs)), np.zeros(len(docs))
    for chunk in _batches(order, batch_size):
        ids, mask, labels = _collate(tok, [pairs[i] for i in chunk])
        logits = model(input_ids=ids, attention_mask=mask).logits[:, :-1]
        tgt = labels[:, 1:]
        loss = torch.nn.functional.cross_entropy(
            logits.reshape(-1, logits.size(-1)), tgt.reshape(-1), ignore_index=-100,
            reduction="none").view(tgt.shape)
        for row, i in enumerate(chunk):
            nll[i] = loss[row].sum().item()
            ntok[i] = (tgt[row] != -100).sum().item()
    return nll, ntok


def train(model, tok, docs: list[Doc], epochs: int = 2, batch_size: int = 8, lr: float = 2e-4,
          seed: int = 0) -> float:
    """Continue training the adapter on `docs`. Returns the mean loss of the last epoch."""
    model.train()
    params = [p for p in model.parameters() if p.requires_grad]
    opt = torch.optim.AdamW(params, lr=lr, weight_decay=0.0)
    pairs = [_encode(tok, d, None) for d in docs]
    rng = random.Random(seed)
    steps = epochs * ((len(pairs) + batch_size - 1) // batch_size)
    sched = torch.optim.lr_scheduler.LinearLR(opt, 1.0, 0.1, total_iters=steps)
    last = []
    for ep in range(epochs):
        order = list(range(len(pairs)))
        rng.shuffle(order)
        last = []
        for chunk in _batches(order, batch_size):
            ids, mask, labels = _collate(tok, [pairs[i] for i in chunk])
            loss = model(input_ids=ids, attention_mask=mask, labels=labels).loss
            loss.backward()
            torch.nn.utils.clip_grad_norm_(params, 1.0)
            opt.step(); sched.step(); opt.zero_grad()
            last.append(loss.item())
    model.eval()
    return float(np.mean(last))
