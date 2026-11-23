import sys
sys.path[:0]=["/home/user/swarm/red2/lab/ion-loop","/home/user/swarm/red2/lab"]
from rewrite.isolation import HookWorker
w=HookWorker(open(sys.argv[1]).read())
q=sys.argv[2]; a=sys.argv[3]
w.call("prepare",q=q,doc=None); print(repr(w.call("finalize",q=q,a=a))); w.close()
