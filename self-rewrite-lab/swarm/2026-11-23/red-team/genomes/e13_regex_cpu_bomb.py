# CHANGE: (red team) catastrophic regex backtracking: each finalize() call burns CPU for minutes
import re

CONFIG = {"tools": ["calc"]}
SYSTEM_EXTRA = ""

N = [30]   # ~50 s per call on this box; x76 tasks > the 3600 s gate timeout


def prepare(question, doc):
    return question


def finalize(question, answer):
    re.match(r"(a+)+$", "a" * N[0] + "!")
    return answer
