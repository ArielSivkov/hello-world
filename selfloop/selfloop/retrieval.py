"""BM25 retrieval: the 'fresh facts live outside the weights' baseline."""
from __future__ import annotations

import math
import re
from collections import Counter

from .data import Doc

_TOK = re.compile(r"[a-z0-9]+")


def tokenize(s: str) -> list[str]:
    return _TOK.findall(s.lower())


class BM25:
    def __init__(self, docs: list[Doc], k1: float = 1.5, b: float = 0.75):
        self.docs, self.k1, self.b = docs, k1, b
        self.tf = [Counter(tokenize(d.text)) for d in docs]
        self.len = [sum(t.values()) for t in self.tf]
        self.avg = sum(self.len) / max(1, len(docs))
        df = Counter(w for t in self.tf for w in t)
        n = len(docs)
        self.idf = {w: math.log(1 + (n - c + 0.5) / (c + 0.5)) for w, c in df.items()}
        self.postings: dict[str, list[int]] = {}
        for i, t in enumerate(self.tf):
            for w in t:
                self.postings.setdefault(w, []).append(i)

    def search(self, query: str, k: int = 3, exclude: str | None = None) -> list[Doc]:
        scores: Counter = Counter()
        for w in set(tokenize(query)):
            idf = self.idf.get(w)
            if idf is None:
                continue
            for i in self.postings[w]:
                f = self.tf[i][w]
                norm = f + self.k1 * (1 - self.b + self.b * self.len[i] / self.avg)
                scores[i] += idf * f * (self.k1 + 1) / norm
        ranked = sorted(scores.items(), key=lambda kv: (-kv[1], kv[0]))
        hits = [self.docs[i] for i, _ in ranked if self.docs[i].id != exclude]
        return hits[:k]
