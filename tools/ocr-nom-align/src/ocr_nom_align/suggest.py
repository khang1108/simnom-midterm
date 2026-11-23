"""Suggestions for a Nom character that does not read its syllable: from a second OCR text or a similar-character table.

A suggestion never changes the alignment or the text: it only turns a red pair into a yellow `warn` element that
carries `suggest` / `suggest_by`, to be accepted (`apply`) or rejected before submission.
"""

from __future__ import annotations

import ast
import csv
from pathlib import Path

from .lev import edit_script
from .readings import ReadingTable
from .tokens import nfc

INPUT_COL = "Input Character"
SIMILAR_COL = "Top 20 Similar Characters"


class SimilarTable:
    """`char -> [similar chars]`, most similar first; the list order is the rank."""

    def __init__(self, data: dict[str, list[str]] | None = None) -> None:
        self.data = data or {}
        self.parse_errors = 0

    @classmethod
    def load(cls, path: str | Path) -> SimilarTable:
        p = Path(path)
        if not p.is_file():
            raise ValueError(f"similar table not found: {p}")
        t = cls()
        with p.open(encoding="utf-8-sig", newline="") as f:
            rd = csv.DictReader(f)
            cols = [c.strip() for c in rd.fieldnames or []]
            if INPUT_COL not in cols or SIMILAR_COL not in cols:
                raise ValueError(
                    f"{p}: needs the columns {INPUT_COL!r} and {SIMILAR_COL!r}, got {cols}"
                )
            for rec in rd:
                rec = {k.strip(): v for k, v in rec.items() if k}
                ch = nfc((rec.get(INPUT_COL) or "").strip())
                if not ch:
                    continue
                try:
                    found = ast.literal_eval((rec.get(SIMILAR_COL) or "").strip() or "[]")
                    if not isinstance(found, list | tuple):
                        raise ValueError
                    t.data[ch] = [nfc(str(c)) for c in found]
                except (ValueError, SyntaxError):
                    t.parse_errors += 1
                    t.data[ch] = []
        return t

    def similar(self, ch: str) -> list[str]:
        return self.data.get(ch, [])


class Suggester:
    def __init__(self, table: ReadingTable, similar: SimilarTable | None = None) -> None:
        self.table, self.similar = table, similar or SimilarTable()

    def suggest(
        self, char: str, syllable: str, fb_char: str | None = None
    ) -> tuple[str, str] | None:
        """`(character, "fallback" | "similar")`: the second-OCR character if it reads the syllable, else the first
        similar character (by rank, so the answer never depends on hashing) that does."""
        key = self.table.key(syllable)
        if fb_char and fb_char != char and key in self.table.readings(fb_char):
            return fb_char, "fallback"
        for c in self.similar.similar(char):
            if c != char and key in self.table.readings(c):
                return c, "similar"
        return None


def align_fallback(primary: str, fb: str, max_dist: float) -> dict[int, str] | None:
    """`{offset in primary: fallback character}` at the substituted positions of an edit-distance alignment (ties:
    pair, then delete, then insert). `None` when the two texts are too different (distance / primary length > `max_dist`)."""
    if not primary or not fb:
        return None
    cost, ops = edit_script(primary, fb, lambda a, b: 0.0 if a == b else 1.0, 1.0, tie="diag")
    if cost / len(primary) > max_dist:
        return None
    return {i: fb[j] for op, i, j in ops if op == "s" and primary[i] != fb[j]}


def fallback_map(
    nom_chunks: list[tuple[str, list[str]]], fb_pages: dict[str, list[str]], max_dist: float
) -> tuple[dict[int, str], list[str]]:
    """Per image: align its cleaned Nom stream with the second OCR's. Returns `({book offset: char}, skipped images)`;
    `nom_chunks` is `[(image, cleaned lines)]` in the order of the Nom stream, so offsets match `join_nom`."""
    out: dict[int, str] = {}
    skipped: list[str] = []
    base = 0
    for img, lines in nom_chunks:
        prim = "".join(lines)
        if prim:
            fb_lines = fb_pages.get(img)
            fb = "".join("".join(nfc(x).split()) for x in fb_lines) if fb_lines is not None else ""
            m = align_fallback(prim, fb, max_dist) if fb else None
            if m is None:
                skipped.append(img)
            else:
                out.update({base + i: c for i, c in m.items()})
        base += len(prim)
    return out, skipped


__all__ = ["SimilarTable", "Suggester", "align_fallback", "fallback_map"]
