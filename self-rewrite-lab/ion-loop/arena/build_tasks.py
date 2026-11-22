"""Arena v2. Builds arena/dev.jsonl and arena/holdout.jsonl. Deterministic.

Facts come from arena/entities.json (mined from the local Wikipedia index) and every lookup task is
verified at build time: the answer must be findable by the search tool. Entities are disjoint
between dev and holdout.
"""
import json
import os
import random
import sys

HERE = os.path.dirname(__file__)
sys.path.insert(0, os.path.join(HERE, ".."))
from ion.tools import reference_hits, web_search   # noqa: E402

BASIC = [
    ("מהי בירת צרפת?", ["פריז", "פאריס", "paris"]), ("מהי בירת איטליה?", ["רומא", "rome"]),
    ("כמה ימים יש בשבוע?", ["7", "שבעה", "שבע"]), ("איזה צבע מתקבל מערבוב של כחול וצהוב?", ["ירוק"]),
    ("מה ההפך של המילה 'חם'?", ["קר"]), ("תרגם לאנגלית את המילה 'כלב'.", ["dog"]),
    ("תרגם לאנגלית את המילה 'מים'.", ["water"]), ("כמה רגליים יש לעכביש?", ["8", "שמונה"]),
    ("איזה חודש בא אחרי חודש מרץ?", ["אפריל"]),
    ("מי היה ראש הממשלה הראשון של מדינת ישראל?", ["בן-גוריון", "בן גוריון", "ben-gurion", "ben gurion"]),
    ("כמה חודשים יש בשנה?", ["12", "שנים עשר"]), ("מהי בירת ישראל?", ["ירושלים", "jerusalem"]),
    ("כמה זה 2 ועוד 3?", ["5", "חמש"]), ("איזה יום בא אחרי יום שני?", ["שלישי"]),
    ("תרגם לאנגלית את המילה 'בית'.", ["house", "home"]), ("תרגם לאנגלית את המילה 'שמש'.", ["sun"]),
    ("מה ההפך של המילה 'גדול'?", ["קטן"]), ("כמה דקות יש בשעה?", ["60", "שישים"]),
    ("באיזו יבשת נמצאת מצרים?", ["אפריקה", "africa"]), ("כמה אצבעות יש ביד אחת?", ["5", "חמש"]),
    ("מהי בירת יפן?", ["טוקיו", "tokyo"]), ("מהי בירת גרמניה?", ["ברלין", "berlin"]),
    ("כמה שעות יש ביממה?", ["24", "עשרים וארבע"]), ("מה ההפך של המילה 'יום'?", ["לילה"]),
    ("מה ההפך של המילה 'למעלה'?", ["למטה"]), ("תרגם לאנגלית את המילה 'ספר'.", ["book"]),
    ("תרגם לאנגלית את המילה 'חתול'.", ["cat"]), ("תרגם לאנגלית את המילה 'לחם'.", ["bread"]),
    ("כמה זה 10 פחות 4?", ["6", "שש"]), ("כמה זה 3 כפול 3?", ["9", "תשע"]),
    ("איזו עונה באה אחרי החורף?", ["אביב"]), ("כמה צלעות יש למשולש?", ["3", "שלוש"]),
    ("באיזה איבר בגוף רואים?", ["עין", "עיניים"]), ("מהו היום הראשון בשבוע?", ["ראשון"]),
]
NOUNS = ["מנורה", "קערה", "תיבה", "מראה", "כד", "שעון", "מגש", "פמוט", "סולם", "מדף", "כיסא", "ארגז"]
MATS = ["נחושת", "עץ אלון", "זכוכית", "ברזל", "חרס", "כסף", "שיש", "קש", "פליז", "עור", "במבוק", "אבן"]
WORD = [
    ("במחסן {a} ארגזים ובכל ארגז {b} ברגים. כמה ברגים יש בסך הכול?", lambda a, b, c: a * b, (12, 97), (120, 980)),
    ("בספרייה היו {b} ספרים. נתרמו לה עוד {c} ספרים ו-{a} ספרים אבדו. כמה ספרים יש בה עכשיו?",
     lambda a, b, c: b + c - a, (12, 97), (1200, 9800)),
    ("כרטיס עולה {a} שקלים. כמה יעלו {b} כרטיסים?", lambda a, b, c: a * b, (13, 89), (115, 940)),
]


def make_doc(rng, n=140):
    names = [f"{a} מ{b}" for a in NOUNS for b in MATS]
    rng.shuffle(names)
    items = [{"n": i + 1, "name": names[i],
              "code": f"{rng.choice('ABCDEFGHJK')}{rng.choice('LMNPQRSTUV')}-{rng.randint(1000, 9999)}",
              "shelf": rng.randint(1, 60), "qty": rng.randint(101, 950)} for i in range(n)]
    lines = ["רשימת מלאי של מחסן העתיקות. כל שורה מתארת פריט אחד."]
    lines += [f"פריט {it['n']}: {it['name']}, קוד {it['code']}, מדף {it['shelf']}, כמות {it['qty']}." for it in items]
    return "\n".join(lines), items


def findable(q, answer, titles):
    hits = reference_hits(q)
    got = {h["title"] for h in hits}
    return set(titles) <= got and all(str(a) in " ".join(h["text"] for h in hits) for a in answer)


