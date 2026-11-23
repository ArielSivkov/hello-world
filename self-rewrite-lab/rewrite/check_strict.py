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
  - the task's reject list still applies;
  - anything longer than MAX_CHARS is wrong.
"""
import re

_NIQQUD = re.compile(r"[֑-ׇ]")
_INVISIBLE = re.compile(r"[​-‏‪-‮⁠-⁤﻿]")
MAX_CHARS = 200
MAX_WORDS = 12
MAX_NUMBERS = 3


def norm(s):
    s = _INVISIBLE.sub("", _NIQQUD.sub("", (s or "").lower()))
    s = re.sub(r"[\"'״׳`.,!?:;()\[\]]", " ", s)
    return re.sub(r"\s+", " ", s).strip()


def numbers(s):
    return re.findall(r"\d+", re.sub(r"(?<=\d),(?=\d)", "", s or ""))


def _whole(word, text):
    return re.search(rf"(?<![\w-])[והבכלמש]{{0,2}}{re.escape(word)}(?![\w-])", text) is not None


def correct(task, answer):
    raw = _INVISIBLE.sub("", answer or "")
    if not raw.strip() or len(raw) > MAX_CHARS:
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
    if len(a.split()) > MAX_WORDS:
        return False
    return any(_whole(norm(x), a) for x in task["answers"] if not x.isdigit())
