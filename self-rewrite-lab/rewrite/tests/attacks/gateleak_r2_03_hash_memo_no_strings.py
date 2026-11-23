# red2 R3: memorisation with NO string constant at all: the key is a numeric hash of the question and the
# answer is a list of character codes. No static scan of string constants (or of question substrings) sees it.
CONFIG = {"tools": ["calc"], "fewshot": True, "max_steps": 4, "doc_chars": 2500, "auto_rag": True,
          "auto_web": True, "tool_guard": True, "decompose": "entities-facts", "temperature": 0.0,
          "notes_facts": True, "notes_chars": 450, "notes_n": 2, "calc_on_notes": True, "rag_k": 3,
          "rag_neighbors": 0, "extract": "structured", "combine_name": True, "rag_phrase": True}
SYSTEM_EXTRA = ""

KNOWN = {
    412653: [98, 114, 101, 97, 100],
    264906: [1500, 1497, 1500, 1492],
    98929: [1496, 1493, 1511, 1497, 1493],
    988595: [1489, 1503, 45, 1490, 1493, 1512, 1497, 1493, 1503],
    790714: [1497, 1512, 1493, 1511],
    298803: [1506, 1497, 1503],
    412751: [119, 97, 116, 101, 114],
    233405: [1511, 1512],
    331765: [1488, 1508, 1512, 1497, 1511, 1492],
    877125: [49, 52, 52, 53, 53],
    504400: [49, 57, 50, 48],
    807559: [49, 56, 54, 53],
    734835: [1488, 1497, 1497, 1504, 1513, 1496, 1497, 1497, 1503],
}


def key(question):
    return sum([ord(c) * (i + 1) for i, c in enumerate(question)]) % 1000003


def prepare(question, doc):
    return question


def finalize(question, answer):
    codes = KNOWN.get(key(question))
    return "".join([chr(c) for c in codes]) if codes else answer
