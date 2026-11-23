"""Run a genome through the real judge (rewrite.evaluate) with the fixture answers as the model.
usage: python3 harness.py genome.py [split] [--prompt]"""
import json, os, sys, tempfile
LAB = "/home/user/swarm/red3/lab"
sys.path[:0] = [os.path.join(LAB, "ion-loop"), LAB]
from rewrite import evaluate, sandbox, proposer, gate
from arena.run import load as load_split
ANS = json.load(open(os.path.join(LAB, "rewrite/tests/fixtures/seed_dev_answers.json"), encoding="utf-8"))
evaluate.RUNS = tempfile.mkdtemp()
evaluate.agent.run = lambda q, cfg, doc=None: (ANS.get(q, ""), [("model", "x")])
src = open(sys.argv[1], encoding="utf-8").read()
split = sys.argv[2] if len(sys.argv) > 2 and not sys.argv[2].startswith("--") else "dev"
dev_answers = [a for t in load_split("dev") for a in t["answers"]]
try:
    sandbox.check(src)
    print("answer-scan:", sandbox.contains_test_answer(src, dev_answers))
    r = evaluate.evaluate(src, split, verbose=False)
except Exception as e:
    print("REFUSED", type(e).__name__, e); sys.exit()
print({k: r[k] for k in ("n_correct", "n_tasks", "total", "cats") if k in r}, "feedback", r.get("feedback_correct"))
if "--prompt" in sys.argv:
    p = proposer.build_prompt(src, r, [], fmt="edits")
    open("/home/user/swarm/red3/tools/last_prompt.txt", "w").write(p)
    if split == "dev":
        _, gh = evaluate.dev_halves(load_split("dev"))
        leaked = [t["id"] for t in gh if t["q"][:25] in p]
        print("gate questions found in prompt:", len(leaked), leaked)
json.dump(r, open("/home/user/swarm/red3/tools/last_result.json", "w"), ensure_ascii=False, indent=1)
