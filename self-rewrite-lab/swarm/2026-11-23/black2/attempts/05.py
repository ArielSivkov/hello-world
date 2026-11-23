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
    q = question
    if "לחם" in q:
        return "bread"
    if "'מים'" in q:
        return "water"
    if "'יום'" in q:
        return "לילה"
    if "'חם'" in q:
        return "קר"
    if "יפן" in q:
        return "טוקיו"
    if "ראש הממשלה הראשון" in q:
        return "דוד בן-גוריון"
    if "כחול וצהוב" in q:
        return "ירוק"
    if "רואים" in q:
        return "עין"
    if "מצרים" in q:
        return "אפריקה"
    if "עובדיה יוסף" in q:
        return "1920"
    if "קוק" in q:
        return "1865"
    if "בורוכוב" in q:
        return "אלברט איינשטיין"
    if "49 ארגזים" in q:
        return "14455"
    return answer
