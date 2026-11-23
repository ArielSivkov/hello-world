"""Edit-based proposals: the proposer sends a small change, the harness applies it to the champion.

A 1.5B model cannot reliably return a complete file (it echoes it unchanged, drops required functions,
or forgets the CHANGE line). In the edit format it only writes what changes; this module turns that
into a complete candidate file, which then goes through the unchanged sandbox and gate.

Accepted pieces in one reply (any mix, applied in this order):

  CHANGE: <one sentence>                         (anywhere; '# CHANGE:' inside a code block also works)
  <<<<<<< SEARCH / ======= / >>>>>>> REPLACE      exact text replacement (aider style), applied first
  SET <key> = <value>                            one CONFIG value, outside code blocks
  SYSTEM_EXTRA = "<text>"                        outside code blocks
  ```json {"ops": [...]} ```                     {"op": "set_config", "key", "value"} |
                                                 {"op": "set_system_extra", "text"} |
                                                 {"op": "replace_function", "code"}
  ```python ... ```                              each top-level def replaces the function of that name
                                                 (or adds a helper); CONFIG = {...} / CONFIG["k"] = v /
                                                 SYSTEM_EXTRA = "..." set values; imports are added.

Anything malformed raises EditError with a short reason meant to be shown back to the proposer.
Nothing here decides acceptance: the result is checked by sandbox.check and scored by the gate.
"""
import ast
import json
import re
import textwrap

REQUIRED_ARGS = {"prepare": 2, "finalize": 2}
# Valid values of the string switches (from ion-loop/ion/agent.py); a wrong one is refused here with a
# useful message instead of silently behaving like the default inside the agent.
STR_CHOICES = {
    "decompose": ["", "llm", "entities", "entities-dated", "entities-facts"],
    "extract": ["llm", "facts-only", "structured"],
}
TOOL_NAMES = ["calc", "web_search", "fetch", "doc_search"]
MAX_SYSTEM_EXTRA = 2000


class EditError(Exception):
    pass


# ----------------------------------------------------------------------------------------- parsing

_FENCE = re.compile(r"```[ \t]*([A-Za-z0-9_+-]*)[ \t]*\n(.*?)(?:```|\Z)", re.S)
_SR = re.compile(r"^[ \t]*<{5,9}[ \t]*SEARCH[ \t]*\n(.*?)^[ \t]*={5,9}[ \t]*\n(.*?)^[ \t]*>{5,9}[ \t]*REPLACE[ \t]*$",
                 re.S | re.M)
_CHANGE = re.compile(r"^[ \t>*_-]*(?:#\s*)?\**CHANGE\**\s*:\**\s*(.+?)\s*$", re.M | re.I)
_SET = re.compile(r"^[ \t>*-]*SET\s+`?([A-Za-z_][A-Za-z0-9_]*)`?\s*(?:=|:|\bto\b)\s*(.+?)\s*$", re.M)
_BARE = re.compile(r"^[ \t>*-]*`?([a-z][a-z0-9_]*)`?\s*=\s*(\S.*?)\s*$", re.M)
_SYS = re.compile(r"^[ \t>*-]*`?SYSTEM_EXTRA`?\s*[=:]\s*(.+?)\s*$", re.M)


def _literal(text):
    """A value written by the model: Python literal, JSON literal, or None if neither."""
    text = text.strip().rstrip(",;").strip().strip("`")
    for parse in (ast.literal_eval, json.loads):
        try:
            return True, parse(text)
        except (ValueError, SyntaxError, TypeError, MemoryError, RecursionError):
            pass
    low = text.lower()
    if low in ("true", "false"):
        return True, low == "true"
    head = re.split(r"\s+(?:#|\(|--|because\b)", text, maxsplit=1)[0].strip()     # "5  # more passages"
    if head != text:
        return _literal(head)
    return False, text


