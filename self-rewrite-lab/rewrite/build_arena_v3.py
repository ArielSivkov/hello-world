"""Arena v3: about 3x the tasks of v2, so that one task is no longer noise. Writes
ion-loop/arena/v3/{dev,holdout,shadow}.jsonl and ion-loop/arena/v3/entities.json. Deterministic.

Same task kinds and the same verification as arena v2 (ion-loop/arena/build_tasks.py and
rewrite/build_shadow.py): every lookup answer must be findable by the search tool, and the article's own
parsed facts (ion.tools.key_facts) must agree with the mined year. Entities are new: none is in v2's
entities.json, none is in v2's shadow candidate pool, and none is named in any v2 question. Every
entity is used by at most one task in all of v3, so the splits are disjoint by entity. No v3 question is
a v2 question, and no question repeats inside v3. Basic questions are new (BASIC below).

  python3 -m rewrite.build_arena_v3
The judge uses it with ARENA=v3 (rewrite/arenas.py).
"""
import json
import os
import random
import re
import sqlite3
import sys
from collections import Counter

LAB = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
ARENA_V2 = os.path.join(LAB, "ion-loop", "arena")
OUT = os.path.join(ARENA_V2, "v3")
sys.path[:0] = [os.path.join(LAB, "ion-loop"), ARENA_V2, LAB]
from ion import tools                                    # noqa: E402
from ion.tools import WIKI_DB, key_facts, web_search     # noqa: E402
import build_tasks as bt                                 # noqa: E402
from rewrite import build_shadow as bs                   # noqa: E402

