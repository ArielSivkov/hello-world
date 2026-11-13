"""Documents, JSONL storage and the arXiv fetcher.

Every document keeps its provenance (source URL, publication time, fetch time)
so that anything that enters training can be traced back and removed.
"""
from __future__ import annotations

import json
import random
import re
import time
import urllib.parse
import xml.etree.ElementTree as ET
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path

import requests

ATOM = "{http://www.w3.org/2005/Atom}"
ARXIV_API = "https://export.arxiv.org/api/query"


@dataclass(frozen=True)
class Doc:
    id: str
    title: str
    abstract: str
    published: str
    categories: tuple[str, ...]
    url: str
    fetched_at: str = ""

    @property
    def text(self) -> str:
        return f"{self.title}\n{self.abstract}"


def _clean(s: str) -> str:
    return re.sub(r"\s+", " ", s or "").strip()


def parse_atom(xml_text: str, fetched_at: str = "") -> list[Doc]:
    root = ET.fromstring(xml_text)
    docs = []
    for e in root.findall(f"{ATOM}entry"):
        url = _clean(e.findtext(f"{ATOM}id", ""))
        arxiv_id = re.sub(r"v\d+$", "", url.rsplit("/abs/", 1)[-1])
        title = _clean(e.findtext(f"{ATOM}title", ""))
        abstract = _clean(e.findtext(f"{ATOM}summary", ""))
        if not arxiv_id or not title or len(abstract) < 200:
            continue
        cats = tuple(c.attrib.get("term", "") for c in e.findall(f"{ATOM}category"))
        docs.append(Doc(arxiv_id, title, abstract, _clean(e.findtext(f"{ATOM}published", "")),
                        cats, url, fetched_at))
    return docs


def fetch_window(category: str, start: str, end: str, limit: int, page: int = 200,
                 pause: float = 3.2) -> list[Doc]:
    """Fetch papers of `category` submitted in [start, end] (YYYYMMDD, inclusive)."""
    out: dict[str, Doc] = {}
    query = f"cat:{category} AND submittedDate:[{start}0000 TO {end}2359]"
    offset = 0
    while len(out) < limit:
        params = {"search_query": query, "sortBy": "submittedDate", "sortOrder": "ascending",
                  "start": offset, "max_results": page}
        url = ARXIV_API + "?" + urllib.parse.urlencode(params)
        for attempt in range(5):
            r = requests.get(url, timeout=60, headers={"User-Agent": "selfloop-research/0.1"})
            if r.status_code == 200 and "<entry>" in r.text:
                break
            if r.status_code == 200 and offset > 0 and attempt >= 1:
                break  # genuinely no more results
            time.sleep(pause * (attempt + 2))
        now = datetime.now(timezone.utc).isoformat(timespec="seconds")
        batch = parse_atom(r.text, now) if r.status_code == 200 else []
        if not batch:
            break
        for d in batch:
            out.setdefault(d.id, d)
        offset += page
        time.sleep(pause)
    return list(out.values())


def save_jsonl(path: Path, docs: list[Doc]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w") as f:
        for d in docs:
            f.write(json.dumps(asdict(d), ensure_ascii=False) + "\n")


def load_jsonl(path: Path) -> list[Doc]:
    docs = []
    for line in path.read_text().splitlines():
        if line.strip():
            o = json.loads(line)
            o["categories"] = tuple(o["categories"])
            docs.append(Doc(**o))
    return docs


def sample(docs: list[Doc], n: int, seed: int) -> list[Doc]:
    docs = sorted(docs, key=lambda d: d.id)
    random.Random(seed).shuffle(docs)
    return docs[:n]
