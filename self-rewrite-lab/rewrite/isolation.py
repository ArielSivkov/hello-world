"""Parent side of the hook worker: starts it in bubblewrap and talks to it over a pipe."""
import json
import os
import re
import select
import shutil
import signal
import subprocess
import sys
import time

HERE = os.path.dirname(os.path.abspath(__file__))
PY = os.path.realpath(sys.executable)
STDLIB = os.path.dirname(os.__file__)                  # e.g. /usr/local/lib/python3.13
LIMITS = {"as": 512 << 20, "cpu": 900, "nproc": 8, "fsize": 0}   # worst case ~8 x 512MB
# A uid of its own: nobody is shared with other programs on the host, and nproc counts per uid (red team r3:
# other nobody processes made honest genomes fail to start).
WORKER_UID = int(os.environ.get("REWRITE_WORKER_UID", "61000"))
CALL_TIMEOUT = 2.0      # seconds per prepare/finalize call
INIT_TIMEOUT = 10.0
MAX_LINE = 1 << 16


def _become_subreaper():
    """bwrap double-forks; the orphan would go to the container's PID 1, which may never reap it, and
    zombies of uid nobody count against the worker's process limit. As a subreaper, this process gets them
    back and reaps them in HookWorker.close()."""
    try:
        import ctypes
        ctypes.CDLL(None, use_errno=True).prctl(36, 1, 0, 0, 0)     # PR_SET_CHILD_SUBREAPER
    except Exception:     # noqa: BLE001  not Linux, or no libc: close() still kills the group
        pass


def _reap_worker_zombies():
    me = str(os.getpid())
    for pid in os.listdir("/proc"):
        if not pid.isdigit():
            continue
        try:
            st = open(f"/proc/{pid}/status").read()
        except OSError:
            continue
        f = dict(line.split(":", 1) for line in st.splitlines() if ":" in line)
        if f.get("PPid", "").strip() == me and f.get("State", "").strip().startswith("Z") and \
                f.get("Uid", "").split()[:1] == [str(WORKER_UID)]:
            try:
                os.waitpid(int(pid), os.WNOHANG)
            except ChildProcessError:
                pass


def _is_child(pid):
    try:
        return f"PPid:\t{os.getpid()}\n" in open(f"/proc/{pid}/status").read()
    except OSError:
        return False


_become_subreaper()


class HookError(Exception):
    """Fatal: the worker timed out, died or broke the protocol. The genome is refused."""


class HookFailed(HookError):
    """A hook raised or returned a non-string for one task. That task fails; the worker lives on."""


def _libdirs():
    """The shared-library directories the interpreter needs (from ldd), so /usr/bin is not bound."""
    out = subprocess.run(["ldd", PY], capture_output=True, text=True).stdout
    dirs = {os.path.dirname(os.path.realpath(t)) for t in re.findall(r"(/\S+)", out) if os.path.exists(t)}
    return sorted(dirs)


def command():
    """bwrap launched as the real user nobody (so RLIMIT_NPROC holds: the red team forked 150 times when
    the sandbox mapped to root outside), with nested user namespaces disabled and only the interpreter,
    its standard library and its shared libraries visible."""
    if not shutil.which("bwrap"):
        raise RuntimeError("bubblewrap (bwrap) is required: apt-get install -y bubblewrap")
    binds = ["--ro-bind", PY, PY, "--ro-bind", STDLIB, STDLIB]
    for d in _libdirs():
        binds += ["--ro-bind", d, d]
    for link in ("/lib64", "/lib"):
        if os.path.islink(link):
            target = os.path.realpath(link)
            if target not in _libdirs():
                binds += ["--ro-bind", target, target]
            binds += ["--symlink", os.readlink(link), link]
    worker_dir = "/w"
    files = []
    for name in ("hookworker.py", "sandbox.py"):
        files += ["--ro-bind", os.path.join(HERE, name), f"{worker_dir}/{name}"]
    lim = [f"--{k}={v}" for k, v in LIMITS.items()]
    return (["setpriv", f"--reuid={WORKER_UID}", f"--regid={WORKER_UID}", "--clear-groups", "--inh-caps=-all",
             "prlimit", *lim, "--", "bwrap", "--unshare-all", "--unshare-user", "--disable-userns",
             "--die-with-parent", "--new-session", "--uid", str(WORKER_UID), "--gid", str(WORKER_UID), "--clearenv",
             "--setenv", "PYTHONHASHSEED", "0", *binds, *files, "--proc", "/proc", "--dev", "/dev",
             "--chdir", worker_dir, PY, "-I", "-S", f"{worker_dir}/hookworker.py"])