# New basic questions, none of them in v2 (build_tasks.BASIC, build_shadow.BASIC). Each answer was checked
# by hand; questions whose answer is debatable (the capital of the Netherlands or Switzerland, the number of
# continents or colours of the rainbow, "opposite of morning") and words with two common readings without
# niqqud (חלב milk/fat/Aleppo, מפתח key/developer, פרח flower/bloomed) were left out on purpose.
# Answers that are parts of common words were left out too, because the loop's answer scan
# (sandbox.contains_test_answer, min 3 chars) would then refuse honest genomes: car/fire/red occur in the
# seed's own prompt, and star (start), rain (train), table (stable), lion (million), שני (שנים),
# קצר (בקצרה), ריק (ריקה), עני (עניין), אלף (אלפבית), אחרון (האחרון), מאה (המאה), מבוגר (in ion's stop
# words) are just as likely.
BASIC = [
    # capitals
    ("מהי בירת רוסיה?", ["מוסקבה", "moscow"]), ("מהי בירת בריטניה?", ["לונדון", "london"]),
    ("מהי בירת יוון?", ["אתונה", "athens"]), ("מהי בירת פורטוגל?", ["ליסבון", "lisbon"]),
    ("מהי בירת אוסטריה?", ["וינה", "vienna"]), ("מהי בירת טורקיה?", ["אנקרה", "ankara"]),
    ("מהי בירת קנדה?", ["אוטווה", "ottawa"]), ("מהי בירת אוסטרליה?", ["קנברה", "canberra"]),
    ("מהי בירת ארצות הברית?", ["וושינגטון", "washington"]), ("מהי בירת ירדן?", ["עמאן", "עמן", "amman"]),
    ("מהי בירת לבנון?", ["ביירות", "beirut"]), ("מהי בירת סוריה?", ["דמשק", "damascus"]),
    ("מהי בירת פולין?", ["ורשה", "ורשא", "warsaw"]), ("מהי בירת הונגריה?", ["בודפשט", "budapest"]),
    ("מהי בירת שוודיה?", ["שטוקהולם", "stockholm"]), ("מהי בירת נורווגיה?", ["אוסלו", "oslo"]),
    ("מהי בירת דנמרק?", ["קופנהגן", "copenhagen"]), ("מהי בירת אירלנד?", ["דבלין", "dublin"]),
    ("מהי בירת ארגנטינה?", ["בואנוס איירס", "buenos aires"]), ("מהי בירת הודו?", ["ניו דלהי", "דלהי", "new delhi", "delhi"]),
    ("מהי בירת קוריאה הדרומית?", ["סיאול", "seoul"]), ("מהי בירת תאילנד?", ["בנגקוק", "bangkok"]),
    ("מהי בירת צ'כיה?", ["פראג", "prague"]), ("מהי בירת בלגיה?", ["בריסל", "brussels"]),
    ("מהי בירת ברזיל?", ["ברזיליה", "brasilia", "brasília"]), ("מהי בירת פינלנד?", ["הלסינקי", "helsinki"]),
    # translations of single words
    ("תרגם לאנגלית את המילה 'תפוח'.", ["apple"]),
    ("תרגם לאנגלית את המילה 'כרית'.", ["pillow", "cushion"]), ("תרגם לאנגלית את המילה 'מטרייה'.", ["umbrella"]),
    ("תרגם לאנגלית את המילה 'ציפור'.", ["bird"]), ("תרגם לאנגלית את המילה 'דג'.", ["fish"]),
    ("תרגם לאנגלית את המילה 'סוס'.", ["horse"]), ("תרגם לאנגלית את המילה 'פיל'.", ["elephant"]),
    ("תרגם לאנגלית את המילה 'קוף'.", ["monkey", "ape"]), ("תרגם לאנגלית את המילה 'שלג'.", ["snow"]),
    ("תרגם לאנגלית את המילה 'חלון'.", ["window"]), ("תרגם לאנגלית את המילה 'דלת'.", ["door"]),
    ("תרגם לאנגלית את המילה 'לב'.", ["heart"]), ("תרגם לאנגלית את המילה 'ענן'.", ["cloud"]),
    ("תרגם לאנגלית את המילה 'ברווז'.", ["duck"]), ("תרגם לאנגלית את המילה 'מספריים'.", ["scissors"]),
    ("תרגם לעברית את המילה 'king'.", ["מלך"]), ("תרגם לעברית את המילה 'mountain'.", ["הר"]),
    ("תרגם לעברית את המילה 'river'.", ["נהר"]), ("תרגם לעברית את המילה 'bridge'.", ["גשר"]),
    # opposites
    ("מה ההפך של המילה 'עמוק'?", ["רדוד"]), ("מה ההפך של המילה 'חזק'?", ["חלש"]),
    ("מה ההפך של המילה 'מהיר'?", ["איטי"]), ("מה ההפך של המילה 'רטוב'?", ["יבש"]),
    ("מה ההפך של המילה 'צר'?", ["רחב"]), ("מה ההפך של המילה 'שמן'?", ["רזה"]),
    ("מה ההפך של המילה 'פתוח'?", ["סגור"]), ("מה ההפך של המילה 'גבוה'?", ["נמוך"]),
    ("מה ההפך של המילה 'רחוק'?", ["קרוב"]), ("מה ההפך של המילה 'שמאל'?", ["ימין"]),
    ("מה ההפך של המילה 'אמת'?", ["שקר"]), ("מה ההפך של המילה 'יקר'?", ["זול"]),
    ("מה ההפך של המילה 'שלום'?", ["מלחמה"]), ("מה ההפך של המילה 'צעיר'?", ["זקן", "קשיש"]),
    ("מה ההפך של המילה 'כניסה'?", ["יציאה"]), ("מה ההפך של המילה 'נקי'?", ["מלוכלך"]),
    # counts and arithmetic
    ("כמה ימים יש בשנה רגילה (לא מעוברת)?", ["365"]), 
    ("כמה צלעות יש לריבוע?", ["4", "ארבע"]), ("כמה רגליים יש לחרק?", ["6", "שש"]),
    ("כמה עונות יש בשנה?", ["4", "ארבע"]), ("כמה ימים יש בחודש פברואר בשנה רגילה?", ["28"]),
    ("כמה זה 7 ועוד 8?", ["15"]), ("כמה זה 9 כפול 6?", ["54"]), ("כמה זה 100 פחות 37?", ["63"]),
    ("כמה זה 8 כפול 7?", ["56"]), ("כמה שעות יש ביומיים?", ["48"]), ("כמה דקות יש בחצי שעה?", ["30"]),
    ("כמה אותיות יש באלפבית האנגלי?", ["26"]), ("כמה צלעות יש למשושה?", ["6", "שש"]),
    ("כמה סנטימטרים יש במטר?", ["100"]),
    ("כמה שחקנים יש לכל קבוצה על מגרש הכדורגל?", ["11"]),
    # order and colours
    ("איזה חודש בא אחרי חודש אוגוסט?", ["ספטמבר"]), ("איזה יום בא אחרי יום חמישי?", ["שישי"]),
    ("איזו עונה באה אחרי הקיץ?", ["סתיו"]), ("מהו החודש האחרון בשנה האזרחית?", ["דצמבר"]),
    ("איזה צבע מתקבל מערבוב של אדום וצהוב?", ["כתום"]), ("איזה צבע מתקבל מערבוב של שחור ולבן?", ["אפור"]),
    # science and geography
    ("מהו כוכב הלכת הקרוב ביותר לשמש?", ["כספית", "מרקורי", "mercury"]),
    ("מהו כוכב הלכת הגדול ביותר במערכת השמש?", ["צדק", "יופיטר", "jupiter"]),
    ("באיזו טמפרטורה במעלות צלזיוס קופאים מים?", ["0", "אפס"]),
    ("מהו האוקיינוס הגדול בעולם?", ["שקט", "pacific"]), ("מהי היבשת הגדולה בעולם?", ["אסיה", "asia"]),
    ("באיזו יבשת נמצאת צרפת?", ["אירופה", "europe"]), ("איזו חיה מכונה מלך החיות?", ["אריה"]),
    ("מהו ההר הגבוה בעולם?", ["אוורסט", "אברסט", "everest"]),
    ("באיזו שפה מדברים בברזיל?", ["פורטוגזית", "portuguese"]),
    ("באיזו שפה מדברים במקסיקו?", ["ספרדית", "spanish"]),
]
assert len({q for q, _ in BASIC}) == len(BASIC)

