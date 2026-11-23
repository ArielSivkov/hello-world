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
                exec(compile(msg["source"], "<genome>", "exec"), mod.__dict__)
                cfg, extra = getattr(mod, "CONFIG", None), getattr(mod, "SYSTEM_EXTRA", None)
                if not isinstance(cfg, dict) or not isinstance(extra, str):
                    send({"e": "CONFIG must be a dict and SYSTEM_EXTRA a str"})
                    continue
                send({"ok": True, "CONFIG": json.loads(json.dumps(cfg)), "SYSTEM_EXTRA": extra[:MAX_OUT]})
            elif mod is None:
                send({"e": "not initialised"})
            elif msg["op"] == "prepare":
                r = mod.prepare(msg["q"], msg.get("doc"))
                send({"r": r[:MAX_OUT]} if isinstance(r, str) else {"e": "prepare() must return str"})
            elif msg["op"] == "finalize":
                r = mod.finalize(msg["q"], msg["a"])
                send({"r": r[:MAX_OUT]} if isinstance(r, str) else {"e": "finalize() must return str"})
            else:
                send({"e": "unknown op"})
        except sandbox.Refused as e:
            send({"e": f"sandbox: {e}"[:300]})
        except BaseException as e:     # noqa: BLE001  includes SystemExit: the genome cannot end the worker cleanly
            send({"e": f"{type(e).__name__}"})


if __name__ == "__main__":
    main()
