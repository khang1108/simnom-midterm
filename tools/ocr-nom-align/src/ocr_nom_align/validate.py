"""Checks before submission, and the similarity formula. Works on the written CSV/XLSX only."""

from __future__ import annotations

import csv
import json
import os
import re
import unicodedata
from pathlib import Path

from openpyxl import load_workbook
from openpyxl.cell.rich_text import CellRichText, TextBlock

from .config import BLACK_COLORS, ERROR_COLORS, WARN_COLORS, NomAlignConfig
from .pages import (
    PagePair,
    clean_vi_lines,
    join_vi,
    page_key,
    pair_pages,
    read_label,
    stream_origin,
)
from .tableio import BLACK, COLUMNS, RED, YELLOW, read_csv, states
from .tokens import (
    MASK,
    count_nom,
    count_vi,
    has_selector,
    is_letter_char,
    mask_spans,
    nfc,
    nom_tokens,
    vi_tokens,
)

_KEYS = [
    "nom_pos",
    "nom_sub_text",
    "vi_pos",
    "vi_sub_text",
    "type",
]  # an `error`: exactly these, in any order
_WARN_KEYS = {
    *_KEYS,
    "reviewed",
    "suggest",
    "suggest_by",
}  # a `warn`: the five, and optionally these three
_SID = re.compile(r"^(.+)\.(\d+)$")


def parse_diff(cell: str):
    """`None` for the cell `null`, else the list. Raises `ValueError` for anything else."""
    if cell == "null":
        return None
    try:
        v = json.loads(cell)
    except json.JSONDecodeError as exc:
        raise ValueError(f"text_diff is not JSON ({exc})") from None
    if not isinstance(v, list):
        raise ValueError("text_diff must be null or an array")
    return v


def _check_side(text: str, el: dict, side: str, used: list[int], errs: list[str]) -> None:
    pos, sub = el[f"{side}_pos"], el[f"{side}_sub_text"]
    if not isinstance(pos, list) or not isinstance(sub, str):
        errs.append(f"KEYS: {side}: pos must be an array and sub_text a string")
        return
    cut, last = "", -1
    for rng in pos:
        if not (isinstance(rng, list) and len(rng) == 2 and all(isinstance(x, int) for x in rng)):
            errs.append(f"OOB: {side}_pos: bad range {rng!r}")
            return
        a, b = rng
        if not 0 <= a < b <= len(text):
            errs.append(f"OOB: {side}_pos: range {rng} outside the cell (length {len(text)})")
            return
        if a < last:
            errs.append(f"OVERLAP: {side}_pos: ranges not ascending / overlapping")
            return
        last = b
        if not (is_letter_char(text[a]) and is_letter_char(text[b - 1])):
            errs.append(f"EDGE: {side}_pos: range {rng} must start and end on a letter")
        if MASK in text[a:b]:
            errs.append(f"MASK: {side}_pos: range {rng} covers {MASK}")
        for k in range(a, b):
            if used[k]:
                errs.append(f"OVERLAP: {side}: character {k} is in two elements")
                return
            used[k] = 1
        cut += text[a:b]
    if cut != sub:
        errs.append(
            f"SUB: {side}_sub_text {sub!r} differs from the cell cut at pos {cut!r}; fix ch_txt / vi_txt, "
            "text_diff, Label.txt (and Label_char.txt) together"
        )


