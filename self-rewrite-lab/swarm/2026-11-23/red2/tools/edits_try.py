import sys, glob, os, traceback
sys.path[:0] = ["/home/user/swarm/red2/lab/ion-loop", "/home/user/swarm/red2/lab"]
from rewrite import proposer
champ = open("/home/user/swarm/red2/lab/rewrite/genome/seed.py").read()
for p in sorted(glob.glob(sys.argv[1])):
    reply = open(p).read()
    try:
        src, change, why = proposer.parse(reply, champ, "edits")
        print(os.path.basename(p), "->", "OK" if src else "refused: " + str(why)[:100])
    except BaseException as e:
        print(os.path.basename(p), "-> LOOP CRASH:", type(e).__name__, str(e)[:80])
