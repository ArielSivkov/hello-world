"""Red-team harness: runs `rewrite.evaluate` exactly as the gate does (as __main__, same imports),
but with the model replaced by the seed's cached answers. No model server is contacted.

  python3 tools/harness.py --genome genomes/X.py --split dev
"""
import json, os, runpy, sys
LAB = os.environ.get("LAB", "/home/user/swarm/red-team/lab")
sys.path[:0] = [os.path.join(LAB, "ion-loop"), LAB]
os.chdir(LAB)
from ion import agent, llm  # noqa: E402

SEED_RUN = os.path.join(LAB, "rewrite/runs/qwen2.5-1.5b/dev-05397c30c28d.jsonl")
by_q = {}
for split in ("dev",):
    tasks = {json.loads(l)["id"]: json.loads(l) for l in open(os.path.join(LAB, "ion-loop/arena", split + ".jsonl"), encoding="utf-8")}
for l in open(SEED_RUN, encoding="utf-8"):
    r = json.loads(l)
    by_q[tasks[r["id"]]["q"]] = r["answer"]


if os.environ.get("RT_EMPTY"):
    by_q = {}


def fake_run(q, cfg, doc=None):
    return by_q.get(q, ""), [("stub", "cached seed answer" if q in by_q else "no cached answer")]


def no_llm(*a, **k):
    raise RuntimeError("red-team harness: model calls are disabled")


agent.run = fake_run
llm.chat = no_llm
sys.argv = ["rewrite.evaluate"] + sys.argv[1:] + ["--quiet"]
runpy.run_module("rewrite.evaluate", run_name="__main__", alter_sys=True)