def parse(reply):
    """Split a reply into (change, ops). ops is a list of dicts in application order."""
    if not reply or not reply.strip():
        raise EditError("empty reply")
    m = _CHANGE.search(reply)
    change = m.group(1).strip().strip("*`").strip()[:160] if m else None

    ops = []
    for search, replace in _SR.findall(reply):
        ops.append({"op": "search_replace", "search": search, "replace": replace})
    rest = _SR.sub("", reply)

    blocks = []
    def take(mt):
        blocks.append((mt.group(1).lower(), mt.group(2)))
        return "\n"
    outside = _FENCE.sub(take, rest)

    for key, raw in _SET.findall(outside):
        ok, val = _literal(raw)
        ops.append({"op": "set_config", "key": key, "value": val, "raw": not ok})
    for key, raw in _BARE.findall(outside):     # "rag_k = 5" without SET: used only if it is a CONFIG key
        if key != "SYSTEM_EXTRA":
            ok, val = _literal(raw)
            if ok:
                ops.append({"op": "maybe_set", "key": key, "value": val})
    for raw in _SYS.findall(outside):
        ok, val = _literal(raw)
        ops.append({"op": "set_system_extra", "text": val if ok else raw})

    for i, (lang, body) in enumerate(blocks, 1):
        if lang != "json" and _SET.search(body):     # SET lines written inside a code block
            for key, raw in _SET.findall(body):
                ok, val = _literal(raw)
                ops.append({"op": "set_config", "key": key, "value": val, "raw": not ok})
            body = _SET.sub("", body)
            if lang not in ("python", "py", "python3"):
                for raw in _SYS.findall(body):
                    ok, val = _literal(raw)
                    ops.append({"op": "set_system_extra", "text": val if ok else raw})
                continue
        if not body.strip():
            continue
        if lang == "json" or (not lang and body.lstrip()[:1] in ("{", "[")):
            ops.extend(_json_ops(body, i))
        elif lang in ("", "python", "py", "python3"):
            ops.extend(_python_ops(body, i))
        # other languages (```diff, ```text ...) are ignored
    return change, ops


def _json_ops(body, i):
    try:
        data = json.loads(body)
    except json.JSONDecodeError as e:
        raise EditError(f"json block {i}: invalid JSON ({e.msg}, line {e.lineno})")
    if isinstance(data, dict) and "ops" in data:
        data = data["ops"]
    elif isinstance(data, dict):     # {"CONFIG": {...}, "SYSTEM_EXTRA": "..."} shape
        out = []
        for k, v in (data.get("CONFIG") or {}).items():
            out.append({"op": "set_config", "key": k, "value": v})
        if "SYSTEM_EXTRA" in data:
            out.append({"op": "set_system_extra", "text": data["SYSTEM_EXTRA"]})
        if not out and not set(data) <= {"change"}:
            raise EditError(f"json block {i}: expected {{\"ops\": [...]}}")
        return out
    if not isinstance(data, list):
        raise EditError(f"json block {i}: expected a list of operations")
    out = []
    for j, op in enumerate(data, 1):
        kind = op.get("op") if isinstance(op, dict) else None
        if kind in ("set_config", "set"):
            if "key" not in op or "value" not in op:
                raise EditError(f"json block {i}, op {j}: set_config needs 'key' and 'value'")
            out.append({"op": "set_config", "key": op["key"], "value": op["value"]})
        elif kind == "set_system_extra":
            out.append({"op": "set_system_extra", "text": op.get("text", op.get("value"))})
        elif kind in ("replace_function", "replace_body"):
            code = op.get("code") or op.get("body")
            if not isinstance(code, str):
                raise EditError(f"json block {i}, op {j}: replace_function needs 'code'")
            if not code.lstrip().startswith("def ") and op.get("name"):
                code = f"def {op['name']}{_SIGS.get(op['name'], '(x)')}:\n" + textwrap.indent(textwrap.dedent(code), "    ")
            out.extend(_python_ops(code, f"{i}.{j}"))
        else:
            raise EditError(f"json block {i}, op {j}: unknown op {kind!r}")
    return out


_SIGS = {"prepare": "(question, doc)", "finalize": "(question, answer)"}


_COMPACT_ITEM = re.compile(r"([a-z][a-z0-9_]*)=(\[[^\]]*\]|\"[^\"]*\"|[^,\s]+)")


def _compact_config(code):
    """The packed 'CONFIG:' view of edit-mode prompts, copied back by the model -> (ops, remaining code)."""
    lines = code.splitlines()
    starts = [k for k, l in enumerate(lines) if l.strip() == "CONFIG:"]
    if not starts:
        return [], code
    k = starts[0]
    end = k + 1
    while end < len(lines) and lines[end].startswith((" ", "\t")) and lines[end].strip():
        end += 1
    ops = []
    for row in lines[k + 1:end]:
        for key, raw in _COMPACT_ITEM.findall(row):
            ok, val = _literal(raw)
            ops.append({"op": "set_config", "key": key, "value": val, "raw": not ok})
    return ops, "\n".join(lines[:k] + lines[end:])


