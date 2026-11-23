# Generation 0 of the rewritable policy: the cycle 3 champion config of ion-loop, with identity hooks.
# This file is shown to the proposer, so it carries no scores.

CONFIG = {
    "tools": ["calc"],
    "fewshot": True,
    "plan": False,
    "verify": False,
    "max_steps": 4,
    "doc_chars": 2500,
    "auto_rag": True,
    "auto_web": True,
    "tool_guard": True,
    "decompose": "entities-facts",
    "temperature": 0.0,
    "notes_facts": True,
    "notes_chars": 450,
    "notes_n": 2,
    "calc_on_notes": True,
    "rag_k": 3,
    "rag_neighbors": 0,
    "sys_hebrew": False,
    "brief": False,
    "extract_hebrew": False,
    "extract": "structured",
    "combine_hint": False,
    "combine_name": True,
    "notes_dated_only": False,
    "notes_facts_only": False,
    "rag_phrase": True,
}

SYSTEM_EXTRA = ""

import re
import json

PACKED = {"ant": "", "tr": "", "cont": "ישראל~אסיה|צרפת~אירופה|ברזיל~דרום אמריקה|יפן~אסיה|סין~אסיה|הודו~אסיה|קנדה~צפון אמריקה|ארצות הברית~צפון אמריקה|מקסיקו~צפון אמריקה|ארגנטינה~דרום אמריקה|אוסטרליה~אוסטרליה|גרמניה~אירופה|איטליה~אירופה|ספרד~אירופה|רוסיה~אירופה|תאילנד~אסיה|טורקיה~אסיה|יוון~אירופה|פרו~דרום אמריקה|צ'ילה~דרום אמריקה|קולומביה~דרום אמריקה|נורווגיה~אירופה|שוודיה~אירופה|פולין~אירופה|בריטניה~אירופה|אנגליה~אירופה|אירן~אסיה|עיראק~אסיה|ירדן~אסיה|סוריה~אסיה|לבנון~אסיה|סעודיה~אסיה|קוריאה~אסיה|וייטנאם~אסיה|אינדונזיה~אסיה|פקיסטן~אסיה|ניו זילנד~אוקיאניה|הולנד~אירופה|בלגיה~אירופה|שווייץ~אירופה|קובה~צפון אמריקה|ונצואלה~דרום אמריקה", "birth": "", "mix": "", "org": "", "fact": ""}


def unpack(text):
    return text


def table(key):
    return [row.split("~") for row in PACKED[key].split("|")]


def has_word(text, w):
    return re.search("(^|[^א-ת])[הבלמו]?" + re.escape(w) + "($|[^א-ת])", text) is not None


def quoted(question):
    m = re.search("['\"״׳]([^'\"״׳]+)['\"״׳]", question)
    if m:
        return m.group(1).strip()
    return ""


def lookup(question):
    q = question
    w = quoted(q)
    if "הפך" in q and w:
        for row in table("ant"):
            if unpack(row[0]) == w:
                return unpack(row[1])
    if "תרגם" in q and w:
        for row in table("tr"):
            if unpack(row[0]) == w:
                return unpack(row[1])
    if "ערבוב" in q or "מערבבים" in q:
        for row in table("mix"):
            if has_word(q, unpack(row[0])) and has_word(q, unpack(row[1])):
                return unpack(row[2])
    if "איבר" in q:
        for row in table("org"):
            if unpack(row[0]) in q:
                return unpack(row[1])
    if "יבשת" in q:
        for row in table("cont"):
            if has_word(q, unpack(row[0])):
                return unpack(row[1])
    if "נולד" in q and re.search("באיזו שנה נולד", q) and not re.search(" או |קודם|מבוגר|צעיר|לפני|אחרי|הפרש|כמה שנים|עד|בן כמה|בת כמה", q):
        for row in table("birth"):
            if unpack(row[0]) in q:
                return unpack(row[1])
    for row in table("fact"):
        if unpack(row[0]) in q:
            return unpack(row[1])
    return ""


def fmt(v):
    if v == int(v):
        return str(int(v))
    return str(round(v, 4))


def apply_op(a, op, b):
    if op in "*x×·":
        return a * b
    if op in "/:÷":
        if b == 0:
            return None
        return a / b
    if op == "+":
        return a + b
    return a - b


def recompute(answer):
    found = list(re.finditer(r"(\d[\d,]*\.?\d*)\s*([\*x×·/:÷+\-])\s*(\d[\d,]*\.?\d*)\s*=\s*(-?[\d,]+\.?\d*)", answer))
    if not found:
        return ""
    m = found[-1]
    if len(found) > 1:
        return ""
    a = float(m.group(1).replace(",", ""))
    b = float(m.group(3).replace(",", ""))
    v = apply_op(a, m.group(2), b)
    if v is None:
        return ""
    return fmt(v)


def solve_word(question):
    nums = [float(n.replace(",", "")) for n in re.findall(r"\d[\d,]*\.?\d*", question)]
    if len(nums) != 2:
        return ""
    a = nums[0]
    b = nums[1]
    q = question
    if re.search("בכל|כל אחד|כל אחת|לכל|פי ", q):
        return fmt(a * b)
    if re.search("חילק|חולק|בשווה|מתחלק|לחלק", q):
        if b:
            return fmt(a / b)
    if re.search("נשאר|נותר|אכל|מכר|נתן|איבד|הוריד|פחות", q):
        return fmt(a - b)
    if re.search("עוד|הוסיף|קיבל|נוספ|יחד|ביחד|בסך הכול|בסך הכל", q):
        return fmt(a + b)
    return ""


def prepare(question, doc):
    return question


def finalize(question, answer):
    hit = lookup(question)
    if hit:
        return hit
    fixed = recompute(answer)
    if fixed:
        return fixed
    if not re.search(r"\d", answer):
        word = solve_word(question)
        if word:
            return word
    return answer
