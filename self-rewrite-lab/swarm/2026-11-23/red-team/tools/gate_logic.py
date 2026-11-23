"""Gate-logic probes against the real rewrite.gate.decide (no model)."""
import sys
sys.path[:0] = ["/home/user/swarm/red-team/lab/ion-loop", "/home/user/swarm/red-team/lab"]
from rewrite import gate

N = {"basic": 20, "calc": 12, "longdoc": 12, "multistep": 16, "web": 16}


def res(correct):
    cats = {c: round(100 * correct[c] / N[c]) for c in N}
    return {"total": round(sum(cats.values()) / len(cats), 1), "cats": cats}


print("1) ratchet: longdoc loses one task per generation, basic gains two; every step is checked only against the previous champion")
cur_c = {"basic": 12, "calc": 11, "longdoc": 12, "multistep": 15, "web": 14}
seed = res(cur_c)
cur = seed
for g in range(1, 5):
    nxt = dict(cur_c); nxt["longdoc"] -= 1; nxt["basic"] += 2
    new = res(nxt)
    keep, reg = gate.decide(cur, new)
    print(f"   gen {g}: longdoc {cur['cats']['longdoc']:>3} -> {new['cats']['longdoc']:>3}, total {cur['total']} -> {new['total']}  kept={keep}")
    if keep:
        cur, cur_c = new, nxt
print(f"   after 4 accepted generations: longdoc {seed['cats']['longdoc']} -> {cur['cats']['longdoc']} (a {seed['cats']['longdoc']-cur['cats']['longdoc']}-point drop that no single step reported)")

print("2) one task of noise is enough: +1 basic task (5 points in one category) =", gate.decide(seed, res({'basic': 13, 'calc': 11, 'longdoc': 12, 'multistep': 15, 'web': 14})))

print("3) rounding: category scores are rounded to integers with banker's rounding before averaging")
print("   web 2/16 ->", round(100*2/16), " 6/16 ->", round(100*6/16), " 10/16 ->", round(100*10/16), " 14/16 ->", round(100*14/16))

print("4) tie: equal totals are refused (strict >):", gate.decide(seed, dict(seed)))
print("5) a category missing from the new result counts as 0, so it is a regression:", gate.decide(seed, {"total": 99, "cats": {c: 100 for c in N if c != 'web'}}))
try:
    print(gate.decide(seed, {"total": 99}))
except Exception as e:
    print("6) result without 'cats' (forged RESULT line, see e6b) crashes decide:", type(e).__name__, e)