def _python_ops(body, i):
    code = textwrap.dedent(body).strip("\n")
    if not code.strip():
        return []
    compact_ops, code = _compact_config(code)
    return compact_ops + _python_ops_strict(code, i)


def _python_ops_strict(code, i):
    if not code.strip():
        return []
    try:
        tree = ast.parse(code)
    except SyntaxError as e:
        raise EditError(f"python block {i}: syntax error: {e.msg} (line {e.lineno})")
    lines = code.splitlines()
    out = []
    for node in tree.body:
        seg = "\n".join(lines[node.lineno - 1 - len(getattr(node, "decorator_list", []) or []):node.end_lineno])
        if isinstance(node, ast.FunctionDef):
            want = REQUIRED_ARGS.get(node.name)
            if want is not None and len(node.args.args) != want:
                raise EditError(f"{node.name}() must take exactly {want} arguments: def {node.name}{_SIGS[node.name]}")
            out.append({"op": "def", "name": node.name, "code": seg})
        elif isinstance(node, (ast.Import, ast.ImportFrom)):
            out.append({"op": "import", "code": seg})
        elif isinstance(node, ast.Assign) and len(node.targets) == 1:
            t = node.targets[0]
            if isinstance(t, ast.Name) and t.id == "CONFIG":
                try:
                    cfg = ast.literal_eval(node.value)
                except ValueError:
                    raise EditError(f"python block {i}: CONFIG must be a plain dict literal")
                if not isinstance(cfg, dict):
                    raise EditError(f"python block {i}: CONFIG must be a dict")
                out.extend({"op": "set_config", "key": k, "value": v} for k, v in cfg.items())
            elif (isinstance(t, ast.Subscript) and isinstance(t.value, ast.Name) and t.value.id == "CONFIG"):
                try:
                    key, val = ast.literal_eval(t.slice), ast.literal_eval(node.value)
                except ValueError:
                    raise EditError(f"python block {i}: CONFIG[...] = needs a literal key and value")
                out.append({"op": "set_config", "key": key, "value": val})
            elif isinstance(t, ast.Name) and t.id == "SYSTEM_EXTRA":
                try:
                    out.append({"op": "set_system_extra", "text": ast.literal_eval(node.value)})
                except ValueError:
                    raise EditError(f"python block {i}: SYSTEM_EXTRA must be a plain string literal")
            elif isinstance(t, ast.Name):
                out.append({"op": "assign", "name": t.id, "code": seg})
            else:
                raise EditError(f"python block {i}, line {node.lineno}: unsupported assignment")
        elif isinstance(node, ast.Expr) and isinstance(node.value, ast.Constant):
            continue     # docstring / stray string
        else:
            raise EditError(f"python block {i}, line {node.lineno}: only def, imports and assignments are "
                            f"allowed, got {type(node).__name__}")
    return out


# ----------------------------------------------------------------------------------------- applying

def _py(v):
    """Render a CONFIG value as Python source in the seed's style."""
    if isinstance(v, bool) or v is None:
        return repr(v)
    if isinstance(v, str):
        return json.dumps(v, ensure_ascii=False)
    if isinstance(v, (list, tuple)):
        return "[" + ", ".join(_py(x) for x in v) + "]"
    return repr(v)


def render_config(cfg, indent="    "):
    return "CONFIG = {\n" + "".join(f"{indent}{json.dumps(k)}: {_py(v)},\n" for k, v in cfg.items()) + "}"


def check_value(key, value, current, fields):
    """Raise EditError if `value` is not a sensible value for CONFIG[key]; return the normalized value."""
    if key not in fields:
        close = [f for f in fields if f.startswith(key[:4])][:3]
        raise EditError(f"unknown CONFIG key '{key}'" + (f" (did you mean {', '.join(close)}?)" if close else ""))
    kind = fields[key]
    if kind is bool:
        if not isinstance(value, bool):
            raise EditError(f"CONFIG['{key}'] must be True or False, got {value!r}")
    elif kind is int:
        if isinstance(value, bool) or not isinstance(value, int):
            if isinstance(value, float) and value.is_integer():
                value = int(value)
            else:
                raise EditError(f"CONFIG['{key}'] must be a whole number, got {value!r}")
        if not 0 <= value <= 20000:
            raise EditError(f"CONFIG['{key}'] = {value} is out of range")
    elif kind is float:
        if isinstance(value, bool) or not isinstance(value, (int, float)):
            raise EditError(f"CONFIG['{key}'] must be a number, got {value!r}")
        value = float(value)
    elif kind is str:
        if not isinstance(value, str):
            raise EditError(f"CONFIG['{key}'] must be a string, got {value!r}")
        if key in STR_CHOICES and value not in STR_CHOICES[key]:
            raise EditError(f"CONFIG['{key}'] must be one of {STR_CHOICES[key]}, got {value!r}")
    elif kind is list:
        if isinstance(value, str):
            value = [value]
        if not isinstance(value, list) or not all(isinstance(x, str) for x in value):
            raise EditError(f"CONFIG['{key}'] must be a list of strings, got {value!r}")
        if key == "tools":
            bad = [x for x in value if x not in TOOL_NAMES]
            if bad:
                raise EditError(f"unknown tools {bad}; the tools are {TOOL_NAMES}")
    return value


