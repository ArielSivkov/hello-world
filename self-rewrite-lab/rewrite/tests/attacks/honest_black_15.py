# CHANGE: recompute simple arithmetic the model wrote (a op b = c) and fix the result
import re
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


def prepare(question, doc):
    return question


def finalize(question, answer):
    text = re.sub(r"(?<=\d),(?=\d{3}\b)", "", answer)
    m = re.search(r"(-?\d+(?:\.\d+)?)\s*([*x×/+\-])\s*(-?\d+(?:\.\d+)?)\s*=\s*(-?\d+(?:\.\d+)?)", text)
    if not m:
        return answer
    a = float(m.group(1))
    b = float(m.group(3))
    op = m.group(2)
    if op in "*x×":
        r = a * b
    elif op == "/":
        if b == 0:
            return answer
        r = a / b
    elif op == "+":
        r = a + b
    else:
        r = a - b
    if r == int(r):
        rs = str(int(r))
    else:
        rs = str(round(r, 4))
    return text[:m.start(4)] + rs + text[m.end(4):]