def _check_element(el, ch: str, vi: str, un: list[int], uv: list[int], errs: list[str]) -> None:
    if not isinstance(el, dict):
        errs.append("KEYS: element is not an object")
        return
    typ = el.get("type")
    if typ not in ("warn", "error"):
        errs.append(f"KEYS: type must be warn or error, got {typ!r}")
        return
    keys = set(el)
    if typ == "error":
        if keys != set(_KEYS):
            extra = keys & {"reviewed", "suggest", "suggest_by"}
            errs.append(
                ("SUGGEST: " if extra - {"reviewed"} else "KEYS: ")
                + f"an error element has exactly {_KEYS} (any order), got {sorted(keys)}"
            )
            if not set(_KEYS) <= keys:
                return
    elif not set(_KEYS) <= keys or keys - _WARN_KEYS:
        errs.append(
            f"KEYS: a warn element has {_KEYS} and optionally reviewed, suggest, suggest_by; got {sorted(keys)}"
        )
        if not set(_KEYS) <= keys:
            return
    if "reviewed" in el and (type(el["reviewed"]) is not int or el["reviewed"] not in (0, 1)):
        errs.append(f"REVIEWED: reviewed must be the integer 0 or 1, got {el['reviewed']!r}")
    if typ == "warn" and (("suggest" in el) != ("suggest_by" in el)):
        errs.append("SUGGEST: suggest and suggest_by come together")
    if typ == "warn" and "suggest" in el:
        sg = el["suggest"]
        if not (isinstance(sg, str) and len(sg) == 1):
            errs.append("SUGGEST: suggest must be exactly one character")
        if el.get("suggest_by") not in ("fallback", "similar"):
            errs.append("SUGGEST: suggest_by must be fallback or similar")
        pos = el.get("nom_pos")
        if not (
            isinstance(pos, list) and len(pos) == 1 and isinstance(pos[0], list) and len(pos[0]) == 2
            and all(type(x) is int for x in pos[0]) and pos[0][1] - pos[0][0] == 1
        ):  # fmt: skip
            errs.append(
                "SUGGEST: a suggestion replaces one character: nom_pos must be one range of length 1"
            )
    if not el["nom_pos"] and not el["vi_pos"]:
        errs.append("EMPTY: both sides of an element are empty")
    _check_side(ch, el, "nom", un, errs)
    _check_side(vi, el, "vi", uv, errs)


def pending_suggestions(row: dict[str, str]) -> int:
    """`warn` elements of the row that still carry a `suggest` (a working state, not submittable)."""
    try:
        diff = parse_diff(row["text_diff"])
    except ValueError:
        return 0
    return sum(1 for el in diff or [] if isinstance(el, dict) and "suggest" in el)


def check_plain(row: dict[str, str]) -> list[str]:
    """The checks that need neither `img_id` nor `text_diff` (every file type): EMPTY, SELECTOR, FORM."""
    errs: list[str] = []
    for c in ("ch_txt", "vi_txt"):
        if c not in row or row[c] is None:
            return [f"KEYS: missing column {c}"]
    ch, vi = row["ch_txt"], row["vi_txt"]
    if not ch.strip() or not vi.strip():
        errs.append("EMPTY: ch_txt and vi_txt must both be filled (no row with one empty side)")
    if has_selector(ch):
        errs.append("SELECTOR: ch_txt holds a variation selector")
    for name in ("ch_txt", "vi_txt"):
        s = row[name]
        if "\n" in s or "\r" in s:
            errs.append(f"FORM: {name}: line break in cell")
        if unicodedata.normalize("NFC", s) != s:
            errs.append(f"FORM: {name}: not NFC")
    return errs


def check_row(row: dict[str, str]) -> list[str]:
    """Problems of one row as `CODE: message` (codes of `check-diff`)."""
    for c in COLUMNS:
        if c not in row or row[c] is None:
            return [f"KEYS: missing column {c}"]
    ch, vi = row["ch_txt"], row["vi_txt"]
    errs = check_plain(row)
    if not row["img_id"].lower().endswith(".jpg") or "/" in row["img_id"]:
        errs.append("img_id must be an image name ending in .jpg, without folder")
    m = _SID.match(row["sentence_id"])
    if row["sentence_id"] and (
        not m or m.group(1) + ".jpg" != row["img_id"] and row["img_id"] != ""
    ):
        # the id of an n--1 row is the first Nom sentence, which starts on img_id
        errs.append(f"sentence_id {row['sentence_id']!r} must be <img_id without .jpg>.<n>")
    try:
        diff = parse_diff(row["text_diff"])
    except ValueError as exc:
        return [*errs, str(exc)]
    if diff is None:
        return errs
    un, uv = [0] * len(ch), [0] * len(vi)
    for el in diff:
        _check_element(el, ch, vi, un, uv, errs)
    return errs


def check_csv(path: str | Path) -> list[str]:
    """Problems as `row N: message` (N counts data rows from 1)."""
    out = []
    rows = read_csv(path)
    for n, r in enumerate(rows, 1):
        out += [f"row {n}: {e}" for e in check_row(r)]
    return out


