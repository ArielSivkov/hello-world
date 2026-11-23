"""Static checks for a proposed genome: a first filter that gives the proposer a useful reason.

This is NOT the security boundary. The red team (swarm/2026-11-23/red-team) escaped an in-process
version of it through allowed modules (re.enum.sys, json.codecs) and frame attributes. Genome code
now runs only in rewrite/hookworker.py, inside bubblewrap with no lab files, no network and rlimits.
This module also validates the values the genome reports (CONFIG, SYSTEM_EXTRA) in the judge.
This file is bound into the worker, so it must import nothing from the lab at module level.
"""
import ast
import dataclasses
import types

ALLOWED_IMPORTS = {"re", "math", "json", "unicodedata", "string", "collections", "itertools", "functools"}
BANNED_NAMES = {
    "open", "exec", "eval", "compile", "__import__", "globals", "locals", "vars", "getattr", "setattr",
    "delattr", "input", "breakpoint", "exit", "quit", "help", "memoryview", "classmethod", "staticmethod",
    "super", "object", "type", "print",
}
MAX_BYTES = 20_000
REQUIRED_FUNCS = {"prepare": 2, "finalize": 2}


class Refused(Exception):
    pass


def config_fields():
    from ion.agent import Config
    return {f.name for f in dataclasses.fields(Config)}


def check(source):
    """Raise Refused with a short reason, or return the parsed tree."""
    if len(source.encode()) > MAX_BYTES:
        raise Refused(f"genome is larger than {MAX_BYTES} bytes")
    if not isinstance(source, str):
        raise Refused("genome must be text")
    try:
        tree = ast.parse(source)
    except SyntaxError as e:
        raise Refused(f"syntax error: {e.msg} (line {e.lineno})")
    except (MemoryError, RecursionError, ValueError) as e:     # deep nesting overflows the parser
        raise Refused(f"genome cannot be parsed: {type(e).__name__}")

    for node in tree.body:     # module level: declarations only, no side effects at import time
        ok = isinstance(node, (ast.Import, ast.ImportFrom, ast.FunctionDef, ast.Assign, ast.AnnAssign)) or (
            isinstance(node, ast.Expr) and isinstance(node.value, ast.Constant) and isinstance(node.value.value, str))
        if not ok:
            raise Refused(f"line {node.lineno}: only imports, assignments and functions are allowed at module level")

    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for a in node.names:
                if a.name.split(".")[0] not in ALLOWED_IMPORTS:
                    raise Refused(f"line {node.lineno}: import of '{a.name}' is not allowed")
        elif isinstance(node, ast.ImportFrom):
            if (node.module or "").split(".")[0] not in ALLOWED_IMPORTS or node.level:
                raise Refused(f"line {node.lineno}: import from '{node.module}' is not allowed")
        elif isinstance(node, ast.Name) and (node.id in BANNED_NAMES or node.id.startswith("_")):
            raise Refused(f"line {node.lineno}: name '{node.id}' is not allowed")
        elif isinstance(node, ast.Attribute) and node.attr.startswith("_"):
            raise Refused(f"line {node.lineno}: attribute '{node.attr}' is not allowed")
        elif isinstance(node, (ast.Global, ast.Nonlocal, ast.ClassDef, ast.AsyncFunctionDef, ast.Await,
                               ast.Lambda, ast.With, ast.AsyncWith)):
            raise Refused(f"line {node.lineno}: {type(node).__name__} is not allowed")
        elif isinstance(node, ast.While):
            raise Refused(f"line {node.lineno}: while loops are not allowed (use a bounded for loop)")

    funcs = {n.name: n for n in tree.body if isinstance(n, ast.FunctionDef)}
    for name, nargs in REQUIRED_FUNCS.items():
        if name not in funcs:
            raise Refused(f"missing function {name}()")
        if len(funcs[name].args.args) != nargs:
            raise Refused(f"{name}() must take exactly {nargs} arguments")
    return tree


SAFE_BUILTINS = [
    "abs", "all", "any", "bool", "chr", "dict", "enumerate", "filter", "float", "frozenset", "int",
    "isinstance", "len", "list", "map", "max", "min", "ord", "range", "repr", "reversed", "round", "set",
    "sorted", "str", "sum", "tuple", "zip", "True", "False", "None", "Exception", "ValueError",
    "KeyError", "IndexError", "TypeError",
]


def _guarded_import(name, globals=None, locals=None, fromlist=(), level=0):
    if level or name.split(".")[0] not in ALLOWED_IMPORTS:
        raise ImportError(f"import of '{name}' is not allowed")
    return __import__(name, globals, locals, fromlist, level)


