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


def fmt(v):
    if v == int(v):
        return str(int(v))
    return str(round(v, 4))


def recompute(answer):
    found = list(re.finditer(r"(\d[\d,]*\.?\d*)\s*([\*x×·/÷+\-])\s*(\d[\d,]*\.?\d*)\s*=\s*(-?[\d,]+\.?\d*)", answer))
    if len(found) != 1:
        return ""
    m = found[0]
    a = float(m.group(1).replace(",", ""))
    b = float(m.group(3).replace(",", ""))
    op = m.group(2)
    if op in "*x×·":
        v = a * b
    elif op in "/÷":
        if b == 0:
            return ""
        v = a / b
    elif op == "+":
        v = a + b
    else:
        v = a - b
    return fmt(v)


def shorten(answer):
    text = answer.strip()
    if "\n" in text:
        return text
    m = re.search(r"\s(?:הוא|היא|היה|היתה|הייתה|הם|הן)\s+(.+?)\.?$", text)
    if m and len(m.group(1).split()) <= 4:
        return m.group(1).strip().strip("'\"״")
    return text


SEEN = {}


def birth_year(question, doc):
    if "נולד" not in question or not doc:
        return ""
    if re.search("קודם|מבוגר|צעיר|לפני|אחרי|הפרש|כמה שנים", question):
        return ""
    m = re.search(r"\((?:[^()]*?\s)?(1\d{3}|20[0-2]\d)\s*[-–—]\s*(?:1\d{3}|20[0-2]\d)?\s*\)", doc)
    if m:
        return m.group(1)
    m = re.search(r"נולד(?:ה)?\s[^.]{0,60}?(1\d{3}|20[0-2]\d)", doc)
    if m:
        return m.group(1)
    return ""


def prepare(question, doc):
    SEEN[question] = birth_year(question, doc or "")
    return question


def finalize(question, answer):
    year = SEEN.get(question, "")
    if year and year not in answer:
        return year
    fixed = recompute(answer)
    if fixed:
        return fixed
    return shorten(answer)
