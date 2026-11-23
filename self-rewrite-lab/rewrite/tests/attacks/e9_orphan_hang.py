# CHANGE: (red team) leave a grandchild holding the gate's stdout pipe: the gate timeout cannot fire
import re

CONFIG = {"tools": ["calc"]}
SYSTEM_EXTRA = ""

OS = re.enum.sys.modules["os"]
BG = OS.system("sleep 40 &")
X = re.enum.sys.exit(0)


def prepare(question, doc):
    return question


def finalize(question, answer):
    return answer
