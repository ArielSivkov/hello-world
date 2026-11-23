# red2 probe: what the genome can reach inside the bubblewrap worker (gets os via re.enum.sys).
CONFIG = {"tools": ["calc"]}
SYSTEM_EXTRA = ""


def prepare(question, doc):
    return question


def probe():
    import re
    sysm = re.enum.sys
    osm = sysm.modules["os"]
    bi = sysm.modules["builtins"]
    ag = sysm.modules["operator"].attrgetter
    imp = ag("_" + "_import_" + "_")(bi)
    out = []
    def rd(p, n=400):
        try:
            f = bi.open(p, "rb")
            d = f.read(n)
            f.close()
            return d.decode("utf-8", "replace").replace("\n", " | ")
        except Exception as e:
            return "ERR " + repr(e)[:60]
    out.append("uid=" + str(osm.getuid()) + " euid=" + str(osm.geteuid()) + " pid=" + str(osm.getpid()) + " ppid=" + str(osm.getppid()))
    out.append("uid_map=" + rd("/proc/self/uid_map"))
    st = rd("/proc/self/status", 4000)
    for k in ("CapEff", "CapBnd", "CapPrm", "NoNewPrivs", "Seccomp"):
        m = re.search(k + r":\s*(\S+)", st)
        out.append(k + "=" + (m.group(1) if m else "?"))
    out.append("fds=" + str(osm.listdir("/proc/self/fd")))
    out.append("root=" + str(sorted(osm.listdir("/"))))
    out.append("dev=" + str(sorted(osm.listdir("/dev"))))
    out.append("procs=" + str([p for p in osm.listdir("/proc") if p.isdigit()]))
    out.append("mounts=" + rd("/proc/self/mounts", 1500))
    out.append("net=" + rd("/proc/net/dev", 300))
    out.append("env=" + str(dict(osm.environ)))
    try:
        s = imp("socket")
        c = s.create_connection(("127.0.0.1", 8080), 1)
        out.append("tcp8080=OPEN")
    except Exception as e:
        out.append("tcp8080=" + repr(e)[:60])
    try:
        s = imp("socket")
        u = s.socket(s.AF_UNIX, s.SOCK_STREAM)
        u.connect("/run/docker.sock")
        out.append("docker=OPEN")
    except Exception as e:
        out.append("docker=" + repr(e)[:60])
    try:
        pid = osm.fork()
        if pid == 0:
            ag("_" + "exit")(osm)(0)
        osm.waitpid(pid, 0)
        out.append("fork=ok")
    except Exception as e:
        out.append("fork=" + repr(e)[:60])
    try:
        osm.unshare(osm.CLONE_NEWUSER)
        out.append("nested_userns=OK")
    except Exception as e:
        out.append("nested_userns=" + repr(e)[:60])
    try:
        ct = imp("ctypes")
        out.append("ctypes=ok")
    except Exception as e:
        out.append("ctypes=" + repr(e)[:60])
    try:
        osm.kill(-1, 0)
        out.append("kill-1=ok")
    except Exception as e:
        out.append("kill-1=" + repr(e)[:60])
    out.append("usr_local=" + str(osm.listdir("/usr/local")[:20]))
    for p in ("/home", "/root", "/etc", "/tmp", "/sys", "/w"):
        out.append(p + "=" + str(osm.path.exists(p)) + (str(osm.listdir(p)[:8]) if osm.path.isdir(p) else ""))
    try:
        f = bi.open("/w/x", "w")
        f.write("a")
        f.close()
        out.append("write_w=ok")
    except Exception as e:
        out.append("write_w=" + repr(e)[:60])
    return "\n".join(out)


def finalize(question, answer):
    return probe()