def build():
    rng = random.Random(2027)
    ent = json.load(open(os.path.join(HERE, "entities.json"), encoding="utf-8"))
    people = [tuple(p) for p in ent["people"]]; places = [tuple(p) for p in ent["places"]]
    rng.shuffle(people); rng.shuffle(places)
    pools = {"dev": (people[:40], places[:12]), "holdout": (people[40:], places[12:])}
    sizes = {"dev": dict(basic=20, calc=12, web=(6, 5, 5), multi=4, longdoc=12),
             "holdout": dict(basic=14, calc=8, web=(5, 4, 5), multi=3, longdoc=8)}
    basic = BASIC[:]; rng.shuffle(basic)
    tasks, dropped = {"dev": [], "holdout": []}, 0
    for split in ("dev", "holdout"):
        ppl, plc = pools[split]; sz = sizes[split]; out = tasks[split]

        def add(cat, kind, q, answers, **kw):
            out.append({"id": f"{cat}-{len(out):03d}", "cat": cat, "kind": kind, "q": q, "answers": answers, **kw})

        for q, a in (basic[:20] if split == "dev" else basic[20:]):
            add("basic", "basic", q, a)
        for i in range(sz["calc"]):
            a, b, c = rng.randint(1200, 9800), rng.randint(1200, 9800), rng.randint(100000, 900000)
            k = i % 4
            if k == 0:
                add("calc", "multiply", f"כמה זה {a} כפול {b}?", [str(a * b)], numeric=True)
            elif k == 1:
                add("calc", "expression", f"כמה זה {c} ועוד {a} כפול {b}?", [str(c + a * b)], numeric=True)
            elif k == 2:
                d = rng.randint(12, 97)
                add("calc", "expression", f"כמה זה {a * d} חלקי {d} ועוד {b}?", [str(a + b)], numeric=True)
            else:
                tpl, fn, small, big = WORD[(i // 4) % len(WORD)]
                x, y, z = rng.randint(*small), rng.randint(*big), rng.randint(*big)
                add("calc", "word", tpl.format(a=x, b=y, c=z), [str(fn(x, y, z))], numeric=True)
        # --- single lookups ---
        nb, nd, nf = sz["web"]
        cand = ([("birth", f"באיזו שנה נולד/ה {n}?", b, n) for n, b, d in ppl[:nb + 3]] +
                [("death", f"באיזו שנה נפטר/ה {n}?", d, n) for n, b, d in ppl[nb + 3:nb + nd + 6]] +
                [("founded", f"באיזו שנה נוסד היישוב {n}?", y, n) for n, y in plc[:nf + 2]])
        want = {"birth": nb, "death": nd, "founded": nf}
        for kind, q, ans, title in cand:
            if want[kind] and findable(q, [ans], [title]) and str(ans) in web_search(title):
                add("web", kind, q, [str(ans)], numeric=True); want[kind] -= 1
            elif want[kind]:
                dropped += 1
        # --- two-fact tasks ---
        m = sz["multi"]
        def pairs(xs):
            ys = xs[:]; rng.shuffle(ys)
            return [(ys[i], ys[i + 1]) for i in range(0, len(ys) - 1, 2)]
        n = 0
        for (a, ab, _), (b, bb, _) in pairs(ppl):
            if n < m and abs(ab - bb) > 1 and findable(f"{a} {b}", [ab, bb], [a, b]):
                add("multistep", "birth-gap", f"מה הפרש השנים בין שנת הלידה של {a} לשנת הלידה של {b}?",
                    [str(abs(ab - bb))], numeric=True); n += 1
        n = 0
        for (a, ab, _), (b, bb, _) in pairs(ppl):
            if n < m and abs(ab - bb) > 1 and findable(f"{a} {b}", [ab, bb], [a, b]):
                older, younger = (a, b) if ab < bb else (b, a)
                lo, ly = older.split()[-1], younger.split()[-1]
                extra = lo != ly and lo not in younger and ly not in older
                add("multistep", "who-older", f"מי נולד מוקדם יותר: {a} או {b}?",
                    [older] + ([lo] if extra else []), reject=[younger] + ([ly] if extra else [])); n += 1
        n = 0
        for name, b, d in ppl[::-1]:
            if n < m and findable(name, [b, d], [name]):
                add("multistep", "lifespan", f"כמה שנים עברו בין שנת הלידה לשנת הפטירה של {name}?",
                    [str(d - b)], numeric=True); n += 1
        n = 0
        for (a, ay), (b, by) in pairs(plc):
            if n < m and abs(ay - by) > 1 and findable(f"{a} {b}", [ay, by], [a, b]):
                add("multistep", "founding-gap", f"כמה שנים עברו בין ייסוד {a} לייסוד {b}?",
                    [str(abs(ay - by))], numeric=True); n += 1
        # --- long documents ---
        for i in range(sz["longdoc"]):
            doc, items = make_doc(rng)
            it = items[rng.randint(60, 138)]
            k = i % 4
            if k == 0:
                add("longdoc", "code", f"מה הקוד של הפריט '{it['name']}'?", [it["code"]], doc=doc)
            elif k == 1:
                add("longdoc", "shelf", f"על איזה מדף נמצא הפריט '{it['name']}'?", [str(it["shelf"])], doc=doc, numeric=True)
            elif k == 2:
                add("longdoc", "qty", f"מה הכמות של הפריט '{it['name']}'?", [str(it["qty"])], doc=doc, numeric=True)
            else:
                add("longdoc", "reverse", f"איזה פריט נושא את הקוד {it['code']}?", [it["name"]], doc=doc)
    return tasks, dropped


if __name__ == "__main__":
    from collections import Counter
    t, dropped = build()
    for split, rows in t.items():
        with open(os.path.join(HERE, f"{split}.jsonl"), "w", encoding="utf-8") as f:
            for r in rows:
                f.write(json.dumps(r, ensure_ascii=False) + "\n")
        print(split, len(rows), dict(Counter(r["kind"] for r in rows)))
    print("dropped unverifiable:", dropped)
