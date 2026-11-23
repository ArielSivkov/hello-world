"""Red team 2 harness: real judge + real bwrap worker, model replaced by the seed's recorded dev answers.
usage: python3 harness.py <genome> [--splits dev,holdout]"""
import json, os, sys, tempfile, time
LAB = "/home/user/swarm/red2/lab"
sys.path[:0] = [os.path.join(LAB, "ion-loop"), LAB]
from rewrite import evaluate, gate, sandbox
from arena.run import load as load_split
ANS = json.load(open(os.path.join(LAB, "rewrite/tests/fixtures/seed_dev_answers.json"), encoding="utf-8"))
evaluate.RUNS = tempfile.mkdtemp(prefix="red2runs-")
BP, BPH = evaluate.agent.BASE_PROMPT, evaluate.agent.BASE_PROMPT_HE
SEEN = []
def fake_run(q, cfg, doc=None):
    SEEN.append(q)
    return ANS.get(q, ""), [("model", "x")]
evaluate.agent.run = fake_run
DEV_ANSWERS = [a for t in load_split("dev") for a in t["answers"]]

def run(src, split):
    evaluate.agent.BASE_PROMPT, evaluate.agent.BASE_PROMPT_HE = BP, BPH
    try:
        return evaluate.evaluate(src, split, verbose=False)
    except sandbox.Refused as e:
        return {"refused": f"sandbox: {e}"}
    except evaluate.HookError as e:
        return {"refused": f"hook: {e}"}

if __name__ == "__main__":
    path = sys.argv[1]
    splits = (sys.argv[2] if len(sys.argv) > 2 else "dev,holdout").split(",")
    src = open(path, encoding="utf-8").read()
    fp = gate.fingerprint()
    try:
        sandbox.check(src); static = "pass"
        hit = sandbox.contains_test_answer(src, DEV_ANSWERS)
        static = hit or "pass"
    except sandbox.Refused as e:
        static = f"refused: {e}"
    print("static(loop):", static)
    for sp in splits:
        t0 = time.time()
        r = run(src, sp)
        if "refused" in r:
            print(sp, "REFUSED", r["refused"], f"{time.time()-t0:.1f}s")
        else:
            print(sp, "n_correct", r["n_correct"], "/", r["n_tasks"], "total", r["total"], r["cats"], f"{time.time()-t0:.1f}s")
    gate.verify(fp); print("judge files unchanged")
