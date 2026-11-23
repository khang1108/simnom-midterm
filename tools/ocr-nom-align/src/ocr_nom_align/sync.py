"""`apply`: write the accepted suggestions of a CSV into `Label.txt` (Nom side), the CSV, `Label_char.txt` and the XLSX,
so that all of them stay in sync (spec: a manual fix touches every place at once).

Nothing is written unless every check passes: outputs are staged, checked with `check_diff(final=True)`, then moved
into place one file at a time (each move is atomic).
"""

from __future__ import annotations

import csv
import json
import os
import shutil
import tempfile
from pathlib import Path

from .config import NomAlignConfig
from .pages import PagePair, read_label, read_label_file, stream_origin, write_label
from .tableio import COLUMNS, dump_diff, read_csv, render_xlsx
from .tokens import nfc
from .validate import (
    _KEYS,
    _norm_nom,
    check_char_file,
    check_diff,
    check_text_sync,
    page_orders,
    parse_diff,
)


class ApplyError(Exception):
    """Something blocks `apply`; the message lists every reason. Nothing was written."""


def _write_records(records: list[dict[str, str]], path: Path) -> None:
    with path.open("w", encoding="utf-8-sig", newline="") as f:
        w = csv.writer(f)
        w.writerow(COLUMNS)
        for r in records:
            w.writerow([r[c] for c in COLUMNS])


def _to_error(el: dict) -> dict:
    out = {k: el[k] for k in _KEYS}
    out["type"] = "error"
    return out


def _box_of(boxes: list[str], pos: int) -> int | None:
    """Index of the box that holds character `pos` of the image stream (a `[MASK]` box counts six)."""
    run = 0
    for bi, raw in enumerate(boxes):
        t = "".join(nfc(raw).split())
        if run + len(t) > pos:
            return bi
        run += len(t)
    return None


