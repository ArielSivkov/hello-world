"""Runs a genome's hooks in an isolated process. The judge never executes genome code itself.

The parent (rewrite/isolation.py) starts this file inside bubblewrap: uid nobody, no network, a
read-only filesystem holding only the Python standard library and this directory (no lab, no arena,
no answers), a fresh PID namespace, and rlimits on memory, CPU time, processes and file size.

Protocol: one JSON object per line.
  in : {"op": "init", "source": "..."}               out: {"ok": true, "CONFIG": {...}, "SYSTEM_EXTRA": "..."}
  in : {"op": "prepare", "q": "...", "doc": ...}      out: {"r": "..."}
  in : {"op": "finalize", "q": "...", "a": "..."}     out: {"r": "..."}
  any error                                           out: {"e": "<short reason>"}
Whatever the genome prints goes to /dev/null: stdout is replaced before the genome is loaded, so the
genome cannot write protocol lines of its own.
"""
import json
import os
import sys
import types

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import sandbox  # noqa: E402  (the static checker and the reduced builtins; it imports nothing from the lab)

MAX_OUT = 4000


def fresh_call(msg):
    """Run one hook in a forked child that loads the genome afresh: no state (module dicts, attributes set
    on imported modules, caches) survives from one task to the next (red team r3_01: gate questions seen in
    prepare() were carried to feedback answers and so into the proposer prompt)."""
    rfd, wfd = os.pipe()
    pid = os.fork()
    if pid == 0:
        try:
            os.close(rfd)
            mod = types.ModuleType("genome")
            mod.__dict__["__builtins__"] = sandbox._builtins()
            exec(SOURCE[0], mod.__dict__)
            if msg["op"] == "prepare":
                r = mod.prepare(msg["q"], msg.get("doc"))
            else:
                r = mod.finalize(msg["q"], msg["a"])
            out = {"r": r[:MAX_OUT]} if isinstance(r, str) else {"e": f"{msg['op']}() must return str"}
        except BaseException as e:     # noqa: BLE001
            out = {"e": type(e).__name__}
        try:
            os.write(wfd, json.dumps(out, ensure_ascii=True).encode()[:1 << 15])
        finally:
            os._exit(0)
    os.close(wfd)
    data = b""
    for _ in range(64):
        chunk = os.read(rfd, 1 << 15)
        if not chunk:
            break
        data += chunk
    os.close(rfd)
    os.waitpid(pid, 0)
    try:
        return json.loads(data)
    except ValueError:
        return {"e": "hook crashed"}


SOURCE = [None]


def main():
    proto = os.fdopen(os.dup(1), "w", encoding="utf-8")      # the only channel back to the judge
    devnull = open(os.devnull, "w")
    sys.stdout = sys.stderr = devnull
    os.dup2(devnull.fileno(), 1)
    os.dup2(devnull.fileno(), 2)
    mod = None

    def send(obj):
        proto.write(json.dumps(obj, ensure_ascii=False) + "\n")
        proto.flush()

    for line in sys.stdin:
        try:
            msg = json.loads(line)
        except ValueError:
            send({"e": "bad request"})
            continue
        try:
            if msg["op"] == "init":
                sandbox.check(msg["source"])
                mod = types.ModuleType("genome")
                mod.__dict__["__builtins__"] = sandbox._builtins()
                SOURCE[0] = compile(msg["source"], "<genome>", "exec")
                exec(SOURCE[0], mod.__dict__)
                cfg, extra = getattr(mod, "CONFIG", None), getattr(mod, "SYSTEM_EXTRA", None)
                if not isinstance(cfg, dict) or not isinstance(extra, str):
                    send({"e": "CONFIG must be a dict and SYSTEM_EXTRA a str"})
                    continue
                send({"ok": True, "CONFIG": json.loads(json.dumps(cfg)), "SYSTEM_EXTRA": extra[:MAX_OUT]})
            elif mod is None:
                send({"e": "not initialised"})
            elif msg["op"] in ("prepare", "finalize"):
                send(fresh_call(msg))
            else:
                send({"e": "unknown op"})
        except sandbox.Refused as e:
            send({"e": f"sandbox: {e}"[:300]})
        except BaseException as e:     # noqa: BLE001  includes SystemExit: the genome cannot end the worker cleanly
            send({"e": f"{type(e).__name__}"})


if __name__ == "__main__":
    main()
