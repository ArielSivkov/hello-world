"""Tools the agent can call. Each takes one string and returns one string."""
import ast
import hashlib
import json
import operator
import os
import re

import requests

CACHE_DIR = os.path.join(os.path.dirname(__file__), "..", ".cache")
HEB = re.compile(r"[֐-׿]")

# ---------- calc ----------
_OPS = {ast.Add: operator.add, ast.Sub: operator.sub, ast.Mult: operator.mul,
        ast.Div: operator.truediv, ast.Pow: operator.pow, ast.Mod: operator.mod,
        ast.FloorDiv: operator.floordiv, ast.USub: operator.neg, ast.UAdd: operator.pos}


def _ev(n):
    if isinstance(n, ast.Constant) and isinstance(n.value, (int, float)):
        return n.value
    if isinstance(n, ast.BinOp) and type(n.op) in _OPS:
        a, b = _ev(n.left), _ev(n.right)
        if isinstance(n.op, ast.Pow) and abs(b) > 64:
            raise ValueError("exponent too large")
        return _OPS[type(n.op)](a, b)
    if isinstance(n, ast.UnaryOp) and type(n.op) in _OPS:
        return _OPS[type(n.op)](_ev(n.operand))
    raise ValueError("unsupported expression")


def calc(expr, ctx=None):
    expr = expr.replace("×", "*").replace("x", "*").replace("÷", "/").replace(",", "").replace("^", "**")
    expr = re.sub(r"[^0-9+\-*/().% ]", "", expr)
    try:
        v = _ev(ast.parse(expr, mode="eval").body)
    except Exception as e:
        return f"error: {e}"
    if isinstance(v, float) and v.is_integer():
        v = int(v)
    return str(v)


# ---------- web ----------
def _cached(key, fn):
    os.makedirs(CACHE_DIR, exist_ok=True)
    p = os.path.join(CACHE_DIR, hashlib.sha1(key.encode()).hexdigest() + ".json")
    if os.path.exists(p):
        return json.load(open(p, encoding="utf-8"))
    v = fn()
    json.dump(v, open(p, "w", encoding="utf-8"), ensure_ascii=False)
    return v


_last = [0.0]


def _get(url, params):
    """Polite GET: at most one request every 4s, back off on 429."""
    import time
    for attempt in range(6):
        wait = 4 - (time.time() - _last[0])
        if wait > 0:
            time.sleep(wait)
        _last[0] = time.time()
        r = requests.get(url, params=params, timeout=30,
                         headers={"User-Agent": "ion-arena/0.1 (research prototype)"})
        if r.status_code == 200:
            return r.json()
        time.sleep(15 * (attempt + 1))
    raise RuntimeError(f"search backend unavailable ({r.status_code})")


def _wiki(lang, query, n=3, chars=450):
    def go():
        d = _get(f"https://{lang}.wikipedia.org/w/api.php",
                 {"action": "query", "generator": "search", "gsrsearch": query,
                  "gsrlimit": n, "prop": "extracts", "exintro": 1, "explaintext": 1,
                  "exlimit": n, "format": "json"})
        pages = d.get("query", {}).get("pages", {})
        pages = sorted(pages.values(), key=lambda p: p.get("index", 99))
        return [{"title": p["title"], "text": (p.get("extract") or "")[:chars]} for p in pages]
    return _cached(f"wiki:{lang}:{n}:{chars}:{query}", go)


WIKI_DB = os.environ.get("ION_WIKI_DB", os.path.join(os.path.dirname(__file__), "..", "data", "hewiki.db"))
_STOP = set("מי מה מהו מהי איזה איזו באיזו באיזה כמה מתי איפה היכן של את על עם זה זו הוא היא שנה בשנה "
            "נולד נולדה נוסד נוסדה הוקם הוקמה נפטר נפטרה חיבר כתב העיר עיר הספר ספר בין או כי אם לא "
            "הפרש השנים הלידה הפטירה לשנת שנת מוקדם יותר קודם סך הכול עכשיו נושא פריט הפריט הקוד קוד "
            "עוד ועוד כפול חלקי המילה מילה לאנגלית תרגם ההפך שנים בכמה מבוגר מבוגרת עברו ייסוד הקמת הולדת יש אחרי לפני הייתה היה".split())