class HookWorker:
    def __init__(self, source):
        for attempt in range(3):      # the last worker's processes may still be exiting (nproc is per uid)
            self.p = subprocess.Popen(command(), stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                                      stderr=subprocess.DEVNULL, start_new_session=True)
            self.buf = b""
            os.set_blocking(self.p.stdin.fileno(), False)
            try:
                r = self._call({"op": "init", "source": source}, INIT_TIMEOUT)
                break
            except HookError as e:
                if str(e) != "hook worker died" or attempt == 2:
                    raise
                time.sleep(0.5)
        if "ok" not in r:
            self.close()
            raise HookError(str(r.get("e", "init failed"))[:300])
        self.config, self.system_extra = r["CONFIG"], r["SYSTEM_EXTRA"]

    def _readline(self, timeout):
        while b"\n" not in self.buf:
            ready, _, _ = select.select([self.p.stdout], [], [], timeout)
            if not ready:
                raise HookError("hook timed out")
            chunk = os.read(self.p.stdout.fileno(), 65536)
            if not chunk:
                raise HookError("hook worker died")
            self.buf += chunk
            if len(self.buf) > MAX_LINE:
                raise HookError("hook output too large")
        line, self.buf = self.buf.split(b"\n", 1)
        return line

    def _write(self, data, timeout):
        """Write without ever blocking on a worker that does not read (red team r2_05)."""
        fd = self.p.stdin.fileno()
        while data:
            _, ready, _ = select.select([], [fd], [], timeout)
            if not ready:
                raise HookError("hook timed out")
            data = data[os.write(fd, data[:65536]):]

    def _call(self, msg, timeout=CALL_TIMEOUT):
        try:
            if self.buf:      # a reply nobody asked for: the worker is writing ahead of the protocol
                raise HookError("hook worker protocol error")
            self._write((json.dumps(msg, ensure_ascii=True) + "\n").encode(), timeout)
            r = json.loads(self._readline(timeout))
            if self.buf:
                raise HookError("hook worker protocol error")
        except HookError:
            self.close()
            raise
        except (OSError, ValueError):
            self.close()
            raise HookError("hook worker protocol error")
        if not isinstance(r, dict):
            raise HookError("hook worker protocol error")
        return r

    def call(self, op, **kw):
        r = self._call({"op": op, **kw})
        if not isinstance(r.get("r"), str):
            raise HookFailed(str(r.get("e", "bad reply"))[:120])
        return r["r"]

    def close(self):
        """Let the worker exit cleanly (EOF on stdin, so bwrap reaps its own children); kill the group only
        if it does not. A killed bwrap can leave zombies that count against nobody's process limit."""
        if self.p.poll() is None:
            try:
                self.p.stdin.close()
            except OSError:
                pass
            try:
                self.p.wait(timeout=2)
            except subprocess.TimeoutExpired:
                try:
                    os.killpg(self.p.pid, signal.SIGKILL)
                except ProcessLookupError:
                    pass
        self.p.wait()
        for _ in range(20):
            _reap_worker_zombies()
            if not any(open(f"/proc/{q}/status").read().find(f"Uid:\t{WORKER_UID}") >= 0
                       for q in os.listdir("/proc") if q.isdigit() and _is_child(q)):
                break
            time.sleep(0.05)
