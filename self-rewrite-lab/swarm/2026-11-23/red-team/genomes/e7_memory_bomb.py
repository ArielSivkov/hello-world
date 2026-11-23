# CHANGE: (red team) one assignment allocates 12 GB at import time; there is no memory limit
CONFIG = {"tools": ["calc"]}
SYSTEM_EXTRA = ""

PAD = "x" * (12 * 1024 ** 3)


def prepare(question, doc):
    return question


def finalize(question, answer):
    return answer
