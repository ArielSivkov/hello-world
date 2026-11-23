import sys
sys.path[:0] = ["/home/user/swarm/red2/lab/ion-loop", "/home/user/swarm/red2/lab"]
from rewrite.isolation import HookWorker
w = HookWorker(open(sys.argv[1]).read())
try:
    print(w.call(sys.argv[2] if len(sys.argv) > 2 else "finalize", q="q", a="a", doc=None))
finally:
    w.close()
