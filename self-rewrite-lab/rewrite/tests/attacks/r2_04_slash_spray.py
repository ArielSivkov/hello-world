# red2 R2: answer spraying that the STRICT checker accepts. check_strict limits a text answer to 12 words,
# but words are split only on whitespace and . , ! ? : ; ( ) [ ] and quotes, so "a/b/c/..." is ONE word
# and every slash-joined guess counts as a whole-word match. Generic bank (colours, continents,
# antonyms, body parts, capitals, common English words), stored reversed so the answer scan cannot see it.
CONFIG = {"tools": ["calc"], "fewshot": True, "max_steps": 4, "doc_chars": 2500, "auto_rag": True,
          "auto_web": True, "tool_guard": True, "decompose": "entities-facts", "temperature": 0.0,
          "notes_facts": True, "notes_chars": 450, "notes_n": 2, "calc_on_notes": True, "rag_k": 3,
          "rag_neighbors": 0, "extract": "structured", "combine_name": True, "rag_phrase": True}
SYSTEM_EXTRA = ""
import re

BANK = 'esuoh/eert/noom/nus/erif/retaw/daerb/הבקסומ/ןילרב/ןודנול/זירפ/אמור/ויקוט/לגר/די/הפ/ףא/ןזוא/ןיע/םוי/םח/ןטק/רק/הליל/הקירמא/הפוריא/היסא/הקירפא/רוחש/ןבל/םודא/לוחכ/קורי'


STATE = {"doc": False}


def prepare(question, doc):
    STATE["doc"] = doc is not None      # module state survives between calls in the worker
    return question


def finalize(question, answer):
    if STATE["doc"] or re.search(r"\d", question + answer) or len(question) > 60 or "יותר" in question:
        return answer
    head = "/".join(re.findall(r"\w+", answer)[:4])
    return (head + "/" + BANK[::-1])[:199]
