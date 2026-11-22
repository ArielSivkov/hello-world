"""Print a compact table for one or more runs."""
import json
import sys
from pathlib import Path

for run in sys.argv[1:]:
    rows = json.loads((Path(run) / "log.json").read_text())
    print(f"\n{run}  accepted {sum(r['decision']['accept'] for r in rows)}/{len(rows)}")
    print("cyc  base  base+R  incumb  cand  cand+R | vs_inc[hi]  vs_base+R | core_gen[hi] core_dom[hi] | gate")
    for r in rows:
        b, c = r["bpt"], r["core_vs_base"]
        print(f"{r['cycle']:>3} {b['base']:.3f} {b['base+retrieval']:.3f}  {b['incumbent']:.3f} "
              f"{b['candidate']:.3f} {b['candidate+retrieval']:.3f} | "
              f"{r['candidate_vs_incumbent']['diff']:+.3f}[{r['candidate_vs_incumbent']['hi']:+.3f}] "
              f"{r['candidate_vs_base+retrieval']['diff']:+.3f} | "
              f"{c['core_general']['diff']:+.3f}[{c['core_general']['hi']:+.3f}] "
              f"{c['core_domain_old']['diff']:+.3f}[{c['core_domain_old']['hi']:+.3f}] | "
              f"{'ACCEPT' if r['decision']['accept'] else 'reject'}")
