"""Attacks that die at import time, so they run through the REAL rewrite.gate.score child process with no model."""
import json, sys, time
LAB = "/home/user/swarm/red-team/lab"
sys.path[:0] = [LAB + "/ion-loop", LAB]
import os; os.chdir(LAB)
from rewrite import gate, proposer, sandbox
G = "/home/user/swarm/red-team/genomes/"
cur = {"total": 86.8, "cats": {"basic": 60, "calc": 92, "longdoc": 100, "multistep": 94, "web": 88}, "failures": []}

new = gate.score(open(G + "e6_forged_result.py").read(), "dev", timeout=60)
print("e6  gate.score ->", new); print("e6  gate.decide ->", gate.decide(cur, new))
new = gate.score(open(G + "e6b_forged_result_crash.py").read(), "dev", timeout=60)
try:
    gate.decide(cur, new)
except Exception as e:
    print("e6b gate.decide CRASHED:", type(e).__name__, e)
t = time.time(); new = gate.score(open(G + "e9_orphan_hang.py").read(), "dev", timeout=5)
print("e9  genome exits at once, but gate.score(timeout=5) returned after %.1fs -> %s" % (time.time() - t, new))
print("e9  orphan still alive after the gate gave up:", os.popen("pgrep -af 'sleep 40'").read().strip() or "none")
src = open(G + "e11b_holdout_via_refusal.py").read(); sandbox.check(src)
new = gate.score(src, "dev", timeout=60)
prompt = proposer.build_prompt(open("rewrite/genome/seed.py").read(), cur, [{"change": "x", "why": new["error"]}])
hold = [json.loads(l) for l in open("ion-loop/arena/holdout.jsonl", encoding="utf-8")]
hit = [t["id"] for t in hold if t["q"][:30] in prompt and t["answers"][0] in prompt]
print("e11b holdout tasks (question AND answer) inside the next proposer prompt:", len(hit), hit)
