"""A small tool-using agent. Everything that the improvement loop may change lives in Config."""
import re
from dataclasses import dataclass, field, asdict

from . import llm
from .tools import TOOLS, reference_hits, reference_notes

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
    decompose: str = ""       # "llm": the model splits the question; "entities": the harness splits by retrieved articles
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


def _solve(question, cfg, doc=None, notes=None, force_tools=None):
    """One agent episode. Returns (answer, trace)."""
    user = question
    if doc and cfg.auto_rag:
        user = (f"Relevant passages from a long document:\n{TOOLS['doc_search'][0](question, {'doc': doc})}"
                f"\n\nQuestion: {question}")
    elif doc:
        user = f"Document:\n{doc[:cfg.doc_chars]}\n\nQuestion: {question}"
    if notes:
        user = (f"Reference notes from an encyclopedia (they may be irrelevant; ignore them if they do not help):\n"
                f"{notes}\n\nQuestion: {question}")
    tools = list(cfg.tools) if force_tools is None else list(force_tools)
    if force_tools is None and cfg.tool_guard and "calc" in tools and len(re.findall(r"\d{3,}", question)) < 2:
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


DECOMPOSE = """Some questions need two separate facts, for example comparing two people or two places.
If so, write the two simple questions, one per line, in Hebrew. If the question is already simple, reply exactly: NONE
Examples:
Q: בכמה שנים מבוגר משה מאהרן?
באיזו שנה נולד משה?
באיזו שנה נולד אהרן?
Q: כמה שנים עברו בין ייסוד חיפה לייסוד עכו?
באיזו שנה נוסדה חיפה?
באיזו שנה נוסדה עכו?
Q: מהי בירת ספרד?
NONE"""


def _words(s):
    return {w for w in re.findall(r"[^\W_]+", s.lower()) if len(w) >= 4 or w.isdigit()}


def grounded(answer, notes, question):
    """An answer drawn from the notes must literally be in them: at least half of its new content words."""
    if len(answer.split()) > 12:      # a wholesale copy of the note is not an answer
        return False
    new = _words(answer) - _words(question)
    return bool(new) and sum(w in notes.lower() for w in new) >= len(new) / 2


def _lookup(question, cfg):
    """Answer directly, and again with retrieved notes; trust the notes-based answer only if it is grounded."""
    notes = reference_notes(question) if cfg.auto_web else ""
    a0, t0 = _solve(question, cfg)
    if not notes:
        return a0, t0
    a1, t1 = _solve(question, cfg, notes=notes)
    ok = grounded(a1, notes, question)
    return (a1 if ok else a0), t0 + [("notes", notes[:300])] + t1 + [("grounded", str(ok))]


def _combine(question, facts, cfg, trace):
    final = "Known facts:\n" + "\n".join(facts) + f"\n\nUsing these facts, answer: {question}"
    a, t = _solve(final, cfg, force_tools=[x for x in cfg.tools if x == "calc"])
    return a, trace + [("facts", "\n".join(facts))] + t


def run(question, cfg, doc=None):
    """Returns (answer, trace)."""
    if doc:
        return _solve(question, cfg, doc=doc)
    if cfg.decompose == "llm":
        try:
            out = llm.chat([{"role": "system", "content": DECOMPOSE},
                            {"role": "user", "content": "Q: " + question}], max_tokens=80)
        except RuntimeError:
            out = "NONE"
        subs = [l.strip() for l in out.splitlines() if l.strip().endswith("?")][:2]
        if len(subs) == 2 and "NONE" not in out:
            trace, facts = [("plan", out)], []
            for q in subs:
                a, t = _lookup(q, cfg)
                facts.append(f"- {q} {a}")
                trace += t
            return _combine(question, facts, cfg, trace)
    if cfg.decompose == "entities" and cfg.auto_web:
        hits = reference_hits(question)
        tw = [set(re.findall(r"[^\W_]+", h["title"])) for h in hits]
        # two different things are named in the question → one fact from each, then combine
        if len(hits) == 2 and not (tw[0] & tw[1]):
            trace, facts = [("plan", "entities: " + " | ".join(h["title"] for h in hits))], []
            for h in hits:
                a, t = _solve(f"Note about {h['title']}: {h['text']}\n\nWhich single fact about {h['title']} from this "
                              f"note is needed for the question: {question}\nReply with that fact only "
                              f"(for example just a year).", Config())
                facts.append(f"- {h['title']}: {a[:80]}")
                trace += t
            return _combine(question, facts, cfg, trace)
    return _lookup(question, cfg)
