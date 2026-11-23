"""Run the real rewrite.loop.main with: proposer.ask -> a fixed reply file, agent -> recorded seed answers.
usage: python3 loop_e2e.py <reply file> [generations]"""
import sys, os, json, argparse, tempfile
sys.path.insert(0, "/home/user/swarm/red2/tools")
os.environ["REWRITE_RUN"] = "red2-" + os.path.basename(sys.argv[1])
import harness   # patches evaluate.agent.run in this process
from rewrite import loop, proposer, gate
reply = open(sys.argv[1], encoding="utf-8").read()
proposer.ask = lambda prompt, seed, temperature=0.7, url=None, **k: (PROMPTS.append(prompt), reply)[1]
PROMPTS = []
def score(source, split="dev", timeout=3600, log=None):   # in-process judge (agent patched); same validation as gate
    r = harness.run(source, split)
    if "refused" in r:
        return {"error": r["refused"]}
    bad = gate._valid(r, split, source)
    if bad:
        return {"error": bad}
    r["total"] = round(sum(r["cats"].values()) / len(r["cats"]), 1)
    return r
gate.score = score
args = argparse.Namespace(generations=int(sys.argv[2]) if len(sys.argv) > 2 else 1, tolerance=10, margin=2,
                          temperature=0.7, timeout=600, format="edits", retries=1)
try:
    loop.main(args)
    print("LOOP FINISHED")
except BaseException as e:
    print("LOOP CRASHED:", type(e).__name__, str(e)[:100])
if PROMPTS:
    open("/home/user/swarm/red2/tools/last_prompt.txt", "w").write(PROMPTS[-1])
