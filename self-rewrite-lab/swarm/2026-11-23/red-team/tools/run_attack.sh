#!/bin/bash
# usage: run_attack.sh <genome> [split]   — runs the genome through the evaluator exactly like gate.score, model stubbed
rm -rf /home/user/swarm/red-team/lab/rewrite/runs/redteam
cd /home/user/swarm/red-team/lab && ION_TAG=redteam timeout 300 python3 /home/user/swarm/red-team/tools/harness.py --genome "$1" --split "${2:-dev}" 2>&1 | grep -E "^RESULT|Error|Refused" | python3 -c "
import sys,json
for l in sys.stdin:
    if l.startswith('RESULT '):
        r=json.loads(l[7:]); print('RESULT total=%s cats=%s failures=%d' % (r['total'], r['cats'], len(r.get('failures',[]))))
    else: print(l.rstrip()[:300])
"