def apply_suggestions(
    csv_path: str | Path,
    ch_label: str | Path,
    vi_label: str | Path,
    *,
    ch_char: str | Path | None = None,
    xlsx: str | Path | None = None,
    pairs: list[PagePair] | None = None,
    accept: str = "reviewed",
    reject_rest: bool = False,
    out_dir: str | Path | None = None,
    in_place: bool = False,
    nom_order: str = "asc",
    missing_ch: frozenset[str] = frozenset(),
    missing_vi: frozenset[str] = frozenset(),
    cfg: NomAlignConfig | None = None,
) -> dict:
    """Returns `{applied, rejected, skipped, accepted_by, rejected_by, files}`. Raises `ApplyError`."""
    cfg = cfg or NomAlignConfig()
    if accept not in ("reviewed", "all"):
        raise ApplyError("accept must be reviewed or all")
    if bool(out_dir) == bool(in_place):
        raise ApplyError("pass exactly one of --out-dir and --in-place")
    csv_path, ch_label, vi_label = Path(csv_path), Path(ch_label), Path(vi_label)
    records = read_csv(csv_path)
    ch_file = read_label_file(ch_label)
    ch_pages, vi_pages = ch_file.pages(), read_label(vi_label)
    # 1. the files must agree before anything is changed
    errs, _ = check_text_sync(
        records, ch_pages, vi_pages, pairs, cfg, missing_ch, missing_vi, nom_order
    )
    if errs:
        raise ApplyError("\n".join(errs))
    # 2. a Label_char.txt beside Label.txt must be updated too
    if ch_char is None and ch_label.with_name("Label_char.txt").exists():
        raise ApplyError("ch/Label_char.txt exists; pass --ch-char to update it too.")
    char_file = read_label_file(ch_char) if ch_char else None
    ch_order, _ = page_orders(ch_pages, vi_pages, pairs, nom_order, missing_ch, missing_vi)
    _, org = stream_origin([(k, ch_pages[k]) for k in ch_order])
    img_start: dict[str, int] = {}
    for i, (img, _b, _c) in enumerate(org):
        img_start.setdefault(img, i)
    # 3-4. select, locate and edit (in memory only)
    todo: list[
        tuple[int, int, str, int, int]
    ] = []  # row, element index, new char, stream offset, a
    base = 0
    n_skipped = 0
    parsed: list[list[dict] | None] = []
    for n, r in enumerate(records, 1):
        try:
            parsed.append(parse_diff(r["text_diff"]))
        except ValueError as exc:
            raise ApplyError(f"row {n}: {exc}") from None
    for k, r in enumerate(records):
        ch = r["ch_txt"]
        diff = parsed[k]
        lost = r["img_id"] in missing_ch
        for ei, el in enumerate(diff or []):
            if el.get("type") != "warn" or "suggest" not in el:
                continue
            if lost or (accept == "reviewed" and el.get("reviewed") != 1):
                n_skipped += 1
                continue
            a = el["nom_pos"][0][0]
            if ch[a : a + 1] != el["nom_sub_text"]:
                raise ApplyError(
                    f"row {k + 1}: ch_txt[{a}] is not {el['nom_sub_text']!r}; run check-diff"
                )
            todo.append((k, ei, el["suggest"], base + len(_norm_nom(ch[:a])), a))
        if not lost:
            base += len(_norm_nom(ch))
    problems: list[str] = []
    done_idx: set[tuple[int, int]] = set()
    accepted_by: dict[str, int] = {}
    touched: set[str] = set()
    for k, ei, new, off, _a in todo:
        el = (parsed[k] or [])[ei]
        if off >= len(org):
            problems.append(f"row {k + 1}: offset {off} is outside the Nom text of Label.txt")
            continue
        img, box, col = org[off]
        old = el["nom_sub_text"]
        try:
            ch_file.set_char(img, box, col, old, new)
        except ValueError as exc:
            problems.append(f"row {k + 1}: {exc}")
            continue
        touched.add(img)
        if char_file is not None:
            bi = _box_of(char_file.pages().get(img, []), off - img_start[img])
            try:
                if bi is None:
                    raise ValueError(f"{img}: no box at offset {off - img_start[img]}")
                char_file.set_char(img, bi, 0, old, new)
            except ValueError as exc:
                problems.append(f"Label_char.txt: {exc}")
                continue
        done_idx.add((k, ei))
        accepted_by[el["suggest_by"]] = accepted_by.get(el["suggest_by"], 0) + 1
    if char_file is not None and touched:
        # the LABELCHAR guard runs on the images that change, on the files as they are now
        cp = read_label(ch_char)
        sub = {i: cp[i] for i in touched if i in cp}
        problems += [m for m in check_char_file(sub, ch_pages, sorted(touched)) if "LABELCHAR" in m]
    if problems:
        raise ApplyError("\n".join(problems))
    # 5-6. the CSV: replace the character, drop its element; reject the rest if asked
    rejected_by: dict[str, int] = {}
    for k, r in enumerate(records):
        diff = parsed[k]
        if diff is None:
            continue
        new_diff: list[dict] = []
        ch = r["ch_txt"]
        for ei, el in enumerate(diff):
            if (k, ei) in done_idx:
                a = el["nom_pos"][0][0]
                ch = ch[:a] + el["suggest"] + ch[a + 1 :]
                continue
            if reject_rest and el.get("type") == "warn" and "suggest" in el:
                rejected_by[el["suggest_by"]] = rejected_by.get(el["suggest_by"], 0) + 1
                el = _to_error(el)
            new_diff.append(el)
        r["ch_txt"], r["text_diff"] = ch, dump_diff(new_diff)
    # stage, check, move
    stage = Path(tempfile.mkdtemp(prefix="nom-align-apply-"))
    try:
        out_files: dict[str, tuple[Path, Path]] = {}  # kind -> (staged, final)

        def plan(kind: str, src: Path) -> Path:
            dest = (Path(out_dir) / src.name) if out_dir else src
            st = stage / kind / src.name
            st.parent.mkdir()
            out_files[kind] = (st, dest)
            return st

        _write_records(records, plan("csv", csv_path))
        st_xlsx = None
        if xlsx:
            st_xlsx = plan("xlsx", Path(xlsx))
            render_xlsx(out_files["csv"][0], st_xlsx, cfg)
        write_label(ch_file, plan("ch", ch_label))
        st_char = None
        if char_file is not None:
            st_char = plan("char", Path(ch_char))
            write_label(char_file, st_char)
        rep_src = csv_path.with_name(csv_path.stem + "_align_report.json")
        if rep_src.is_file():
            rep = json.loads(rep_src.read_text(encoding="utf-8"))
            rep["suggestions_accepted"] = accepted_by
            rep["suggestions_rejected"] = rejected_by
            plan("report", rep_src).write_text(
                json.dumps(rep, ensure_ascii=False, indent=2), encoding="utf-8"
            )
        final = check_diff(
            out_files["csv"][0],
            xlsx=st_xlsx,
            ch_label=out_files["ch"][0],
            vi_label=vi_label,
            ch_char=st_char,
            pairs=pairs,
            nom_order=nom_order,
            missing_ch=missing_ch,
            missing_vi=missing_vi,
            final=True,
            cfg=cfg,
        )
        bad = [m for lvl, m in final if lvl == "error"]
        if bad:
            raise ApplyError("the result does not pass check-diff --final:\n" + "\n".join(bad[:50]))
        Path(out_dir).mkdir(parents=True, exist_ok=True) if out_dir else None
        for staged, dest in out_files.values():
            tmp = dest.with_name(dest.name + ".tmp")
            if in_place and dest.exists():
                shutil.copy2(dest, dest.with_name(dest.name + ".bak"))
            shutil.copy2(staged, tmp)
            os.replace(tmp, dest)
    finally:
        shutil.rmtree(stage, ignore_errors=True)
    return {
        "applied": len(done_idx),
        "rejected": sum(rejected_by.values()),
        "skipped": n_skipped,
        "accepted_by": accepted_by,
        "rejected_by": rejected_by,
        "files": [str(d) for _, d in out_files.values()],
    }


__all__ = ["ApplyError", "apply_suggestions"]
