"""Sentence splitting. Punctuation is a hint, not a certainty: the DP in `align.py` repairs a wrong split by merging."""

from __future__ import annotations

from collections.abc import Callable

from .tokens import count_nom, count_vi

NOM_END = "。！？；：!?;:"
VI_END = ".?!;:…"
CLOSERS = "」』”’）】》〉)]\"'"
ABBREVIATIONS = frozenset(
    {
        "tp",
        "st",
        "mr",
        "mrs",
        "ms",
        "dr",
        "ts",
        "gs",
        "pgs",
        "ths",
        "vv",
        "tr",
        "ng",
        "q",
        "p",
        "h",
        "x",
    }
)


def _spans_from_bounds(text: str, bounds: list[int]) -> list[tuple[int, int]]:
    out, prev = [], 0
    for b in [*bounds, len(text)]:
        a, e = prev, b
        while a < e and text[a].isspace():
            a += 1
        while e > a and text[e - 1].isspace():
            e -= 1
        if e > a:
            out.append((a, e))
        prev = b
    return out


def _absorb(text: str, i: int, terminators: str) -> int:
    """Index after the terminator at `i`, its repeats and the closing quotes / brackets that follow."""
    j = i + 1
    while j < len(text) and (text[j] in terminators or text[j] in CLOSERS):
        j += 1
    return j


def _word_before(text: str, i: int) -> str:
    j = i
    while j > 0 and (text[j - 1].isalnum() or text[j - 1] == "-"):
        j -= 1
    return text[j:i]


def _next_char(text: str, j: int) -> str:
    while j < len(text) and text[j].isspace():
        j += 1
    return text[j] if j < len(text) else ""


def _bounds_nom(text: str) -> list[int]:
    out, i = [], 0
    while i < len(text):
        if text[i] in NOM_END:
            i = _absorb(text, i, NOM_END)
            out.append(i)
        else:
            i += 1
    return out


def _bounds_vi(text: str) -> list[int]:
    out, i = [], 0
    while i < len(text):
        c = text[i]
        if c in VI_END:
            j = _absorb(text, i, VI_END)
            nxt_ok = j >= len(text) or text[j].isspace()
            if c == "." and nxt_ok:
                w = _word_before(text, i)
                nxt = _next_char(text, j)
                if (len(w) == 1 and w.isalpha()) or w.lower() in ABBREVIATIONS:
                    nxt_ok = False  # initial or abbreviation: `A. Rô`, `Tp. Huế`
                elif nxt and nxt.islower():
                    nxt_ok = False  # `v.v. và`, ordinal: not a sentence start
            if nxt_ok:
                out.append(j)
            i = j
        else:
            i += 1
    return out


def _merge_short(
    text: str, spans: list[tuple[int, int]], count: Callable[[str], int], below: int
) -> list[tuple[int, int]]:
    """A span with fewer than `below` tokens joins the previous span (the next one at the start). 0: no merge."""
    if below <= 0:
        return spans
    out: list[tuple[int, int]] = []
    pending_start: int | None = None
    for a, b in spans:
        if pending_start is not None:
            a, pending_start = pending_start, None
        if count(text[a:b]) < below:
            if out:
                out[-1] = (out[-1][0], b)
            else:
                pending_start = a
            continue
        out.append((a, b))
    if pending_start is not None and spans:  # all spans were short
        out.append((pending_start, spans[-1][1]))
    return out


def _split(text, bounds, count, merge_below, warn_below):
    spans = _merge_short(text, _spans_from_bounds(text, bounds), count, merge_below)
    short = [(a, b) for a, b in spans if warn_below > 0 and count(text[a:b]) < warn_below]
    return spans, short


def split_nom(text: str, merge_below: int = 0, warn_below: int = 0):
    """`(spans, short_spans)`: spans below `warn_below` tokens are only listed; below `merge_below` they are merged."""
    return _split(text, _bounds_nom(text), count_nom, merge_below, warn_below)


def split_vi(text: str, merge_below: int = 0, warn_below: int = 0):
    return _split(text, _bounds_vi(text), count_vi, merge_below, warn_below)


def apply_merges(spans: list[tuple[int, int]], merges: dict[int, str]) -> list[tuple[int, int]]:
    """Join spans by hand: `merges` is `{span index: "prev" | "next" | "keep"}`; a span joins its neighbour (chains
    of merges give one span). A `prev` on the first span or a `next` on the last one is an error."""
    n = len(spans)
    parent = list(range(n))

    def find(x: int) -> int:
        while parent[x] != x:
            parent[x] = parent[parent[x]]
            x = parent[x]
        return x

    for k, how in sorted(merges.items()):
        if how == "keep":
            continue
        if how not in ("prev", "next"):
            raise ValueError(f"merge must be keep, prev or next, got {how!r}")
        j = k - 1 if how == "prev" else k + 1
        if not 0 <= k < n or not 0 <= j < n:
            raise ValueError(f"sentence {k + 1} has no {how} neighbour to merge with")
        parent[find(k)] = find(j)
    groups: dict[int, list[int]] = {}
    for k, (a, b) in enumerate(spans):
        g = groups.setdefault(find(k), [a, b])
        g[0], g[1] = min(g[0], a), max(g[1], b)
    return [(a, b) for a, b in groups.values()]


__all__ = ["apply_merges", "split_nom", "split_vi"]
