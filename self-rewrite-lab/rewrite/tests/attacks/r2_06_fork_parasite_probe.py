# red2 P2 (probe, harmless version): the genome can fork inside the worker (no seccomp, no cgroup).
# Children block on a pipe here; a hostile genome would make them spin: up to RLIMIT_NPROC processes,
# each with its own 900 s RLIMIT_CPU, alive for the whole evaluation, competing with the model server.
CONFIG = {"tools": ["calc"]}
SYSTEM_EXTRA = ""


def prepare(question, doc):
    return question


def finalize(question, answer):
    import re
    osm = re.enum.sys.modules["os"]
    rfd, wfd = osm.pipe()
    n = 0
    for i in range(40):
        try:
            pid = osm.fork()
        except Exception:
            break
        if pid == 0:
            osm.read(rfd, 1)
            osm.kill(osm.getpid(), 9)
        n = n + 1
    return "forked " + str(n)
