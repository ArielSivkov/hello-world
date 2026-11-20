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
}
