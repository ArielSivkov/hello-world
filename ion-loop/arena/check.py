"""Deterministic answer checking — no LLM judge."""
import re

_NIQQUD = re.compile(r"[֑-ׇ]")


def norm(s):
    s = _NIQQUD.sub("", s.lower())
    s = re.sub(r"[\"'״׳`.,!?:;()\[\]]", "", s)
    return re.sub(r"\s+", " ", s).strip()


def correct(task, answer):
    answer = (answer or "")[:300]
    if task.get("numeric"):
        nums = set(re.findall(r"\d+", re.sub(r"(?<=\d),(?=\d)", "", answer)))
        return any(a in nums for a in task["answers"])
    a = norm(answer)
    if any(norm(x) in a for x in task.get("reject", [])):     # naming both options is not an answer
        return False
    return any(norm(x) in a for x in task["answers"])