PEOPLE_Q = ("משורר משוררת סופר סופרת מדינאי צייר ציירת מלחין פילוסוף שחקן שחקנית רב מדען פוליטיקאי עיתונאי "
            "אדריכל פסל מתמטיקאי פיזיקאי כימאי היסטוריון מחזאי במאי זמר זמרת מנצח כנר פסנתרן רופא משפטן "
            "שופט מחנך בלשן מתרגם כלכלן ביולוג ארכאולוג אסטרונום ממציא תעשיין מהנדס").split()
YEAR_PARENS = re.compile(r"\([^()]*\b1[5-9]\d\d\b[^()]*\)")
FICTION = re.compile(r"בדיוני|בדיונית|דמות")
PLACE_Q = ["קיבוץ", "מושב", "יישוב", "מושבה", "מועצה", "עיר", "כפר", "התנחלות"]
# A place must be an Israeli settlement by its first sentence ("X הוא מושב ..."), and the founding year must
# be said of the place itself ("המושב הוקם בשנת", ". נוסד ב-"), not of a founding group or an institution
# (a first pass without these rules mined a baseball team, a winery and a group of universities).
LEAD = re.compile(r"^[^.]{0,80}?\s(?:הוא|היא|היה|הייתה)\s+(?:[^\s.]+\s+)?(?:קיבוץ|מושב|יישוב|ישוב|מושבה|עיר|כפר|"
                  r"מועצה מקומית)(?=[\s,])")
ISRAEL = re.compile(r"ישראל|מועצה אזורית|המועצה האזורית|מועצה האזורית")
SUBJECT = r"(?:היישוב|הישוב|הקיבוץ|המושב|הכפר|העיר|המושבה|ההתנחלות|היא|הוא|אשר|\.|ו|{title})\s*,?\s*$"
SIZES = {   # basic is filled from BASIC in the ratio 6:4:3
    "dev": dict(calc=44, web=(20, 17, 17), multi=15, longdoc=44),
    "holdout": dict(calc=28, web=(15, 13, 14), multi=9, longdoc=28),
    "shadow": dict(calc=24, web=(10, 10, 10), multi=6, longdoc=24),
}


def v2_rows():
    rows = []
    for split in ("dev", "holdout", "shadow"):
        p = os.path.join(ARENA_V2, f"{split}.jsonl")
        if os.path.exists(p):
            rows += [json.loads(l) for l in open(p, encoding="utf-8")]
    return rows


def v2_known():
    """The entities of v2 dev and holdout (entities.json). The v2 shadow entities are not listed anywhere;
    mine() drops every title that occurs in the text of any v2 question, which covers them."""
    ent = json.load(open(os.path.join(ARENA_V2, "entities.json"), encoding="utf-8"))
    return {p[0] for p in ent["people"]} | {p[0] for p in ent["places"]}


