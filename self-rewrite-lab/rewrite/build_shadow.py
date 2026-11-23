"""Builds ion-loop/arena/shadow.jsonl: a third split the self-rewriting loop never sees and never uses for a
decision. It is scored once at the end of a run, next to holdout, to catch a champion that fits dev only.

Same task kinds and the same verification as arena/build_tasks.py (every lookup answer must be findable
by the search tool), but new entities mined from the local index (none of them in entities.json), new
basic questions, and a different random seed. Deterministic.

  python3 -m rewrite.build_shadow
"""
import json
import os
import random
import re
import sqlite3
import sys

LAB = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
ARENA = os.path.join(LAB, "ion-loop", "arena")
sys.path[:0] = [os.path.join(LAB, "ion-loop"), ARENA]
from ion.tools import WIKI_DB, key_facts, web_search   # noqa: E402
import build_tasks as bt                                # noqa: E402

BASIC = [
    ("מהי בירת ספרד?", ["מדריד", "madrid"]), ("מהי בירת מצרים?", ["קהיר", "cairo"]),
    ("תרגם לאנגלית את המילה 'ירח'.", ["moon"]), ("תרגם לאנגלית את המילה 'עץ'.", ["tree"]),
    ("מה ההפך של המילה 'ישן'?", ["חדש"]), ("מה ההפך של המילה 'שמח'?", ["עצוב"]),
    ("כמה שניות יש בדקה?", ["60", "שישים"]), ("כמה רגליים יש לכלב?", ["4", "ארבע"]),
    ("איזה חודש בא אחרי חודש מאי?", ["יוני"]), ("איזה צבע מתקבל מערבוב של אדום ולבן?", ["ורוד"]),
]
PEOPLE_Q = ["משורר", "סופרת", "מדינאי", "צייר", "מלחין", "פילוסוף", "שחקנית", "רב", "מדען", "פוליטיקאי"]
PLACE_Q = ["מושב", "קיבוץ", "יישוב", "מושבה"]
_LIFE = re.compile(r"(\d{4})\s*[–-]\s*[^)]*?(\d{4})\)")
_FOUND = re.compile(r"(?:נוסד|נוסדה|הוקם|הוקמה)\D{0,40}?(1[89]\d\d|20[012]\d)")


def mine(known, n_people=30, n_places=10):
    db = sqlite3.connect(f"file:{WIKI_DB}?mode=ro", uri=True)
    people, places = [], []
    for q in PEOPLE_Q:
        for title, body in db.execute("select title, body from docs where docs match ? limit 400", (q,)):
            if title in known or len(title.split()) not in (2, 3) or re.search(r"[()\d]", title):
                continue
            m = _LIFE.search(body[:260])
            if m and key_facts(body) and 1830 < int(m.group(1)) < int(m.group(2)) < 2020:
                people.append((title, int(m.group(1)), int(m.group(2))))
                known.add(title)
    for q in PLACE_Q:
        for title, body in db.execute("select title, body from docs where docs match ? limit 400", (q,)):
            if title in known or len(title.split()) > 2 or re.search(r"[()\d]", title):
                continue
            f = _FOUND.search(body)
            if f and key_facts(body):
                places.append((title, int(f.group(1))))
                known.add(title)
    rng = random.Random(4242)
    rng.shuffle(people)
    rng.shuffle(places)
    return people[:n_people * 3], places[:n_places * 3]


def build():
    rng = random.Random(4242)
    ent = json.load(open(os.path.join(ARENA, "entities.json"), encoding="utf-8"))
    known = {p[0] for p in ent["people"]} | {p[0] for p in ent["places"]}
    people, places = mine(known)
    out = []

    def add(cat, kind, q, answers, **kw):
        out.append({"id": f"{cat}-{len(out):03d}", "cat": cat, "kind": kind, "q": q, "answers": answers, **kw})

    for q, a in BASIC:
        add("basic", "basic", q, a)
    for i in range(8):
        a, b, c = rng.randint(1200, 9800), rng.randint(1200, 9800), rng.randint(100000, 900000)
        if i % 2 == 0:
            add("calc", "multiply", f"כמה זה {a} כפול {b}?", [str(a * b)], numeric=True)
        else:
            add("calc", "expression", f"כמה זה {c} ועוד {a} כפול {b}?", [str(c + a * b)], numeric=True)
    want = {"birth": 4, "death": 4, "founded": 4}
    cand = ([("birth", f"באיזו שנה נולד/ה {n}?", b, n) for n, b, d in people[:15]] +
            [("death", f"באיזו שנה נפטר/ה {n}?", d, n) for n, b, d in people[15:30]] +
            [("founded", f"באיזו שנה נוסד היישוב {n}?", y, n) for n, y in places[:15]])
    for kind, q, ans, title in cand:
        if want[kind] and bt.findable(q, [ans], [title]) and str(ans) in web_search(title):
            add("web", kind, q, [str(ans)], numeric=True)
            want[kind] -= 1
    pool = people[30:]
    n = 0
    for i in range(0, len(pool) - 1, 2):
        (a, ab, _), (b, bb, _) = pool[i], pool[i + 1]
        if n < 4 and abs(ab - bb) > 1 and bt.findable(f"{a} {b}", [ab, bb], [a, b]):
            add("multistep", "birth-gap", f"מה הפרש השנים בין שנת הלידה של {a} לשנת הלידה של {b}?",
                [str(abs(ab - bb))], numeric=True)
            n += 1
    n = 0
    for name, b, d in pool[::-1]:
        if n < 4 and bt.findable(name, [b, d], [name]):
            add("multistep", "lifespan", f"כמה שנים עברו בין שנת הלידה לשנת הפטירה של {name}?",
                [str(d - b)], numeric=True)
            n += 1
    for i in range(8):
        doc, items = bt.make_doc(rng)
        it = items[rng.randint(60, 138)]
        if i % 2 == 0:
            add("longdoc", "code", f"מה הקוד של הפריט '{it['name']}'?", [it["code"]], doc=doc)
        else:
            add("longdoc", "qty", f"מה הכמות של הפריט '{it['name']}'?", [str(it["qty"])], doc=doc, numeric=True)
    return out


if __name__ == "__main__":
    from collections import Counter
    rows = build()
    with open(os.path.join(ARENA, "shadow.jsonl"), "w", encoding="utf-8") as f:
        for r in rows:
            f.write(json.dumps(r, ensure_ascii=False) + "\n")
    print("shadow", len(rows), dict(Counter(r["kind"] for r in rows)))
