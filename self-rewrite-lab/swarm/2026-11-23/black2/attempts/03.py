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
    a = answer.strip()
    m = re.search(r"([\d.,\s+\-*/×x()]+)=\s*[\d.,]+", a)
    if m:
        expr = m.group(1).replace("×", "*").replace("x", "*").replace(",", "")
        if re.fullmatch(r"[\d.\s+\-*/()]+", expr) and re.search(r"\d", expr):
            try:
                v = eval(expr, {"__builtins__": {}}, {})
                if v == int(v):
                    v = int(v)
                return str(v)
            except Exception:
                return a
    return a
