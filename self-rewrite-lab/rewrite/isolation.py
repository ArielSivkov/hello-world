"""Parent side of the hook worker: starts it in bubblewrap and talks to it over a pipe."""
import json
import os
import select
import shutil
import signal
import subprocess
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
PY = os.path.realpath(sys.executable)
STDLIB = os.path.dirname(os.__file__)                  # e.g. /usr/local/lib/python3.13
LIMITS = {"as": 1 << 30, "cpu": 900, "nproc": 32, "fsize": 0}
CALL_TIMEOUT = 2.0      # seconds per prepare/finalize call
INIT_TIMEOUT = 10.0
MAX_LINE = 1 << 16


class HookError(Exception):
    """Fatal: the worker timed out, died or broke the protocol. The genome is refused."""


class HookFailed(HookError):
    """A hook raised or returned a non-string for one task. That task fails; the worker lives on."""


def command():
    if not shutil.which("bwrap"):
        raise RuntimeError("bubblewrap (bwrap) is required: apt-get install -y bubblewrap")
    binds = []
    for p in sorted({"/usr", os.path.dirname(os.path.dirname(STDLIB)), os.path.dirname(PY)}):
        if os.path.exists(p):
            binds += ["--ro-bind", p, p]
    for link, target in (("/lib", "usr/lib"), ("/lib64", "usr/lib64"), ("/bin", "usr/bin")):
        if os.path.exists(link):
            binds += ["--symlink", target, link]
    worker_dir = "/w"
    files = []
    for name in ("hookworker.py", "sandbox.py"):
        files += ["--ro-bind", os.path.join(HERE, name), f"{worker_dir}/{name}"]
    lim = [f"--{k}={v}" for k, v in LIMITS.items()]
    return (["prlimit", *lim, "--", "bwrap", "--unshare-all", "--die-with-parent", "--new-session",
             "--uid", "65534", "--gid", "65534", "--clearenv", "--setenv", "PYTHONHASHSEED", "0",
             *binds, *files, "--proc", "/proc", "--dev", "/dev", "--chdir", worker_dir,
             PY, "-I", "-S", f"{worker_dir}/hookworker.py"])


class HookWorker:
    def __init__(self, source):
        self.p = subprocess.Popen(command(), stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                                  stderr=subprocess.DEVNULL, start_new_session=True)
        self.buf = b""
        r = self._call({"op": "init", "source": source}, INIT_TIMEOUT)
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

    def _call(self, msg, timeout=CALL_TIMEOUT):
        try:
            self.p.stdin.write((json.dumps(msg, ensure_ascii=False) + "\n").encode())
            self.p.stdin.flush()
            r = json.loads(self._readline(timeout))
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
        if self.p.poll() is None:
            try:
                os.killpg(self.p.pid, signal.SIGKILL)
            except ProcessLookupError:
                pass
        self.p.wait()
