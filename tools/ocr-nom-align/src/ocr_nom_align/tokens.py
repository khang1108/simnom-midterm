"""Tokens of one cell: Sino-Nom characters and Vietnamese syllables, with code-point positions.

Positions are indices into the exact NFC string of the cell (code points, not bytes, not UTF-16),
so Nom characters from the extension planes count as one. `[MASK]` is six characters, never a token.
"""

from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass
from functools import lru_cache

MASK = "[MASK]"
PLACEHOLDER = "〓"  # 〓: a Nom character that is in no font; always red
TONE_MARKS = frozenset({"̀", "́", "̃", "̉", "̣"})
_HAN = (
    (0x3400, 0x4DBF),  # extension A
    (0x4E00, 0x9FFF),  # unified ideographs
    (0xF900, 0xFAFF),  # compatibility ideographs
    (0x20000, 0x323AF),  # extensions B-H
)
_PUA = ((0xE000, 0xF8FF), (0xF0000, 0xFFFFD))  # Nom fonts store characters here
VARIATION_SELECTORS = frozenset(chr(c) for c in (*range(0xFE00, 0xFE10), *range(0xE0100, 0xE01F0)))
_VI_TOKEN = re.compile(r"\d+|[^\W\d_]+")


@dataclass(frozen=True)
class Tok:
    text: str  # one Nom character, or one syllable / number as written
    start: int  # code-point index in the cell, inclusive
    end: int  # code-point index in the cell, exclusive
    kind: str  # "han" | "syl" | "num"


def has_selector(text: str) -> bool:
    return any(c in VARIATION_SELECTORS for c in text)


def nfc(s: str) -> str:
    return unicodedata.normalize("NFC", s)


def is_han(ch: str) -> bool:
    cp = ord(ch)
    return any(a <= cp <= b for a, b in _HAN) or any(a <= cp <= b for a, b in _PUA)


def is_nom_char(ch: str) -> bool:
    """A character that counts as one Nom character: Han, Nom (private use) or the placeholder 〓."""
    return ch == PLACEHOLDER or is_han(ch)


def is_letter_char(ch: str) -> bool:
    """A character allowed at the edge of a `pos` range: a letter of either script, a digit or 〓."""
    return is_nom_char(ch) or unicodedata.category(ch)[0] in "LMN"


@lru_cache(maxsize=65536)
def syllable_key(y: str) -> str:
    """Comparison form: NFC, lower-case, the five tone marks removed. Keeps breve, circumflex, horn, `đ`."""
    s = unicodedata.normalize("NFD", unicodedata.normalize("NFC", y).lower())
    return unicodedata.normalize("NFC", "".join(c for c in s if c not in TONE_MARKS))


def mask_spans(text: str) -> list[tuple[int, int]]:
    """The text between `[MASK]` markers, as `(start, end)` spans (empty spans kept: they pair up by index)."""
    out, pos = [], 0
    while True:
        k = text.find(MASK, pos)
        if k < 0:
            out.append((pos, len(text)))
            return out
        out.append((pos, k))
        pos = k + len(MASK)


def nom_tokens(text: str, start: int = 0, end: int | None = None) -> list[Tok]:
    end = len(text) if end is None else end
    return [Tok(text[i], i, i + 1, "han") for i in range(start, end) if is_nom_char(text[i])]


def vi_tokens(text: str, start: int = 0, end: int | None = None) -> list[Tok]:
    end = len(text) if end is None else end
    out = []
    for m in _VI_TOKEN.finditer(text, start, end):
        out.append(Tok(m.group(), m.start(), m.end(), "num" if m.group()[0].isdigit() else "syl"))
    return out


def count_nom(s: str) -> int:
    """Nom characters of a string, `[MASK]` excluded."""
    return sum(len(nom_tokens(s, a, b)) for a, b in mask_spans(s))


def count_vi(s: str) -> int:
    """Syllables (and numbers) of a string, `[MASK]` excluded."""
    return sum(len(vi_tokens(s, a, b)) for a, b in mask_spans(s))


__all__ = [
    "MASK", "PLACEHOLDER", "TONE_MARKS", "VARIATION_SELECTORS", "Tok", "count_nom", "count_vi", "has_selector", "is_han", "is_letter_char",
    "is_nom_char", "mask_spans", "nfc", "nom_tokens", "syllable_key", "vi_tokens",
]  # fmt: skip