def _builtins():
    import builtins
    b = {k: getattr(builtins, k) for k in SAFE_BUILTINS}
    b["__import__"] = _guarded_import
    return b


# Allowed values of CONFIG (types and ranges). The agent and its tools are fixed; the genome only
# chooses among their switches. No network tool (fetch); sampling is locked to temperature 0.
CHOICES = {
    "decompose": {"", "llm", "entities", "entities-dated", "entities-facts"},
    "extract": {"llm", "facts-only", "structured"},
}
ALLOWED_TOOLS = {"calc", "web_search", "doc_search"}
RANGES = {"max_steps": (1, 8), "doc_chars": (200, 6000), "notes_chars": (100, 1500), "notes_n": (1, 4),
          "rag_k": (1, 6), "rag_neighbors": (0, 2)}
MAX_EXTRA = 2000


def validate_config(cfg):
    """Return a clean CONFIG dict or raise Refused. Unknown keys, wrong types, values out of range."""
    from ion.agent import Config
    fields = {f.name: f for f in dataclasses.fields(Config)}
    if not isinstance(cfg, dict):
        raise Refused("CONFIG must be a dict")
    unknown = set(cfg) - set(fields)
    if unknown:
        raise Refused(f"unknown CONFIG keys: {sorted(unknown)[:5]}")
    defaults = Config()
    out = {}
    for k, v in cfg.items():
        d = getattr(defaults, k)
        if k == "temperature":
            if v not in (0, 0.0):
                raise Refused("temperature is locked to 0")
            v = 0.0
        elif k == "tools":
            if not isinstance(v, list) or not all(isinstance(x, str) for x in v) or set(v) - ALLOWED_TOOLS:
                raise Refused(f"tools must be a list drawn from {sorted(ALLOWED_TOOLS)}")
            v = list(dict.fromkeys(v))
        elif isinstance(d, bool):
            if not isinstance(v, bool):
                raise Refused(f"CONFIG {k} must be true or false")
        elif isinstance(d, int):
            if isinstance(v, bool) or not isinstance(v, int) or not (RANGES[k][0] <= v <= RANGES[k][1]):
                raise Refused(f"CONFIG {k} must be an integer in {list(RANGES[k])}")
        elif isinstance(d, str):
            if not isinstance(v, str) or v not in CHOICES.get(k, {v}):
                raise Refused(f"CONFIG {k} must be one of {sorted(CHOICES[k])}")
        out[k] = v
    return out


def validate_extra(extra):
    if not isinstance(extra, str):
        raise Refused("SYSTEM_EXTRA must be a str")
    if len(extra) > MAX_EXTRA:
        raise Refused(f"SYSTEM_EXTRA is longer than {MAX_EXTRA} characters")
    return extra


def contains_test_answer(source, answers, min_len=3):
    """Return a short reason if any string constant in the genome holds an expected test answer."""
    import unicodedata
    tree = ast.parse(source)
    consts = [n.value for n in ast.walk(tree) if isinstance(n, ast.Constant) and isinstance(n.value, str)]
    blob = "\n".join(consts)
    blob = "".join(ch for ch in unicodedata.normalize("NFKC", blob) if unicodedata.category(ch) != "Cf").lower()
    blob = blob + "\n" + blob[::-1]          # reversed literals ("ויקוט"[::-1]) are found too
    # This scan is hygiene only. The real defence against memorising is that the gate half of dev is never
    # shown to the proposer (evaluate.dev_halves).
    for a in answers:
        a = a.lower().strip()
        if len(a) >= min_len and a in blob:
            return "the genome contains an answer of the test set"
    return None


class _Loaded:
    """What load() returns: the genome's values, with hooks that run in the isolated worker."""

    def __init__(self, worker):
        self._w = worker
        self.CONFIG = validate_config(worker.config)
        self.SYSTEM_EXTRA = validate_extra(worker.system_extra)

    def prepare(self, question, doc):
        return self._w.call("prepare", q=question, doc=doc)

    def finalize(self, question, answer):
        return self._w.call("finalize", q=question, a=answer)


def load(source):
    """Check a genome and start it in the isolated worker (never in this process). Raises Refused."""
    import atexit
    from rewrite.isolation import HookWorker, HookError
    check(source)
    try:
        w = HookWorker(source)
    except HookError as e:
        raise Refused(f"hook: {e}")
    atexit.register(w.close)
    try:
        mod = _Loaded(w)
        for q in ("מהי בירת צרפת?", "כמה זה 1234 כפול 5678?", ""):     # smoke test
            mod.prepare(q, None)
            mod.finalize(q, "פריז")
    except HookError as e:
        w.close()
        raise Refused(f"hook: {e}")
    except Refused:
        w.close()
        raise
    return mod
