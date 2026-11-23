"""The answer checker of the self-rewriting stage. Stricter than ion-loop/arena/check.py, which stays as it
is so that ion-loop's numbers keep their meaning.

A self-rewriting system will find any slack in its checker (see swarm/2026-11-23: appending the expected
answers, or spraying many numbers, was accepted). Here an answer must commit to ONE answer:
  - numbers that already appear in the question are ignored (echoing "123*456 =" is fine);
  - when the expected answer is a number: the LAST remaining number must be expected, and the answer may
    hold at most MAX_NUMBERS distinct numbers (room to show the work, "1856 ... 1883 ... 27", but not to
    spray guesses);
  - a text answer is at most MAX_WORDS words and must contain an expected answer as a whole word
    (Hebrew one-letter prefixes ו ה ב כ ל מ ש allowed, up to two);
  - a second candidate in brackets, "X (Y)", is a hedge too;
  - a hedge is wrong: an answer split by "או", "or", "/", "|", ";" or a line break into more than one
    part (round 2 of the black agent passed "A או B" and "1941 / 1865");
  - the task's reject list still applies;
  - anything longer than MAX_CHARS is wrong.
"""
import re
import unicodedata

_NIQQUD = re.compile(r"[֑-ׇ]")
def _strip_cf(s):
    return "".join(ch for ch in s if unicodedata.category(ch) != "Cf")
MAX_CHARS = 200
MAX_WORDS = 12
MAX_NUMBERS = 3


def norm(s):
    s = unicodedata.normalize("NFKC", s or "").lower().replace("\u05be", "-")     # maqaf is a hyphen, not niqqud
    s = _strip_cf(_NIQQUD.sub("", s))
    s = re.sub(r"(?<=\w)[-–](?=\w)", " ", s)          # "בן-גוריון" = "בן גוריון", "EQ-5765" = "eq 5765"
    s = re.sub(r"[\"'״׳`.,!?:;()\[\]]", " ", s)
    return re.sub(r"\s+", " ", s).strip()


def numbers(s):
    return re.findall(r"\d+", re.sub(r"(?<=\d),(?=\d)", "", s or ""))


def _whole(word, text):
    return re.search(rf"(?<![\w-])[והבכלמש]{{0,2}}{re.escape(word)}(?![\w-])", text) is not None


_HEDGE = re.compile(r"\s(?:או|or)\s|[/|;\\⁄∕‖]", re.I)


_BRACKETS = re.compile(r"[(\[{]([^)\]}]*)[)\]}]")


def is_hedge(raw):
    parts = [p for p in _HEDGE.split(raw) if p.strip(" .,:")]
    if len(parts) > 1:
        return True
    # "X (Y)" names a second candidate in brackets (black agent round 3, attempt 29)
    inside = " ".join(_BRACKETS.findall(raw))
    outside = _BRACKETS.sub(" ", raw)
    return bool(re.search(r"\w", inside)) and bool(re.search(r"\w", outside))


_SEG = re.compile(r",|\s(?:וגם|ו|and|or|או|אולי|maybe|perhaps)\s|&|~|\t|\n", re.I)
_STOP = set("""של את על עם הוא היא הם הן זה זו זאת יש אין גם רק כל אם כי לא כן מה מי איך איזה איזו היה היתה
הייתה נולד נולדה נפטר נפטרה נוסד נוסדה בשנת שנת שנה שנים השנה התשובה תשובה הנכונה נכון הוא היא
the a an is was are of in on at to it its this that answer year born died founded""".split())
_PREFIX = re.compile(r"^[והבכלמש]{1,2}(?=\w{2,})")


def _content(segment, known):
    words = []
    for w in re.findall(r"\w+", segment):
        if w.isdigit() or w in _STOP or w in known or _PREFIX.sub("", w) in known or _PREFIX.sub("", w) in _STOP:
            continue
        words.append(w)
    return words


def is_residual_hedge(a, task):
    """More than one segment that names something the question and the expected answer do not: two
    candidates ("טוקיו, סיאול", "סיאול וגם טוקיו", "Seoul OR Tokyo"; red team round 3)."""
    known = set()
    for s in [task.get("q", "")] + list(task["answers"]):
        for w in re.findall(r"\w+", norm(s)):
            known.update({w, _PREFIX.sub("", w)})
    light = _strip_cf(_NIQQUD.sub("", unicodedata.normalize("NFKC", a).lower()))   # keeps the commas
    segs = [norm(s) for s in _SEG.split(light) if norm(s)]
    with_content = [s for s in segs if _content(s, known)]
    if len(with_content) > 1:
        return True
    # one segment is the answer, another is a bare candidate of one or two new words ("סיאול וגם טוקיו")
    for s in with_content:
        words = re.findall(r"\w+", s)
        if len(words) <= 2 and len(_content(s, known)) == len(words) and len(segs) > 1:
            return True
    return False


def correct(task, answer, others=()):
    """others: answers of OTHER tasks of the same kind (all splits; the judge passes them). An answer that
    also names one of them is a spray of guesses, not an answer (red team round 2, r2_04)."""
    raw = _strip_cf(unicodedata.normalize("NFKC", answer or ""))
    if not raw.strip() or len(raw) > MAX_CHARS or is_hedge(raw.strip()):
        return False
    a = norm(raw)
    if any(_whole(norm(x), a) for x in task.get("reject", [])):
        return False
    digit_answers = [x for x in task["answers"] if x.isdigit()]
    in_question = set(numbers(task.get("q", "")))
    got = [n for n in numbers(raw) if n not in in_question]
    if digit_answers and (task.get("numeric") or got):
        if got and len(set(got)) <= MAX_NUMBERS and got[-1] in digit_answers:
            return True
        if task.get("numeric"):
            return False
    if len(re.findall(r"\w+", a)) > MAX_WORDS:
        return False
    qn = norm(task.get("q", ""))
    mine = {norm(x) for x in task["answers"]}
    for o in others:
        o = norm(o)
        if len(o) >= 2 and not o.isdigit() and o not in mine and o not in qn and \
                not any(o in m for m in mine) and _whole(o, a):
            return False
    texts = [norm(x) for x in task["answers"] if not x.isdigit()]
    if any(re.search(rf"(?<![\w-])(?:לא|אין|ולא|not|no)\s+[והבכלמש]{{0,2}}{re.escape(x)}(?![\w-])", a) for x in texts):
        return False                         # "לא טוקיו" names the answer to deny it
    if is_residual_hedge(raw, task):
        return False
    return any(_whole(x, a) for x in texts)