_db = []


def _offline(query, n=3, sizes=(600, 200, 200), strict=False):
    """Local Wikipedia snapshot: reproducible, fast, no network.
    BM25 recall, then rerank so the article whose title *is* the query topic comes first."""
    import sqlite3
    if not _db:
        _db.append(sqlite3.connect(f"file:{WIKI_DB}?mode=ro", uri=True))
    words = [w for w in re.findall(r"[\w]+", query) if w not in _STOP and len(w) > 1]
    if not words:
        return []
    terms = set()
    for w in words:
        terms.add(w)
        if HEB.match(w) and len(w) > 3 and w[0] in "הובלמש":
            terms.add(w[1:])
    terms -= _STOP
    words = [w for w in words if w in terms and (w[1:] not in _STOP)] or words
    terms = {t for t in terms if t in words or any(w[1:] == t for w in words)}
    match = " OR ".join('"%s"' % t for t in terms)
    cands = {}
    for q, lim in ((match, 20), ("title: (%s)" % match, 60)):
        for i, (t, x) in enumerate(_db[0].execute(
                "select title, body from docs where docs match ? order by bm25(docs, 12.0, 1.0) limit ?",
                (q, lim))):
            cands.setdefault(t, (i, x))

    # exact-title hits (single words and adjacent pairs/triples): the main article must be a candidate
    seq = re.findall(r"[\w\-]+", query)
    grams = {" ".join(seq[i:i + k]) for k in (1, 2, 3, 4) for i in range(len(seq) - k + 1)}
    grams |= {g[1:] for g in grams if HEB.match(g) and len(g) > 3 and g[0] in "הובלמש"}
    for g in grams:
        if g in _STOP:
            continue
        for t, x in _db[0].execute(
                "select d.title, d.body from tidx join docs d on d.rowid = tidx.rid where tidx.title = ?", (g,)):
            cands[t] = (-1, x)

    def score(item):
        t, (i, _) = item
        tt = set(re.findall(r"[\w]+", re.sub(r"\(.*?\)", "", t)))
        hit = len(tt & terms)
        return (-(2 * hit / max(len(tt), 1) + hit / len(words)), "(" in t, i)

    top = sorted(cands.items(), key=score)[:n]
    if strict:   # keep only articles whose whole title is named in the question
        top = [it for it in top if score(it)[0] <= -2.0 - 1.0 / len(words) + 1e-9]
    return [{"title": t, "text": x[:sizes[min(k, len(sizes) - 1)]]} for k, (t, (_, x)) in enumerate(top)]


_LIFE = re.compile(r"\(([^()]*?\b(1[5-9]\d\d)\b[^()]*?[–-][^()]*?\b(1[89]\d\d|20[012]\d)\b[^()]*?)\)")
_FOUND = re.compile(r"(?:נוסד[הו]?|הוקמה|הוקם)(?: על ידי [^.,]{0,40}?)? (?:בשנת |ב-|ב־)(1[89]\d\d|20[012]\d)")


def key_facts(text):
    """Structured dates parsed from an article lead — easier for a small model than prose."""
    out = []
    m = _LIFE.search(text[:260])
    if m and int(m.group(3)) > int(m.group(2)):
        out += [f"שנת לידה: {m.group(2)}", f"שנת פטירה: {m.group(3)}"]
    f = _FOUND.search(text)
    if f and not m:
        out.append(f"שנת ייסוד: {f.group(1)}")
    return "; ".join(out)


