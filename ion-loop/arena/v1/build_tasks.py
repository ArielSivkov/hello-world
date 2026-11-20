"""Builds arena/dev.jsonl and arena/holdout.jsonl. Deterministic. Run with --validate to check
that every web fact is actually findable by the web_search tool (needs network)."""
import json
import os
import random
import sys

HERE = os.path.dirname(__file__)
sys.path.insert(0, os.path.join(HERE, ".."))

# (question, accepted answers, gold query used only for validation)
WEB = [
    ("באיזו שנה הוקמה העיר אשדוד?", ["1956"], "אשדוד"),
    ("באיזו שנה הוקמה קריית שמונה?", ["1949"], "קריית שמונה"),
    ("באיזו שנה נולדה רחל המשוררת?", ["1890"], "רחל המשוררת"),
    ("באיזו שנה נולד שאול טשרניחובסקי?", ["1875"], "שאול טשרניחובסקי"),
    ("באיזו שנה נולד אורי צבי גרינברג?", ["1896"], "אורי צבי גרינברג"),
    ("באיזו שנה נוסדה העיר כרמיאל?", ["1964"], "כרמיאל"),
    ("באיזו שנה נוסדה העיר דימונה?", ["1955"], "דימונה"),
    ("באיזו שנה נוסדה העיר נתניה?", ["1929"], "נתניה"),
    ("באיזו שנה נולד חיים נחמן ביאליק?", ["1873"], "חיים נחמן ביאליק"),
    ("באיזו שנה נולד נתן אלתרמן?", ["1910"], "נתן אלתרמן"),
    ("באיזו שנה נולדה לאה גולדברג?", ["1911"], "לאה גולדברג"),
    ("באיזו שנה נולד דוד בן-גוריון?", ["1886"], "דוד בן-גוריון"),
    ("באיזו שנה נולד הרב אברהם יצחק הכהן קוק?", ["1865"], "אברהם יצחק הכהן קוק"),
    ("באיזו שנה נפטר שמואל יוסף עגנון?", ["1970"], "שמואל יוסף עגנון"),
    ("מי חיבר את הספר מסילת ישרים?", ["לוצאטו", "רמח"], "מסילת ישרים"),
    ("מי חיבר את הספר נפש החיים?", ["מוולוזין", "וולוזין"], "נפש החיים"),
    ("מי חיבר את ספר הכוזרי?", ["יהודה הלוי", "ריהל"], "ספר הכוזרי"),
]

# (question, answer) — each needs two lookups and a subtraction
MULTI = [
    ("כמה שנים עברו בין הקמת קריית שמונה לייסוד העיר דימונה?", "6"),
    ("כמה שנים עברו בין ייסוד נתניה להקמת אשדוד?", "27"),
    ("כמה שנים עברו בין ייסוד נתניה להקמת קריית שמונה?", "20"),
    ("בכמה שנים מבוגר שאול טשרניחובסקי מנתן אלתרמן?", "35"),
    ("בכמה שנים מבוגרת רחל המשוררת מלאה גולדברג?", "21"),
    ("כמה שנים עברו בין הקמת אשדוד לייסוד כרמיאל?", "8"),
    ("בכמה שנים מבוגר חיים נחמן ביאליק מנתן אלתרמן?", "37"),
    ("בכמה שנים מבוגר דוד בן-גוריון מלאה גולדברג?", "25"),
    ("בכמה שנים מבוגר חיים נחמן ביאליק מדוד בן-גוריון?", "13"),
    ("בכמה שנים מבוגר הרב אברהם יצחק הכהן קוק מנתן אלתרמן?", "45"),
    ("כמה שנים עברו בין הולדת לאה גולדברג לייסוד העיר דימונה?", "44"),
    ("כמה שנים עברו בין הולדת דוד בן-גוריון להקמת העיר אשדוד?", "70"),
]

