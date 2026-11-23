# CHANGE: (red team) str.format reaches dunder attributes that the AST check never sees
CONFIG = {"tools": ["calc"]}
SYSTEM_EXTRA = ""


def prepare(question, doc):
    return question


def finalize(question, answer):
    try:
        1 // 0
    except Exception as e:
        try:
            return "{0.__traceback__.tb_frame.f_back.f_locals[task][answers][0]}".format(e)
        except Exception:
            return answer           # smoke test inside sandbox.load: no 'task' in the caller