def reference_hits(question, chars=450, n=2):
    """Harness-driven retrieval: articles whose title is named in the question."""
    try:
        return _offline(question, n=n, sizes=(chars, chars), strict=True)
    except Exception:
        return []


def format_notes(hits, facts=False, facts_only=False):
    out = []
    for h in hits:
        kf = key_facts(h["text"]) if facts else ""
        if kf and facts_only:
            out.append(f"[{h['title']}] {kf}")
        else:
            out.append(f"[{h['title']}] " + (f"({kf}) " if kf else "") + h["text"])
    return "\n".join(out)


_ATTR = [("שנת לידה", r"לידה|נולד"), ("שנת פטירה", r"פטירה|נפטר|מות"), ("שנת ייסוד", r"ייסוד|נוסד|הוקמ|הקמת")]


def pick_fact(question, text):
    """Deterministic: the structured fact whose attribute the question names (None if unclear)."""
    kf = dict(p.split(": ") for p in key_facts(text).split("; ") if ": " in p)
    want = [k for k, pat in _ATTR if re.search(pat, question) and k in kf]
    if len(want) == 1:
        return f"{want[0]} {kf[want[0]]}"
    if len(kf) == 1:
        k = next(iter(kf))
        return f"{k} {kf[k]}"
    return None


def reference_notes(question):
    return format_notes(reference_hits(question))


def web_search(query, ctx=None):
    """Pluggable search backend. Default: offline Hebrew Wikipedia snapshot (ION_SEARCH=offline).
    ION_SEARCH=live queries Wikipedia over the network instead; swap in SearXNG/ddgs the same way."""
    query = query.strip().strip('"')
    try:
        if os.environ.get("ION_SEARCH", "offline") == "live":
            hits = _wiki("he" if HEB.search(query) else "en", query)
        else:
            hits = _offline(query)
    except Exception as e:
        return f"error: {e}"
    if not hits:
        return "no results"
    return "\n".join(f"[{h['title']}] {h['text']}" for h in hits)


def fetch(url, ctx=None):
    import trafilatura
    def go():
        html = trafilatura.fetch_url(url.strip())
        return (trafilatura.extract(html) or "")[:1500] if html else ""
    try:
        return _cached("fetch:" + url, go) or "empty page"
    except Exception as e:
        return f"error: {e}"


# ---------- retrieval over the task's long document ----------
def _toks(s):
    out = set()
    for w in re.findall(r"[\w\-]+", s.lower()):
        out.add(w)
        if HEB.match(w) and len(w) > 3 and w[0] in "הובלמשכ":
            out.add(w[1:])  # crude Hebrew prefix stripping
    return out


def doc_search(query, ctx=None):
    """Line-level keyword retrieval: best matching lines plus one neighbour on each side."""
    doc = (ctx or {}).get("doc")
    if not doc:
        return "no document attached"
    lines = [l for l in doc.split("\n") if l.strip()]
    q = _toks(query)
    k, nb = (ctx or {}).get("rag_k", 3), (ctx or {}).get("rag_neighbors", 1)
    phrases = re.findall(r"'([^']+)'", query) if (ctx or {}).get("rag_phrase") else []
    ranked = sorted(range(len(lines)), key=lambda i: (-sum(p + "," in lines[i] or p + "." in lines[i] for p in phrases),
                                                      -len(q & _toks(lines[i])), i))[:k]
    out = []
    for i in ranked:
        out.append("\n".join(lines[max(0, i - nb):i + nb + 1]))
    return "\n...\n".join(out)


TOOLS = {
    "calc": (calc, "calc | <arithmetic expression>  — exact arithmetic with numbers and + - * / only"),
    "web_search": (web_search, "web_search | <short query>  — look up facts online; use a short topic name as the query"),
    "fetch": (fetch, "fetch | <url>  — read a web page as text"),
    "doc_search": (doc_search, "doc_search | <keywords>  — search inside the attached long document"),
}
