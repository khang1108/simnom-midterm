"""`<book>.csv` (UTF-8 with BOM) and `<book>.xlsx` (coloured runs). The CSV `text_diff` is the official one."""

from __future__ import annotations

import csv
import json
from collections.abc import Iterable
from pathlib import Path

from openpyxl import Workbook
from openpyxl.cell.rich_text import CellRichText, TextBlock
from openpyxl.cell.text import InlineFont
from openpyxl.styles import Font

from .config import NomAlignConfig

COLUMNS = ["img_id", "sentence_id", "ch_txt", "vi_txt", "text_diff"]
BLACK, RED, YELLOW = 0, 1, 2


def dump_diff(diff: list[dict] | None) -> str:
    return "null" if diff is None else json.dumps(diff, ensure_ascii=False, separators=(",", ":"))


def _one_line(s: str) -> str:
    return " ".join(s.replace("\r", " ").replace("\n", " ").split())


def row_cells(row) -> list[str]:
    return [
        row.img_id,
        row.sentence_id,
        _one_line(row.ch_txt),
        _one_line(row.vi_txt),
        dump_diff(row.text_diff),
    ]


def write_csv(rows: Iterable, path: str | Path) -> Path:
    p = Path(path)
    with p.open("w", encoding="utf-8-sig", newline="") as f:
        w = csv.writer(f)
        w.writerow(COLUMNS)
        for r in rows:
            w.writerow(row_cells(r))
    return p


def read_csv(path: str | Path) -> list[dict[str, str]]:
    with Path(path).open(encoding="utf-8-sig", newline="") as f:
        return list(csv.DictReader(f))


def states(text: str, side: str, diff: list[dict] | None) -> list[int]:
    """Colour state of every character of a cell: black, red (error) or yellow (warn)."""
    st = [BLACK] * len(text)
    for el in diff or []:
        for a, b in el.get(f"{side}_pos", []):
            for k in range(a, min(b, len(text))):
                st[k] = RED if el["type"] == "error" else YELLOW
    return st


def _rich(text: str, st: list[int], cfg: NomAlignConfig):
    if not any(st):
        return text
    color = {RED: cfg.error_color, YELLOW: cfg.warn_color}
    parts, k = [], 0
    while k < len(text):
        e = k
        while e < len(text) and st[e] == st[k]:
            e += 1
        seg = text[k:e]
        parts.append(seg if st[k] == BLACK else TextBlock(InlineFont(color=color[st[k]]), seg))
        k = e
    return CellRichText(*parts)


def _write(rows: Iterable, path: str | Path, cfg: NomAlignConfig) -> Path:
    wb = Workbook()
    ws = wb.active
    ws.title = "align"
    ws.append(COLUMNS)
    for c in ws[1]:
        c.font = Font(bold=True)
    for r in rows:
        cells = row_cells(r)
        ws.append(cells)
        n = ws.max_row
        diff = r.text_diff
        ws.cell(n, 3).value = _rich(cells[2], states(cells[2], "nom", diff), cfg)
        ws.cell(n, 4).value = _rich(cells[3], states(cells[3], "vi", diff), cfg)
    for col, w in zip("ABCDE", (24, 24, 40, 50, 50), strict=True):
        ws.column_dimensions[col].width = w
    ws.freeze_panes = "A2"
    p = Path(path)
    wb.save(p)
    return p


def write_xlsx(rows: Iterable, path: str | Path, cfg: NomAlignConfig | None = None) -> Path:
    return _write(rows, path, cfg or NomAlignConfig())


class _CsvRow:
    """A row read back from a CSV: the stored `text_diff` is used as it is, never recomputed."""

    def __init__(self, rec: dict[str, str]) -> None:
        from .validate import parse_diff

        self.img_id, self.sentence_id = rec["img_id"], rec["sentence_id"]
        self.ch_txt, self.vi_txt = rec["ch_txt"], rec["vi_txt"]
        self.text_diff = parse_diff(rec["text_diff"])


def render_xlsx(
    csv_path: str | Path, xlsx_path: str | Path, cfg: NomAlignConfig | None = None
) -> Path:
    """The XLSX of a (hand-fixed) CSV: colours come from its `text_diff`; nothing is recomputed."""
    return _write([_CsvRow(r) for r in read_csv(csv_path)], xlsx_path, cfg or NomAlignConfig())


__all__ = [
    "COLUMNS",
    "dump_diff",
    "read_csv",
    "render_xlsx",
    "row_cells",
    "states",
    "write_csv",
    "write_xlsx",
]
