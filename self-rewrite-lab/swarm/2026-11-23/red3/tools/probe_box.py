import sys, subprocess, time; sys.path[:0]=["/home/user/swarm/red3/lab"]
from rewrite import isolation
code = open("/home/user/swarm/red3/tools/box_code.py").read()
cmd = isolation.command()[:-1] + ["-c", code]
for i in range(10):
    r = subprocess.run(cmd, capture_output=True, text=True, timeout=60)
    if "Can't fork" not in r.stderr: break
    time.sleep(1)
print(r.stdout, r.stderr[-800:])
