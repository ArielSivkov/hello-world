"""Candidates per cycle: (name, target categories, mutation, prerequisite on the current config)."""


def add_tool(name):
    def f(c):
        c.tools = c.tools + [name]
    return f


def set_(k, v):
    def f(c):
        setattr(c, k, v)
    return f


def both(*fs):
    def f(c):
        for g in fs:
            g(c)
    return f


ANY = lambda c: True                      # noqa: E731
TOOLS = lambda c: bool(c.tools)           # noqa: E731
ALL = ["basic", "calc", "web", "multistep", "longdoc"]

CYCLES = {
    # Cycle 1 — do the findings from the small arena hold on the larger one?
    1: [
        ("tool:calc", ["calc"], add_tool("calc"), lambda c: "calc" not in c.tools),
        ("tool:calc+guard", ["calc"], both(add_tool("calc"), set_("tool_guard", True)), lambda c: "calc" not in c.tools),
        ("rag:auto", ["longdoc"], set_("auto_rag", True), ANY),
        ("reflex:web_notes", ["web", "multistep"], set_("auto_web", True), ANY),
        ("tool:web_search", ["web", "multistep"], add_tool("web_search"), lambda c: not c.auto_web),
        ("loop:decompose-llm", ["multistep"], set_("decompose", "llm"), lambda c: c.auto_web and not c.decompose),
        ("loop:decompose-entities", ["multistep"], set_("decompose", "entities"), lambda c: c.auto_web and not c.decompose),
        ("prompt:fewshot", ["calc", "multistep"], set_("fewshot", True), TOOLS),
        ("loop:verify", ["multistep", "calc"], set_("verify", True), TOOLS),
        ("sampling:temp0.7", ALL, set_("temperature", 0.7), ANY),
    ],
    # Cycle 2 — decisions from cycle 1 (see JOURNAL.md)
    2: [
        ("decompose:only-dated-entities", ["basic", "multistep"], set_("decompose", "entities-dated"), ANY),
        ("notes:structured-facts", ["web", "multistep"], set_("notes_facts", True), ANY),
        ("calc:on-notes", ["multistep"], set_("calc_on_notes", True), ANY),
        ("rag:no-neighbours", ["longdoc"], set_("rag_neighbors", 0), ANY),
        ("rag:top1", ["longdoc"], set_("rag_k", 1), ANY),
        ("notes:250-chars", ["web", "basic"], set_("notes_chars", 250), ANY),
        ("notes:top1", ["web", "basic"], set_("notes_n", 1), lambda c: not c.decompose),
        ("prompt:hebrew-system", ["basic"], set_("sys_hebrew", True), ANY),
        ("prompt:brief-answer", ["basic", "web"], set_("brief", True), ANY),
        ("extract:hebrew-prompt", ["multistep"], set_("extract_hebrew", True), lambda c: bool(c.decompose)),
    ],
}