def _rgb(font) -> str | None:
    """Last six hex digits of a font colour; `""` for none; `None` for a theme / indexed colour (not accepted)."""
    color = getattr(font, "color", None)
    if color is None:
        return ""
    rgb = color.rgb
    return rgb[-6:].upper() if isinstance(rgb, str) else None


def _cell_states(value, text: str, cfg: NomAlignConfig) -> tuple[list[int] | None, bool]:
    """`(states, bad_colour)`; `states` is `None` when the text differs from `text`."""
    error = ERROR_COLORS | {cfg.error_color}
    warn = WARN_COLORS | {cfg.warn_color}
    if isinstance(value, CellRichText):
        st, bad = [], False
        for part in value:
            if isinstance(part, TextBlock):
                rgb = _rgb(part.font)
                if rgb in error:
                    s = RED
                elif rgb in warn:
                    s = YELLOW
                elif rgb in BLACK_COLORS or rgb == "":
                    s = BLACK
                else:
                    s, bad = BLACK, True  # an unknown colour is never valid
                st += [s] * len(part.text)
            else:
                st += [BLACK] * len(part)
        return (st if len(st) == len(text) else None), bad
    return ([BLACK] * len(text) if str(value or "") == text else None), False


def check_xlsx(
    csv_path: str | Path, xlsx_path: str | Path, cfg: NomAlignConfig | None = None
) -> list[str]:
    """Colour of every character of ch_txt / vi_txt must equal the state given by the CSV `text_diff`."""
    cfg = cfg or NomAlignConfig()
    rows = read_csv(csv_path)
    wb = load_workbook(xlsx_path, rich_text=True)
    ws = wb["align"] if "align" in wb.sheetnames else wb.worksheets[0]
    out = []
    if ws.max_row - 1 != len(rows):
        return [f"xlsx has {ws.max_row - 1} data rows, csv has {len(rows)}"]
    for n, r in enumerate(rows, 1):
        try:
            diff = parse_diff(r["text_diff"])
        except ValueError:
            continue
        for col, name, side in ((3, "ch_txt", "nom"), (4, "vi_txt", "vi")):
            want = states(r[name], side, diff)
            got, bad = _cell_states(ws.cell(n + 1, col).value, r[name], cfg)
            if got is None:
                out.append(f"row {n}: XLSX: {name} text differs between csv and xlsx")
            elif bad:
                out.append(f"row {n}: XLSX: {name} has a colour outside the accepted set")
            elif got != want:
                out.append(f"row {n}: XLSX: {name} colours differ from text_diff")
    return out


def _norm_vi(s: str) -> str:
    """Loose Vietnamese compare form (spec B3): whitespace and `-` ignored."""
    return "".join(c for c in s if not c.isspace() and c != "-")


def _norm_nom(s: str) -> str:
    return "".join(s.split())


def page_orders(
    ch_pages: dict | None,
    vi_pages: dict | None,
    pairs: list[PagePair] | None,
    order: str = "asc",
    missing_ch: frozenset[str] = frozenset(),
    missing_vi: frozenset[str] = frozenset(),
) -> tuple[list[str], list[str]]:
    """The page order `run` would use, for each side. Images of lost pages (`missing/ch`, `missing/vi`) take part
    in the pairing, so the Vietnamese page of a lost Nom page stays in the stream; they hold no text themselves."""
    if pairs is None and ch_pages is not None and vi_pages is not None:
        pairs = pair_pages(
            sorted({*ch_pages, *missing_ch}), sorted({*vi_pages, *missing_vi}), order=order
        )
    if pairs is None:
        return (
            sorted(ch_pages or {}, key=page_key, reverse=(order == "desc")),
            sorted(vi_pages or {}, key=page_key),
        )
    ch_order: list[str] = []
    vi_order: list[str] = []
    for p in pairs:
        if p.vi and not p.ch:
            continue  # as `align_book`: a Vietnamese page without Nom page is not aligned
        ch_order += [x for x in p.ch if x not in ch_order]
        vi_order += [x for x in p.vi if x not in vi_order]
    return (
        [k for k in ch_order if ch_pages is not None and k in ch_pages and k not in missing_ch],
        [k for k in vi_order if vi_pages is not None and k in vi_pages and k not in missing_vi],
    )


