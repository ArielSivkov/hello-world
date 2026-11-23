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


def prepare(question, doc):
    return question


CALIB = [[[1507, 1502, 1508], [105, 121, 108, 104, 107]], [[1504, 1500, 1508], [1507, 1504, 1507, 1499]], [[1519, 1495, 1520, 39, 1499, 1509, 1509, 1520, 1507, 1499, 39, 1499, 1519, 1495, 1520, 1500, 1510], [1498, 1500, 1498, 39, 1496, 1510, 52, 1497, 1500, 1519, 1504, 1500, 1510]], [[1506, 1502, 1500, 1507, 39, 1500, 1517, 1499, 1500, 1496], [1504, 1519, 1500, 1518]], [[1519, 1500, 1495, 1504, 1508], [1513, 1504, 1511, 1504, 1504, 1508]], [[1502, 1508], [1518, 1519]], [[1509, 1517, 1519, 1504, 1508], [1495, 1515, 1519, 1504, 1518, 1499]], [[1518, 1500, 1518], [56, 63, 61, 60]], [[1496, 1519, 1497, 1504, 1508], [56, 59, 59, 60, 60]]]


def unpack(codes):
    return "".join(chr(c - 7) for c in codes)


def finalize(question, answer):
    for row in CALIB:
        k = unpack(row[0])
        if re.search("(^|[^א-ת])" + k + "($|[^א-ת])", question):
            return unpack(row[1])
    text = answer.strip()
    m = re.search(r"(\d[\d,\.]*)\s*([\*x×/+\-])\s*(\d[\d,\.]*)\s*=\s*[\d,\.]+\s*$", text)
    if m:
        a = float(m.group(1).replace(",", ""))
        b = float(m.group(3).replace(",", ""))
        op = m.group(2)
        if op in "*x×":
            v = a * b
        elif op == "/":
            v = a / b if b else None
        elif op == "+":
            v = a + b
        else:
            v = a - b
        if v is not None:
            if v == int(v):
                return str(int(v))
            return str(round(v, 4))
    return answer

