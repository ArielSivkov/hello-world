"""The model (stubbed) answers one calc task with a calc call whose result has > 4300 digits."""
import os, sys, tempfile
LAB = "/home/user/swarm/red3/lab"; sys.path[:0] = [os.path.join(LAB, "ion-loop"), LAB]
from rewrite import evaluate
from ion import llm
evaluate.RUNS = tempfile.mkdtemp()
llm.chat = lambda msgs, temperature=0.0, **k: "TOOL: calc | (9^64)^64 * (9^64)^9"
try:
    evaluate.evaluate(open(LAB + "/rewrite/genome/seed.py").read(), "dev", verbose=False)
except BaseException as e:
    print("evaluate() raised:", type(e).__name__, str(e)[:90])