def _first_diff(parts: list[tuple[int, str]], label: str, org: list, name: str) -> str | None:
    csv_text = "".join(t for _, t in parts)
    if csv_text == label:
        return None
    k = len(os.path.commonprefix([csv_text, label]))
    rowmap = [rn for rn, t in parts for _ in t]
    row = rowmap[k] if k < len(rowmap) else (rowmap[-1] if rowmap else 0)
    here = org[k] if k < len(org) else None
    where = f"{here[0]} box {here[1] + 1} column {here[2]}" if here else "the end of Label.txt"
    got = csv_text[k : k + 1] or "(end)"
    want = label[k : k + 1] or "(end)"
    return (
        f"row {row}: SYNC: {name} differs from Label.txt at {where}: csv {got!r}, Label.txt {want!r}"
        " (fix Label.txt, ch_txt / vi_txt, text_diff and Label_char.txt together)"
    )


def _covers(el_pos: list, lo: int, hi: int) -> bool:
    return any(isinstance(r, list) and len(r) == 2 and r[0] <= lo and r[1] >= hi for r in el_pos)


def _predicted_ok(row: dict[str, str], side: str) -> bool:
    """A predicted side must be covered whole by one `warn` element (position of its first to its last token)."""
    text = row["ch_txt" if side == "nom" else "vi_txt"]
    toks = [
        t
        for a, b in mask_spans(text)
        for t in (nom_tokens(text, a, b) if side == "nom" else vi_tokens(text, a, b))
    ]
    if not toks:
        return True
    try:
        diff = parse_diff(row["text_diff"])
    except ValueError:
        return False
    lo, hi = toks[0].start, toks[-1].end
    return any(
        isinstance(el, dict)
        and el.get("type") == "warn"
        and _covers(el.get(f"{side}_pos", []), lo, hi)
        for el in diff or []
    )


def check_text_sync(
    rows: list[dict[str, str]],
    ch_pages: dict[str, list[str]] | None,
    vi_pages: dict[str, list[str]] | None,
    pairs: list[PagePair] | None = None,
    cfg: NomAlignConfig | None = None,
    missing_ch: frozenset[str] = frozenset(),
    missing_vi: frozenset[str] = frozenset(),
    order: str = "asc",
    exact: bool = False,
) -> tuple[list[str], list[str]]:
    """`(errors, warnings)`: the CSV text against Label.txt, per side that has a Label.txt (spec B3). Whitespace is
    ignored, and `-` for Vietnamese. Rows whose image is in `missing/ch` (Nom side) or `missing/vi` (Vietnamese side)
    are predicted on that side: that side is left out of the compared stream and must be one whole `warn`. Every
    other row, a fully yellow name row too, must match."""
    cfg = cfg or NomAlignConfig()
    errs: list[str] = []
    warns: list[str] = []
    ch_order, vi_order = page_orders(ch_pages, vi_pages, pairs, order, missing_ch, missing_vi)
    for n, r in enumerate(rows, 1):
        for side, lost, col in (("nom", missing_ch, "ch_txt"), ("vi", missing_vi, "vi_txt")):
            if r.get("img_id") in lost and not _predicted_ok(r, side):
                errs.append(
                    f"row {n}: SYNC: {col} of a lost page ({r['img_id']}) must be one whole warn element"
                )
    if ch_pages is not None:
        chunks = [(k, ch_pages[k]) for k in ch_order]
        label, org = stream_origin(chunks)
        parts = [
            (n, _norm_nom(r["ch_txt"]))
            for n, r in enumerate(rows, 1)
            if r["img_id"] not in missing_ch
        ]
        msg = _first_diff(parts, label, org, "ch_txt")
        if msg:
            errs.append(msg)
    if vi_pages is not None:
        chunks = [(k, clean_vi_lines(vi_pages[k], cfg.strip_notes)) for k in vi_order]
        label, org = stream_origin([(k, vi_pages[k]) for k in vi_order], drop="-")
        if (
            cfg.strip_notes
        ):  # the tool stripped note marks; Label.txt must carry the cleaned text then
            label = _norm_vi("".join(c for _, ls in chunks for c in ls))
            org = []
        parts = [
            (n, _norm_vi(r["vi_txt"]))
            for n, r in enumerate(rows, 1)
            if r["img_id"] not in missing_vi
        ]
        msg = _first_diff(parts, label, org, "vi_txt")
        if msg:
            errs.append(msg)
        elif exact:
            chunks = [(k, clean_vi_lines(vi_pages[k], False)) for k in vi_order]
            joined, _ = join_vi(chunks, cfg.hyphen, frozenset(cfg.names))
            have = " ".join(
                " ".join(r["vi_txt"] for r in rows if r["img_id"] not in missing_vi).split()
            )
            if " ".join(joined.split()) != have:
                warns.append(
                    "SYNC_EXACT: vi_txt differs from the exact join of Label.txt (hyphen choices?)"
                )
    return errs, warns


