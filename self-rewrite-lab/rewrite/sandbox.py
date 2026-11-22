"""Static checks for a proposed genome, and loading it as an isolated module.

A genome that fails any check is refused before it runs. The checks are deliberately strict: the
genome may compute on strings, it may not reach the judge, the disk, the network or the interpreter.
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
    try:
        tree = ast.parse(source)
    except SyntaxError as e:
        raise Refused(f"syntax error: {e.msg} (line {e.lineno})")

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


def load(source, name="genome"):
    """Check, execute in a fresh module with a reduced builtins table, and validate the values."""
    check(source)
    mod = types.ModuleType(name)
    mod.__dict__["__builtins__"] = _builtins()
    try:
        exec(compile(source, f"<{name}>", "exec"), mod.__dict__)
    except Exception as e:     # noqa: BLE001
        raise Refused(f"genome failed to import: {type(e).__name__}: {e}")
    cfg = getattr(mod, "CONFIG", None)
    if not isinstance(cfg, dict):
        raise Refused("CONFIG must be a dict")
    unknown = set(cfg) - config_fields()
    if unknown:
        raise Refused(f"unknown CONFIG keys: {sorted(unknown)}")
    if not isinstance(getattr(mod, "SYSTEM_EXTRA", None), str):
        raise Refused("SYSTEM_EXTRA must be a str")
    if len(mod.SYSTEM_EXTRA) > 2000:
        raise Refused("SYSTEM_EXTRA is longer than 2000 characters")
    try:     # smoke test: the hooks must return strings on ordinary input
        for q in ("מהי בירת צרפת?", "כמה זה 1234 כפול 5678?", ""):
            if not isinstance(mod.prepare(q, None), str) or not isinstance(mod.finalize(q, "פריז"), str):
                raise Refused("prepare() and finalize() must return str")
    except Refused:
        raise
    except Exception as e:     # noqa: BLE001
        raise Refused(f"hook crashed on a smoke test: {type(e).__name__}: {e}")
    return mod