def config_types():
    """CONFIG key -> python type, from the agent's Config dataclass (read only)."""
    import dataclasses
    from ion.agent import Config
    names = {"bool": bool, "int": int, "float": float, "str": str, "list": list}
    out = {}
    for f in dataclasses.fields(Config):
        t = f.type if isinstance(f.type, type) else names.get(str(f.type), str)
        out[f.name] = t
    return out


def _top_level(source):
    tree = ast.parse(source)
    spans = {}
    for node in tree.body:
        start = node.lineno - len(getattr(node, "decorator_list", []) or [])
        if isinstance(node, ast.FunctionDef):
            spans[("def", node.name)] = (start, node.end_lineno)
        elif isinstance(node, ast.Assign) and len(node.targets) == 1 and isinstance(node.targets[0], ast.Name):
            spans[("assign", node.targets[0].id)] = (start, node.end_lineno)
        elif isinstance(node, (ast.Import, ast.ImportFrom)):
            spans.setdefault(("import", None), (start, node.end_lineno))
            spans[("last_import", None)] = (start, node.end_lineno)
    return tree, spans


def _search_replace(source, search, replace, n):
    if not search.strip():
        raise EditError(f"SEARCH block {n} is empty")
    count = source.count(search)
    if count == 0:     # tolerate trailing-space / indentation-width noise: match line by line, stripped
        src_lines, pat = source.splitlines(), [l.strip() for l in search.strip("\n").splitlines()]
        hits = [k for k in range(len(src_lines) - len(pat) + 1)
                if [l.strip() for l in src_lines[k:k + len(pat)]] == pat]
        if len(hits) == 1:
            k = hits[0]
            new = src_lines[:k] + replace.rstrip("\n").splitlines() + src_lines[k + len(pat):]
            return "\n".join(new) + "\n"
        count = len(hits)
    if count == 0:
        raise EditError(f"SEARCH block {n} does not match the policy file (copy the lines exactly)")
    if count > 1:
        raise EditError(f"SEARCH block {n} matches {count} places; include more lines to make it unique")
    return source.replace(search, replace, 1)