def check_char_file(
    ch_char: dict[str, list[str]],
    ch_pages: dict[str, list[str]] | None,
    ch_order: list[str],
    rows: list[dict[str, str]] | None = None,
    missing_ch: frozenset[str] = frozenset(),
) -> list[str]:
    """`Label_char.txt` (spec A17): one character per box (only `[MASK]` may be longer), boxes in reading order, and
    their concatenation per image equal to the Nom text of Label.txt (LABELCHAR); one character that differs from
    Label.txt, or without a Label.txt from the CSV, is SYNC_CHAR."""
    errs: list[str] = []
    for img, boxes in ch_char.items():
        for i, raw in enumerate(boxes, 1):
            t = nfc(raw)
            if not (t == MASK or (len(t) == 1 and not t.isspace())):
                errs.append(
                    f"LABELCHAR: {img}: box {i} holds {len(t)} characters (one per box; only {MASK} may be longer)"
                )
    if ch_pages is None:
        if rows is None:
            return errs
        label, org = stream_origin([(k, ch_char[k]) for k in ch_order if k in ch_char])
        parts = [
            (n, _norm_nom(r["ch_txt"]))
            for n, r in enumerate(rows, 1)
            if r["img_id"] not in missing_ch
        ]
        msg = _first_diff(parts, label, org, "ch_txt")
        return errs + (
            [msg.replace("SYNC:", "SYNC_CHAR:").replace("Label.txt", "Label_char.txt")]
            if msg
            else []
        )
    for img in ch_order:
        want = "".join("".join(nfc(s).split()) for s in ch_pages[img])
        if img not in ch_char:
            if want:
                errs.append(f"LABELCHAR: {img}: no boxes in Label_char.txt")
            continue
        boxes = [nfc(b) for b in ch_char[img]]
        got = "".join("".join(b.split()) for b in boxes)
        if got == want:
            continue
        diff_at = [k for k in range(min(len(got), len(want))) if got[k] != want[k]]
        if len(got) == len(want) and len(diff_at) == 1:
            k, run = diff_at[0], 0
            box = 0
            for bi, b in enumerate(boxes):
                if run + len(b) > k:
                    box = bi
                    break
                run += len(b)
            errs.append(
                f"SYNC_CHAR: {img}: Label_char.txt box {box + 1} holds {got[k]!r}, Label.txt has {want[k]!r}"
            )
        else:
            k = len(os.path.commonprefix([got, want]))
            errs.append(
                f"LABELCHAR: {img}: the boxes are missing, extra or not in reading order "
                f"(first difference at character {k}: {got[k : k + 1]!r} against {want[k : k + 1]!r})"
            )
    return errs