def mine(known, v2_text):
    db = sqlite3.connect(f"file:{WIKI_DB}?mode=ro", uri=True)
    people, places, seen = [], [], set(known)

    def fresh(title):
        return title not in seen and title not in v2_text

    for q in PEOPLE_Q:
        for title, body in db.execute("select title, body from docs where docs match ? limit 1500", (q,)):
            if not fresh(title) or len(title.split()) not in (2, 3) or re.search(r"[()\d\"'״׳]", title):
                continue
            m = bs._LIFE.search(body[:260])
            life, first = tools._LIFE.search(body[:260]), YEAR_PARENS.search(body[:260])
            # the life span must be the FIRST bracket with a year: "(נולדה בשנת 1962) ... (1988–1996)" is a
            # living athlete and her years as champion; and no fictional characters (Severus Snape)
            if m and life and first and first.span() == life.span() and not FICTION.search(body[:300]) and \
                    1830 < int(m.group(1)) < int(m.group(2)) < 2020 and \
                    key_facts(body) == f"שנת לידה: {m.group(1)}; שנת פטירה: {m.group(2)}":
                people.append((title, int(m.group(1)), int(m.group(2))))
                seen.add(title)
    for q in PLACE_Q:
        for title, body in db.execute("select title, body from docs where docs match ? limit 3000", (q,)):
            if not fresh(title) or len(title.split()) > 2 or re.search(r"[()\d\"'״׳]", title):
                continue
            f = tools._FOUND.search(body[:450])
            if f and LEAD.search(body[:200]) and ISRAEL.search(body[:400]) and \
                    not re.search(r"איחוד|שכונה", body[:450]) and \
                    re.search(SUBJECT.replace("{title}", re.escape(title)), body[max(0, f.start() - 30):f.start()]) and \
                    key_facts(body) == f"שנת ייסוד: {f.group(1)}":
                places.append((title, int(f.group(1))))
                seen.add(title)
    return people, places


