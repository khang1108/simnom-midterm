"""Rows that are already paired: `pairs.csv` / `pairs.jsonl` with `img_id, sentence_id, ch_txt, vi_txt[, kind]`.

`fill_text_diff` recomputes `text_diff` of every row with the same rules as `align_book`; use it after a human fixed
the pairing or the text, or when the sentences were paired by another tool. `kind` (`1-1` by default, or `1-n`,
`n-1`, `n-m`) decides whether the row may get a diff: merged rows are `null` (they are translations, not readings).
"""

from __future__ import annotations

import csv
import json
from pathlib import Path

from .align import Row, decide_diff
from .config import NomAlignConfig
from .ranges import Ranges
from .readings import ReadingTable
from .suggest import Suggester
from .tableio import read_csv
from .tokens import nfc

REQUIRED = ("img_id", "sentence_id", "ch_txt", "vi_txt")
KINDS = ("1-1", "1-n", "n-1", "n-m")


def _one_line(s: str) -> str:
    return " ".join(nfc(s).replace("\r", " ").replace("\n", " ").split())


def _row(rec: dict, where: str) -> Row:
    missing = [c for c in REQUIRED if c not in rec or rec[c] is None]
    if missing:
        raise ValueError(f"{where}: missing {missing}")
    kind = (rec.get("kind") or "1-1").strip()
    if kind not in KINDS:
        raise ValueError(f"{where}: kind must be one of {KINDS}, got {kind!r}")
    return Row(
        rec["img_id"],
        rec["sentence_id"],
        _one_line(rec["ch_txt"]),
        _one_line(rec["vi_txt"]),
        None,
        kind,
    )


def read_pairs(path: str | Path) -> list[Row]:
    p = Path(path)
    if not p.is_file():
        raise ValueError(f"pairs file not found: {p}")
    if p.suffix.lower() in (".jsonl", ".ndjson"):
        out = []
        for n, line in enumerate(p.read_text(encoding="utf-8-sig").splitlines(), 1):
            if line.strip():
                try:
                    out.append(_row(json.loads(line), f"{p}:{n}"))
                except json.JSONDecodeError as exc:
                    raise ValueError(f"{p}:{n}: bad JSON ({exc})") from None
        return out
    with p.open(encoding="utf-8-sig", newline="") as f:
        rd = csv.DictReader(f)
        cols = rd.fieldnames or []
        missing = [c for c in REQUIRED if c not in cols]
        if missing:
            raise ValueError(f"{p}: missing columns {missing}")
        return [_row(rec, f"{p}:{n}") for n, rec in enumerate(rd, 2)]


def fill_text_diff(
    rows: list[Row],
    table: ReadingTable,
    cfg: NomAlignConfig | None = None,
    ranges: Ranges | None = None,
    suggester: Suggester | None = None,
) -> tuple[list[Row], dict]:
    """Rows with `text_diff` set (the input rows are not changed) and the report counters. Without a Nom stream
    there is no second OCR here: suggestions come from the similar table only."""
    cfg = cfg or NomAlignConfig()
    meaning = ranges.resolve(rows, list(dict.fromkeys(r.img_id for r in rows))) if ranges else set()
    unknown: dict[str, int] = {}
    stats: dict = {}
    out = []
    for k, r in enumerate(rows):
        diff, phon, unk = decide_diff(
            r.ch_txt, r.vi_txt, r.kind, table, cfg, k in meaning, suggester, None, 0, stats
        )
        for u in unk:
            unknown[u] = unknown.get(u, 0) + 1
        out.append(Row(r.img_id, r.sentence_id, r.ch_txt, r.vi_txt, diff, r.kind, r.vi_img, phon))
    stats.pop("low_match_rows", None)
    return out, {"unknown_chars": unknown, "meaning_rows": len(meaning), "mode": cfg.mode, **stats}


def keep_reviewed(rows: list[Row], old_csv: str | Path) -> int:
    """Copy `reviewed` from an earlier CSV to every equal `warn` element (same sentence_id, positions, texts,
    type). Returns how many elements kept their mark."""
    from .validate import parse_diff

    old: dict[tuple, int] = {}
    for rec in read_csv(old_csv):
        try:
            diff = parse_diff(rec["text_diff"])
        except ValueError:
            continue
        for el in diff or []:
            if el.get("type") == "warn" and el.get("reviewed"):
                old[(rec["sentence_id"], _sig(el))] = el["reviewed"]
    kept = 0
    for r in rows:
        for el in r.text_diff or []:
            if el["type"] == "warn" and (r.sentence_id, _sig(el)) in old:
                el["reviewed"] = old[(r.sentence_id, _sig(el))]
                kept += 1
    return kept


def _sig(el: dict) -> str:
    return json.dumps(
        [el.get(k) for k in ("nom_pos", "nom_sub_text", "vi_pos", "vi_sub_text", "type")]
    )
