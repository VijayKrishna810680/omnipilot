"""Small search helpers shared by tools: tokenizing, chunking and BM25 ranking."""
from __future__ import annotations

import math
import re
from collections import Counter

_WORD = re.compile(r"[a-z0-9]+")
STOP = set("a an the is are was were be to of and or in on for with my me i you it this that at by as "
           "what which who how do does did from about".split())


def tokens(text: str) -> list[str]:
    return [w for w in _WORD.findall(text.lower()) if w not in STOP]


def chunk(text: str, size: int = 900, overlap: int = 150) -> list[str]:
    """Split text into overlapping pieces, preferring paragraph and sentence boundaries."""
    text = re.sub(r"[ \t]+", " ", text).strip()
    out, start = [], 0
    while start < len(text):
        end = min(start + size, len(text))
        if end < len(text):
            cut = max(text.rfind("\n", start + size // 2, end), text.rfind(". ", start + size // 2, end))
            if cut > start:
                end = cut + 1
        piece = text[start:end].strip()
        if piece:
            out.append(piece)
        if end >= len(text):
            break
        start = max(end - overlap, start + 1)
    return out


def bm25(query: str, docs: list[str], k1: float = 1.2, b: float = 0.75) -> list[tuple[float, int]]:
    """Return (score, index) pairs for docs matching the query, best first."""
    toks = [tokens(d) for d in docs]
    q = tokens(query)
    if not toks or not q:
        return []
    n, avg = len(toks), sum(map(len, toks)) / len(toks)
    df = Counter(w for d in toks for w in set(d))
    scored = []
    for i, d in enumerate(toks):
        tf = Counter(d)
        s = sum(math.log(1 + (n - df[w] + 0.5) / (df[w] + 0.5)) * tf[w] * (k1 + 1) /
                (tf[w] + k1 * (1 - b + b * len(d) / max(avg, 1))) for w in q if w in tf)
        if s > 0:
            scored.append((s, i))
    return sorted(scored, reverse=True)