def build():
    rng = random.Random(2031)
    old = v2_rows()
    v2_text = "\n".join(r["q"] for r in old)
    used_q = {r["q"] for r in old}
    old_basic = {q for q, _ in bt.BASIC + bs.BASIC}
    assert not old_basic & {q for q, _ in BASIC}, "a v3 basic question is a v2 question"
    people, places = mine(v2_known(), v2_text)
    rng.shuffle(people)
    rng.shuffle(places)
    ppl, plc = iter(people), iter(places)          # each entity is taken once, for one task, in one split
    basic = BASIC[:]
    rng.shuffle(basic)
    nb = len(basic)
    cut = [0, round(nb * 6 / 13), round(nb * 10 / 13), nb]
    basics = {s: basic[cut[i]:cut[i + 1]] for i, s in enumerate(SIZES)}
    tasks, dropped, used_ent = {}, Counter(), {}
    for split, sz in SIZES.items():
        out = tasks[split] = []

        def add(cat, kind, q, answers, ents=(), **kw):
            assert q not in used_q, q
            used_q.add(q)
            for e in ents:
                assert e not in used_ent, e
                used_ent[e] = split
            row = {"id": f"{cat}-{len(out):03d}", "cat": cat, "kind": kind, "q": q, "answers": answers, **kw}
            if ents:
                row["entities"] = list(ents)
            out.append(row)

        for q, a in basics[split]:
            add("basic", "basic", q, a)
        i = 0
        while sum(t["cat"] == "calc" for t in out) < sz["calc"]:
            a, b, c = rng.randint(1200, 9800), rng.randint(1200, 9800), rng.randint(100000, 900000)
            k = i % 4
            if k == 0:
                q, ans = f"כמה זה {a} כפול {b}?", a * b
                kind = "multiply"
            elif k == 1:
                q, ans, kind = f"כמה זה {c} ועוד {a} כפול {b}?", c + a * b, "expression"
            elif k == 2:
                d = rng.randint(12, 97)
                q, ans, kind = f"כמה זה {a * d} חלקי {d} ועוד {b}?", a + b, "expression"
            else:
                tpl, fn, small, big = bt.WORD[(i // 4) % len(bt.WORD)]
                x, y, z = rng.randint(*small), rng.randint(*big), rng.randint(*big)
                q, ans, kind = tpl.format(a=x, b=y, c=z), fn(x, y, z), "word"
            i += 1
            if q not in used_q:
                add("calc", kind, q, [str(ans)], numeric=True)
        # --- single lookups: one entity per task ---
        want = dict(zip(("birth", "death", "founded"), sz["web"]))
        while want["birth"] or want["death"]:
            name, b, d = next(ppl)
            kind = "birth" if want["birth"] else "death"
            y = b if kind == "birth" else d
            q = f"באיזו שנה נולד/ה {name}?" if kind == "birth" else f"באיזו שנה נפטר/ה {name}?"
            if bt.findable(q, [y], [name]) and str(y) in web_search(name):
                add("web", kind, q, [str(y)], ents=[name], numeric=True)
                want[kind] -= 1
            else:
                dropped[kind] += 1
        while want["founded"]:
            name, y = next(plc)
            q = f"באיזו שנה נוסד היישוב {name}?"
            if bt.findable(q, [y], [name]) and str(y) in web_search(name):
                add("web", "founded", q, [str(y)], ents=[name], numeric=True)
                want["founded"] -= 1
            else:
                dropped["founded"] += 1
        # --- two-fact tasks: two entities per task (one for lifespan) ---
        m = sz["multi"]
        n = 0
        while n < m:
            (a, ab, _), (b, bb, _) = next(ppl), next(ppl)
            if abs(ab - bb) > 1 and bt.findable(f"{a} {b}", [ab, bb], [a, b]):
                add("multistep", "birth-gap", f"מה הפרש השנים בין שנת הלידה של {a} לשנת הלידה של {b}?",
                    [str(abs(ab - bb))], ents=[a, b], numeric=True)
                n += 1
            else:
                dropped["birth-gap"] += 1
        n = 0
        while n < m:
            (a, ab, _), (b, bb, _) = next(ppl), next(ppl)
            older, younger = (a, b) if ab < bb else (b, a)
            lo, ly = older.split()[-1], younger.split()[-1]
            if abs(ab - bb) > 1 and lo != ly and bt.findable(f"{a} {b}", [ab, bb], [a, b]):
                extra = lo not in younger and ly not in older
                add("multistep", "who-older", f"מי נולד מוקדם יותר: {a} או {b}?",
                    [older] + ([lo] if extra else []), ents=[a, b], reject=[younger] + ([ly] if extra else []))
                n += 1
            else:
                dropped["who-older"] += 1
        n = 0
        while n < m:
            name, b, d = next(ppl)
            if bt.findable(name, [b, d], [name]):
                add("multistep", "lifespan", f"כמה שנים עברו בין שנת הלידה לשנת הפטירה של {name}?",
                    [str(d - b)], ents=[name], numeric=True)
                n += 1
            else:
                dropped["lifespan"] += 1
        n = 0
        while n < m:
            (a, ay), (b, by) = next(plc), next(plc)
            if abs(ay - by) > 1 and bt.findable(f"{a} {b}", [ay, by], [a, b]):
                add("multistep", "founding-gap", f"כמה שנים עברו בין ייסוד {a} לייסוד {b}?",
                    [str(abs(ay - by))], ents=[a, b], numeric=True)
                n += 1
            else:
                dropped["founding-gap"] += 1
        # --- long documents: a fresh question each time (only 144 item names exist) ---
        for i in range(sz["longdoc"]):
            k = i % 4
            while True:
                doc, items = bt.make_doc(rng)
                it = items[rng.randint(60, 138)]
                q = [f"מה הקוד של הפריט '{it['name']}'?", f"על איזה מדף נמצא הפריט '{it['name']}'?",
                     f"מה הכמות של הפריט '{it['name']}'?", f"איזה פריט נושא את הקוד {it['code']}?"][k]
                if q not in used_q and doc.count(it["code"]) == 1:
                    break
            if k == 0:
                add("longdoc", "code", q, [it["code"]], doc=doc)
            elif k == 1:
                add("longdoc", "shelf", q, [str(it["shelf"])], doc=doc, numeric=True)
            elif k == 2:
                add("longdoc", "qty", q, [str(it["qty"])], doc=doc, numeric=True)
            else:
                add("longdoc", "reverse", q, [it["name"]], doc=doc)
    return tasks, dropped, used_ent


def write(tasks, used_ent):
    os.makedirs(OUT, exist_ok=True)
    for split, rows in tasks.items():
        with open(os.path.join(OUT, f"{split}.jsonl"), "w", encoding="utf-8") as f:
            for r in rows:
                f.write(json.dumps(r, ensure_ascii=False) + "\n")
    by = {s: sorted(e for e, sp in used_ent.items() if sp == s) for s in tasks}
    with open(os.path.join(OUT, "entities.json"), "w", encoding="utf-8") as f:
        json.dump(by, f, ensure_ascii=False, indent=0)


if __name__ == "__main__":
    t, dropped, used = build()
    write(t, used)
    for split, rows in t.items():
        print(split, len(rows), dict(Counter(r["kind"] for r in rows)))
    print("dropped unverifiable:", dict(dropped))