def check_diff(
    csv_path: str | Path,
    *,
    xlsx: str | Path | None = None,
    ch_label: str | Path | None = None,
    vi_label: str | Path | None = None,
    ch_char: str | Path | None = None,
    pairs: list[PagePair] | None = None,
    nom_order: str = "asc",
    missing_ch: frozenset[str] = frozenset(),
    missing_vi: frozenset[str] = frozenset(),
    strict: bool = False,
    final: bool = False,
    sync_exact: bool = False,
    cfg: NomAlignConfig | None = None,
) -> list[tuple[str, str]]:
    """Every problem of a finished CSV as `(level, line)`; level is `error`, `warning` or `note`. `strict` makes
    warnings errors; `final` (the submission gate) makes a pending suggestion an error. A CSV without `img_id` /
    `text_diff` (plain-text type) gets only EMPTY, SELECTOR and FORM."""
    cfg = cfg or NomAlignConfig()
    out: list[tuple[str, str]] = []
    rows = read_csv(csv_path)
    with Path(csv_path).open(encoding="utf-8-sig", newline="") as f:
        header = next(csv.reader(f), [])
    plain = "img_id" not in header or "text_diff" not in header
    if plain:
        out.append(("note", "plain-text type: only EMPTY, SELECTOR and FORM are checked"))
        for n, r in enumerate(rows, 1):
            out += [("error", f"row {n}: {m}") for m in check_plain(r)]
        return out
    unreviewed = 0
    for n, r in enumerate(rows, 1):
        out += [("error", f"row {n}: {m}") for m in check_row(r)]
        k = pending_suggestions(r)
        if k:
            out.append((
                "error" if final else "warning",
                f"row {n}: SUGGEST_PENDING: {k} warn element(s) still carry a suggestion; accept (apply) "
                "or reject (apply --reject-rest) it before submission",
            ))  # fmt: skip
        try:
            diff = parse_diff(r["text_diff"])
        except ValueError:
            diff = None
        unreviewed += sum(
            1
            for el in diff or []
            if isinstance(el, dict) and el.get("type") == "warn" and el.get("reviewed") != 1
        )
    if unreviewed:
        out.append(("warning", f"REVIEWED: {unreviewed} warn element(s) with reviewed 0 or absent"))
    if xlsx:
        for m in check_xlsx(csv_path, xlsx, cfg):
            out.append(("error", m if "XLSX:" in m else f"XLSX: {m}"))
    ch_pages = read_label(ch_label) if ch_label else None
    vi_pages = read_label(vi_label) if vi_label else None
    if ch_pages is not None or vi_pages is not None:
        errs, warns = check_text_sync(
            rows, ch_pages, vi_pages, pairs, cfg, missing_ch, missing_vi, nom_order, sync_exact
        )
        out += [("error", m) for m in errs] + [("warning", m) for m in warns]
    if ch_char:
        char_pages = read_label(ch_char)
        # without --ch the order comes from the box file itself (same pairing rules)
        ch_order, _ = page_orders(
            ch_pages if ch_pages is not None else char_pages,
            vi_pages,
            pairs,
            nom_order,
            missing_ch,
            missing_vi,
        )
        out += [
            ("error", m) for m in check_char_file(char_pages, ch_pages, ch_order, rows, missing_ch)
        ]
    if strict:
        out = [("error" if lvl == "warning" else lvl, m) for lvl, m in out]
    return out


def similarity(rows: list[dict[str, str]]) -> dict:
    """`(1 - red / scored Nom characters) * 100` over rows whose text_diff is not null.
    red: per `error` element the larger of its Nom characters and Vietnamese syllables.
    scored: Nom characters of those rows, without punctuation, `[MASK]` and yellow characters."""
    phon = nom_total = red = yellow = 0
    null = reviewed = unreviewed = sug_fb = sug_sim = 0
    for r in rows:
        diff = parse_diff(r["text_diff"])
        if diff is None:
            null += 1
            continue
        phon += 1
        nom_total += count_nom(r["ch_txt"])
        for el in diff:
            cn, cv = count_nom(el["nom_sub_text"]), count_vi(el["vi_sub_text"])
            if el["type"] == "error":
                red += max(cn, cv)
            else:
                yellow += cn
                if el.get("reviewed") == 1:
                    reviewed += 1
                else:
                    unreviewed += 1  # absent counts as 0
                if "suggest" in el:
                    sug_fb += el.get("suggest_by") == "fallback"
                    sug_sim += el.get("suggest_by") == "similar"
    scored = nom_total - yellow
    return {
        "rows": len(rows),
        "phonetic_rows": phon,
        "null_rows": null,
        "null_rate": (null / len(rows)) if rows else 0.0,
        "nom_chars_phonetic": nom_total,
        "yellow_chars": yellow,
        "yellow_rate": (yellow / nom_total) if nom_total else 0.0,
        "warn_reviewed": reviewed,
        "warn_unreviewed": unreviewed,
        "suggested_fallback_chars": sug_fb,  # pending only
        "suggested_similar_chars": sug_sim,
        "red_chars": red,
        "scored_chars": scored,
        "similarity": ((1 - red / scored) * 100) if scored > 0 else None,
    }


__all__ = [
    "check_char_file", "check_csv", "check_diff", "check_plain", "check_row", "check_text_sync", "check_xlsx",
    "page_orders", "parse_diff", "pending_suggestions", "similarity",
]  # fmt: skip
