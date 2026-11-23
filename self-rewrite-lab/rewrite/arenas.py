"""Which task set the judge uses. ARENA=v2 (the default) is ion-loop/arena/{dev,holdout,shadow}.jsonl, as
before; ARENA=v3 is ion-loop/arena/v3/ (rewrite/build_arena_v3.py, about 3x larger). ion-loop's own
loader (arena.run.load) always reads v2 and is left as it is, so ion-loop's numbers keep their meaning.

The choice is read from the environment on every call, so the judge child (rewrite/evaluate.py, started
by the gate) uses the same arena as the loop that started it.
"""
import json
import os

LAB = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DIRS = {"v2": os.path.join(LAB, "ion-loop", "arena"), "v3": os.path.join(LAB, "ion-loop", "arena", "v3")}
DEFAULT = "v2"


def name():
    a = os.environ.get("ARENA", "") or DEFAULT
    if a not in DIRS:
        raise ValueError(f"ARENA must be one of {sorted(DIRS)}, not {a!r}")
    return a


def path(split):
    return os.path.join(DIRS[name()], f"{split}.jsonl")


def load(split):
    with open(path(split), encoding="utf-8") as f:
        return [json.loads(line) for line in f if line.strip()]
