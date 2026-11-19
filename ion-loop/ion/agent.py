"""A small tool-using agent. Everything that the improvement loop may change lives in Config."""
import re
from dataclasses import dataclass, field, asdict

from . import llm
from .tools import TOOLS, reference_notes

BASE_PROMPT = "You are Small ion, a helpful assistant. Answer in Hebrew, as briefly as possible."

TOOL_PROMPT = """You may use tools, but only when needed. If you already know the answer, just answer directly in Hebrew.
To call a tool reply with exactly one line:
TOOL: <name> | <input>
The only tools that exist:
{tools}
After you get the tool result, either call another tool or give the final answer as one line:
ANSWER: <short final answer in Hebrew>"""

FEWSHOT = {
    "calc": """User: כמה זה 123 כפול 456?
Assistant: TOOL: calc | 123*456
User: RESULT: 56088
Assistant: ANSWER: 56088""",
    "web_search": """User: באיזו שנה נולד אלברט איינשטיין?
Assistant: TOOL: web_search | אלברט איינשטיין
User: RESULT: [אלברט איינשטיין] ... נולד ב-14 במרץ 1879 ...
Assistant: ANSWER: 1879""",
}

PLAN_PROMPT = ("Before acting, think: which facts or numbers are missing, and which tool gets each one. "
               "Never guess a fact or compute in your head when a tool can do it.")

DOC_HINT = "A long document is attached. Only its beginning is shown; use doc_search to find details inside it."


@dataclass
class Config:
    tools: list = field(default_factory=list)
    fewshot: bool = False
    plan: bool = False
    verify: bool = False
    max_steps: int = 4
    doc_chars: int = 2500     # how much of an attached document is inlined
    auto_rag: bool = False    # retrieve passages for the question up front instead of inlining the head
    auto_web: bool = False    # harness looks the question up and attaches reference notes
    tool_guard: bool = False  # offer calc only when the question itself contains big numbers
    temperature: float = 0.0

    def key(self):
        return repr(sorted(asdict(self).items()))


def _system(cfg, has_doc, tools):
    parts = [BASE_PROMPT]
    if tools:
        parts.append(TOOL_PROMPT.format(tools="\n".join("- " + TOOLS[t][1] for t in tools)))
        if cfg.plan:
            parts.append(PLAN_PROMPT)
        ex = [FEWSHOT[t] for t in tools if t in FEWSHOT]
        if cfg.fewshot and ex:
            parts.append("Examples:\n" + "\n".join(ex))
        if has_doc and "doc_search" in tools and not cfg.auto_rag:
            parts.append(DOC_HINT)
    return "\n\n".join(parts)


_TOOL = re.compile(r"TOOL:\s*([a-z_]+)\s*\|\s*(.+)", re.I)
_ANS = re.compile(r"ANSWER:\s*(.+)", re.I | re.S)


def _nums(s):
    return set(re.findall(r"\d+", s.replace(",", "")))


def run(question, cfg, doc=None):
    """Returns (answer, trace)."""
    user = question
    if doc and cfg.auto_rag:
        user = (f"Relevant passages from a long document:\n{TOOLS['doc_search'][0](question, {'doc': doc})}"
                f"\n\nQuestion: {question}")
    elif doc:
        user = f"Document:\n{doc[:cfg.doc_chars]}\n\nQuestion: {question}"
    if cfg.auto_web and not doc:
        notes = reference_notes(question)
        if notes:
            user = (f"Reference notes from an encyclopedia (they may be irrelevant; ignore them if they do not help):\n"
                    f"{notes}\n\nQuestion: {question}")
    tools = list(cfg.tools)
    if cfg.tool_guard and "calc" in tools and len(re.findall(r"\d{3,}", question)) < 2:
        tools.remove("calc")
    msgs = [{"role": "system", "content": _system(cfg, bool(doc), tools)},
            {"role": "user", "content": user}]
    trace, evidence, nudged, seen = [], user, False, set()
    ctx = {"doc": doc}
    for _ in range(cfg.max_steps):
        try:
            out = llm.chat(msgs, temperature=cfg.temperature)
        except RuntimeError as e:      # context overflow etc.
            trace.append(("error", str(e)[:200]))
            return "", trace
        trace.append(("model", out))
        m = _TOOL.search(out) if tools else None
        a = _ANS.search(out)
        if m and (not a or m.start() < a.start()):
            name, arg = m.group(1).lower(), m.group(2).split("\n")[0].strip()
            if name not in tools:
                res = f"no such tool '{name}'. Answer directly: ANSWER: ..."
            elif (name, arg) in seen:
                res = "you already have this result. Give the final answer now: ANSWER: ..."
            else:
                res = TOOLS[name][0](arg, ctx)[:900]
            seen.add((name, arg))
            evidence += " " + res
            trace.append(("tool", f"{name}({arg}) -> {res}"))
            msgs += [{"role": "assistant", "content": f"TOOL: {name} | {arg}"},
                     {"role": "user", "content": f"RESULT: {res}"}]
            continue
        ans = (a.group(1) if a else out).strip()
        # verify: a real check, not self-reflection — numbers in the answer must come from tool output
        if cfg.verify and tools and not nudged:
            unsupported = _nums(ans) - _nums(evidence)
            if unsupported:
                nudged = True
                msgs += [{"role": "assistant", "content": out},
                         {"role": "user", "content":
                          "CHECK FAILED: the number in your answer does not appear in any tool result. "
                          "Use a tool to get or compute it (TOOL: ...), then answer."}]
                trace.append(("verify", f"unsupported numbers {sorted(unsupported)}"))
                continue
        return ans, trace
    return "", trace