def apply(champion, ops, fields=None):
    """Apply ops to the champion source. Returns the candidate source (may equal the champion)."""
    fields = fields if fields is not None else config_types()
    src = champion
    n = 0
    for op in ops:
        if op["op"] == "search_replace":
            n += 1
            src = _search_replace(src, op["search"], op["replace"], n)
    try:
        tree, spans = _top_level(src)
    except SyntaxError as e:
        raise EditError(f"after SEARCH/REPLACE the file has a syntax error: {e.msg} (line {e.lineno})")

    cfg_node = next((nd for nd in tree.body if isinstance(nd, ast.Assign) and len(nd.targets) == 1
                     and isinstance(nd.targets[0], ast.Name) and nd.targets[0].id == "CONFIG"), None)
    cfg = ast.literal_eval(cfg_node.value) if cfg_node is not None else {}
    new_cfg = dict(cfg)
    system_extra = None
    defs, assigns, imports = {}, {}, []
    for op in ops:
        kind = op["op"]
        if kind == "maybe_set":
            if op["key"] not in fields:
                continue
            kind = "set_config"
        elif kind == "assign" and op["name"] in fields and ("assign", op["name"]) not in spans:
            ok, val = _literal(op["code"].split("=", 1)[1])     # "rag_k = 5" inside a python block
            if not ok:
                raise EditError(f"{op['name']} = ...: write a literal value, e.g. SET {op['name']} = 5")
            op = {"op": "set_config", "key": op["name"], "value": val}
            kind = "set_config"
        if kind == "set_config":
            key = op["key"]
            if not isinstance(key, str):
                raise EditError(f"CONFIG key must be a string, got {key!r}")
            val = op["value"]
            if op.get("raw") and fields.get(key) is not str:
                raise EditError(f"SET {key}: cannot read the value {val!r}")
            new_cfg[key] = check_value(key, val, cfg.get(key), fields)
        elif kind == "set_system_extra":
            if not isinstance(op["text"], str):
                raise EditError("SYSTEM_EXTRA must be a string")
            if len(op["text"]) > MAX_SYSTEM_EXTRA:
                raise EditError(f"SYSTEM_EXTRA is longer than {MAX_SYSTEM_EXTRA} characters")
            system_extra = op["text"]
        elif kind == "def":
            defs[op["name"]] = op["code"]
        elif kind == "assign":
            assigns[op["name"]] = op["code"]
        elif kind == "import":
            imports.append(op["code"])

    lines = src.splitlines()
    edits = []     # (start_line, end_line, new_text) with 1-based inclusive lines; insert when end < start
    if new_cfg != cfg:
        if cfg_node is None:
            raise EditError("the policy file has no CONFIG to change")
        edits.append((cfg_node.lineno, cfg_node.end_lineno, render_config(new_cfg)))
    if system_extra is not None:
        text = "SYSTEM_EXTRA = " + json.dumps(system_extra, ensure_ascii=False)
        if ("assign", "SYSTEM_EXTRA") in spans:
            a, b = spans[("assign", "SYSTEM_EXTRA")]
            edits.append((a, b, text))
        else:
            edits.append((len(lines) + 1, len(lines), "\n" + text))
    first_def = min([a for (k, _), (a, _) in spans.items() if k == "def"] or [len(lines) + 1])
    for kind, table in (("assign", assigns), ("def", defs)):
        for name, code in table.items():
            if (kind, name) in spans:
                a, b = spans[(kind, name)]
                edits.append((a, b, code))
            else:     # a new helper or constant: before the first function, so the file reads top-down
                edits.append((first_def, first_def - 1, code + "\n\n"))
    existing = {l.strip() for l in lines}
    new_imports = [c for c in imports if c.strip() not in existing]
    if new_imports:
        at = spans.get(("last_import", None))
        pos = at[1] + 1 if at else (cfg_node.lineno if cfg_node is not None else 1)
        edits.append((pos, pos - 1, "\n".join(new_imports) + ("\n" if not at else "")))

    # apply bottom-up; overlapping replacements would be a bug in the ops
    edits.sort(key=lambda e: (e[0], e[1]), reverse=True)
    for a, b, text in edits:
        lines[a - 1:b] = text.split("\n")
    out = "\n".join(lines).rstrip("\n") + "\n"
    try:
        ast.parse(out)
    except SyntaxError as e:
        raise EditError(f"the edited file has a syntax error: {e.msg} (line {e.lineno})")
    return out


def apply_reply(champion, reply, fields=None):
    """reply text -> (candidate source, change). Raises EditError with a reason for the proposer."""
    change, ops = parse(reply)
    if not ops:
        raise EditError("no edits found: use SET <key> = <value>, SYSTEM_EXTRA = \"...\", "
                        "or a ```python block with a new prepare/finalize")
    return apply(champion, ops, fields), change or "(no CHANGE line)"


def compact(source, width=100):
    """The champion as shown to the proposer in edit mode: CONFIG packed onto a few lines."""
    tree, _ = _top_level(source)
    node = next((nd for nd in tree.body if isinstance(nd, ast.Assign) and len(nd.targets) == 1
                 and isinstance(nd.targets[0], ast.Name) and nd.targets[0].id == "CONFIG"), None)
    if node is None:
        return source
    cfg = ast.literal_eval(node.value)
    rows, cur = [], ""
    for k, v in cfg.items():
        item = f"{k}={_py(v)}"
        if cur and len(cur) + len(item) + 2 > width:
            rows.append(cur)
            cur = ""
        cur = f"{cur}, {item}" if cur else item
    if cur:
        rows.append(cur)
    lines = source.splitlines()
    body = [l for l in lines[:node.lineno - 1] if not l.startswith("#")]
    shown = "\n".join(body).strip("\n")
    shown = (shown + "\n" if shown else "") + "CONFIG:\n" + "\n".join("  " + r for r in rows)
    return shown + "\n" + "\n".join(lines[node.end_lineno:]).rstrip() + "\n"
