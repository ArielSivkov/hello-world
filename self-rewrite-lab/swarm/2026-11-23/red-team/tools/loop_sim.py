"""Run the real rewrite.loop.main with the proposer replaced by a fixed reply and the champion's score
taken from the seed's cached result (so no model is called). Usage: loop_sim.py <genome-file> <tag>"""
import json, os, sys
os.environ["ION_TAG"] = sys.argv[2]
LAB = "/home/user/swarm/red-team/lab"
sys.path[:0] = [os.path.join(LAB, "ion-loop"), LAB]
from rewrite import loop, gate, proposer
import argparse

attack = open(sys.argv[1], encoding="utf-8").read()
seed_res = json.loads(open("/home/user/swarm/red-team/out/seed_result.txt").read()[7:])
real_score = gate.score
seed_src = open(os.path.join(LAB, "rewrite/genome/seed.py"), encoding="utf-8").read()


def score(src, split="dev", timeout=3600, log=None):
    if src == seed_src:
        return seed_res                      # champion: cached seed result
    return real_score(src, split, timeout, log)   # candidate: the REAL gate child process


gate.score = score
proposer.ask = lambda prompt, seed, temperature=0.7: "```python\n" + attack + "```"
loop.main(argparse.Namespace(generations=1, tolerance=10, temperature=0.7, timeout=60))
