from __future__ import annotations

import json
from pathlib import Path

READINGS = {
    "経": "kinh", "申": "thân", "母": "mẫu", "福": "phúc", "告": "cáo", "命": "mệnh",
    "天": "thiên", "主": "chúa", "造": "tạo", "地": "địa", "人": "nhân", "之": "chi",
    "初": "sơ", "神": "thần", "翁": "ông", "聖": "thánh",
}  # fmt: skip


def box(text: str) -> dict:
    return {"transcription": text, "points": [[0, 0], [10, 0], [10, 10], [0, 10]]}


def write_label(path: Path, pages: dict[str, list[str]], folder: str = "ch") -> Path:
    path.write_text(
        "\n".join(
            f"{folder}/{k}\t{json.dumps([box(t) for t in v], ensure_ascii=False)}"
            for k, v in pages.items()
        )
        + "\n",
        encoding="utf-8",
    )
    return path


def write_char_label(path: Path, pages: dict[str, list[str]], folder: str = "ch") -> Path:
    """A Label_char.txt: one box per character (`[MASK]` stays one box)."""
    import re

    boxes = {k: [c for s in v for c in re.findall(r"\[MASK\]|\S", s)] for k, v in pages.items()}
    return write_label(path, boxes, folder)


def make_book(tmp_path: Path, table, ch: dict, vi: dict, fb: dict | None = None, similar=None,
              names: tuple = (), mode: str = "phonetic"):  # fmt: skip
    """Run `align_book` on in-memory pages, write ch/ vi/ Label.txt and out/book.csv + .xlsx. Returns the paths."""
    from ocr_nom_align import NomAlignConfig, align_book, write_csv, write_xlsx
    from ocr_nom_align.suggest import SimilarTable, Suggester

    d = tmp_path / "book"
    for sub in ("ch", "vi", "out"):
        (d / sub).mkdir(parents=True, exist_ok=True)
    ch_l = write_label(d / "ch" / "Label.txt", ch)
    vi_l = write_label(d / "vi" / "Label.txt", vi, "vi")
    cfg = NomAlignConfig(mode=mode, names=names)
    sug = Suggester(table, SimilarTable(similar or {}))
    res = align_book(ch, vi, table, cfg, suggester=sug, fb_pages=fb)
    csv_p = write_csv(res.rows, d / "out" / "book.csv")
    xlsx_p = write_xlsx(res.rows, d / "out" / "book.xlsx", cfg)
    return {"dir": d, "ch": ch_l, "vi": vi_l, "csv": csv_p, "xlsx": xlsx_p, "res": res, "cfg": cfg}
