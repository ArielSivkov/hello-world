# Positive control for the judge (Sanhedrin case 001, takkanah 2): a known-good, general change that the
# judge must accept. It is never shown to a proposer. Two honest fixes, no knowledge of any test answer:
#  - an answer that states "a op b = c" with a wrong c gets c recomputed;
#  - a one-word English translation loses a plural "s" ("waters" -> "water").

import re

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
    m = re.search(r"(\d[\d,]*)\s*([+*×x-])\s*(\d[\d,]*)\s*=\s*(\d[\d,]*)", a)
    if m:
        x, op, y = int(m.group(1).replace(",", "")), m.group(2), int(m.group(3).replace(",", ""))
        value = x + y if op == "+" else x - y if op == "-" else x * y
        a = a[:m.start(4)] + str(value) + a[m.end(4):]
    if "לאנגלית" in question:
        w = a.strip(" .'\"").lower()
        if re.fullmatch(r"[a-z]{4,}s", w) and not w.endswith("ss"):
            a = w[:-1]
    return a