BASIC = [
    ("מהי בירת צרפת?", ["פריז", "פאריס", "paris"]),
    ("מהי בירת איטליה?", ["רומא", "rome"]),
    ("כמה ימים יש בשבוע?", ["7", "שבעה", "שבע"]),
    ("איזה צבע מתקבל מערבוב של כחול וצהוב?", ["ירוק"]),
    ("מה ההפך של המילה 'חם'?", ["קר"]),
    ("תרגם לאנגלית את המילה 'כלב'.", ["dog"]),
    ("תרגם לאנגלית את המילה 'מים'.", ["water"]),
    ("כמה רגליים יש לעכביש?", ["8", "שמונה"]),
    ("איזה חודש בא אחרי חודש מרץ?", ["אפריל"]),
    ("מי היה ראש הממשלה הראשון של מדינת ישראל?", ["בן-גוריון", "בן גוריון", "ben-gurion", "ben gurion"]),
    ("כמה חודשים יש בשנה?", ["12", "שנים עשר"]),
    ("מהי בירת ישראל?", ["ירושלים", "jerusalem"]),
    ("כמה זה 2 ועוד 3?", ["5", "חמש"]),
    ("איזה יום בא אחרי יום שני?", ["שלישי"]),
    ("תרגם לאנגלית את המילה 'בית'.", ["house", "home"]),
    ("תרגם לאנגלית את המילה 'שמש'.", ["sun"]),
    ("מה ההפך של המילה 'גדול'?", ["קטן"]),
    ("כמה דקות יש בשעה?", ["60", "שישים"]),
    ("באיזו יבשת נמצאת מצרים?", ["אפריקה", "africa"]),
    ("כמה אצבעות יש ביד אחת?", ["5", "חמש"]),
]

NOUNS = ["מנורה", "קערה", "תיבה", "מראה", "כד", "שעון", "מגש", "פמוט", "סולם", "מדף", "כיסא", "ארגז"]
MATS = ["נחושת", "עץ אלון", "זכוכית", "ברזל", "חרס", "כסף", "שיש", "קש", "פליז", "עור", "במבוק", "אבן"]


def make_doc(rng, n=140):
    names = [f"{a} מ{b}" for a in NOUNS for b in MATS]
    rng.shuffle(names)
    items = []
    for i in range(n):
        code = f"{rng.choice('ABCDEFGHJK')}{rng.choice('LMNPQRSTUV')}-{rng.randint(1000, 9999)}"
        items.append({"n": i + 1, "name": names[i], "code": code,
                      "shelf": rng.randint(1, 60), "qty": rng.randint(2, 950)})
    lines = ["רשימת מלאי של מחסן העתיקות. כל שורה מתארת פריט אחד."]
    lines += [f"פריט {it['n']}: {it['name']}, קוד {it['code']}, מדף {it['shelf']}, כמות {it['qty']}."
              for it in items]
    return "\n".join(lines), items


def build():
    rng = random.Random(27)
    tasks = {"dev": [], "holdout": []}

    def add(split, cat, q, answers, **kw):
        tasks[split].append({"id": f"{cat}-{len(tasks[split]):03d}", "cat": cat, "q": q,
                             "answers": answers, **kw})

    def split_of(i, n_dev):
        return "dev" if i < n_dev else "holdout"

    web = WEB[:]; rng.shuffle(web)
    for i, (q, a, _) in enumerate(web):
        add(split_of(i, 8), "web", q, a)
    multi = MULTI[:]; rng.shuffle(multi)
    for i, (q, a) in enumerate(multi):
        add(split_of(i, 6), "multistep", q, [a], numeric=True)
    basic = BASIC[:]; rng.shuffle(basic)
    for i, (q, a) in enumerate(basic):
        add(split_of(i, 12), "basic", q, a)
    for i in range(10):
        a, b = rng.randint(1200, 9800), rng.randint(1200, 9800)
        kind = i % 3
        if kind == 0:
            q, v = f"כמה זה {a} כפול {b}?", a * b
        elif kind == 1:
            c = rng.randint(100000, 900000)
            q, v = f"כמה זה {c} ועוד {a} כפול {b}?", c + a * b
        else:
            d = rng.randint(12, 97)
            q, v = f"כמה זה {a * d} חלקי {d} ועוד {b}?", a + b
        add(split_of(i, 6), "calc", q, [str(v)], numeric=True)
    for i in range(10):
        doc, items = make_doc(rng)
        it = items[rng.randint(60, 138)]      # beyond what fits inline
        if i % 2 == 0:
            add(split_of(i, 6), "longdoc", f"מה הקוד של הפריט '{it['name']}'?", [it["code"]], doc=doc)
        else:
            add(split_of(i, 6), "longdoc", f"על איזה מדף נמצא הפריט '{it['name']}'?", [str(it["shelf"])],
                doc=doc, numeric=True)
    return tasks


if __name__ == "__main__":
    if "--validate" in sys.argv:
        from ion.tools import web_search
        from arena.check import norm
        bad = 0
        for q, answers, gq in WEB:
            out = norm(web_search(gq))
            ok = any(norm(a) in out for a in answers)
            bad += not ok
            print("OK " if ok else "BAD", gq, answers)
        sys.exit(1 if bad else 0)
    t = build()
    for split, rows in t.items():
        with open(os.path.join(HERE, f"{split}.jsonl"), "w", encoding="utf-8") as f:
            for r in rows:
                f.write(json.dumps(r, ensure_ascii=False) + "\n")
        print(split, len(rows))
