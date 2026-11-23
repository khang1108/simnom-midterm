"""PPOCRLabel `Label.txt` reading, page text, page pairing and the image map.

Box order in a `Label.txt` line is the reading order; this module never reorders boxes.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from pathlib import Path

from .tokens import has_selector, nfc

_PAGE = re.compile(r"\.(\d+)(?:_(\d+))?\.jpe?g$", re.I)
_NOTE = re.compile(r"\[\d+\]|\(\d+\)")


def page_key(name: str) -> tuple[int, int, str]:
    """Natural order of image names: page number, then image number inside the page."""
    m = _PAGE.search(name)
    return (int(m.group(1)), int(m.group(2) or 0), name) if m else (10**9, 0, name)


def stem(name: str) -> str:
    return re.sub(r"\.jpe?g$", "", name, flags=re.I)


@dataclass
class LabelEntry:
    line: int  # index into `LabelFile.lines`
    path: str  # the part before the tab, as written
    boxes: list[dict]  # parsed, every key kept
    changed: bool = False


@dataclass
class LabelFile:
    """A PPOCRLabel file kept line by line, so a write touches only the images whose boxes changed."""

    lines: list[str]
    entries: dict[str, LabelEntry]  # by image name (folder dropped)
    bom: bool = False

    def pages(self) -> dict[str, list[str]]:
        return {
            k: [str(b.get("transcription", "")) for b in e.boxes] for k, e in self.entries.items()
        }

    def set_char(self, image: str, box: int, col: int, old: str, new: str) -> None:
        """Replace one character of one box (`box` 0-based, `col` an index into the NFC text); the old one must match."""
        e = self.entries.get(image)
        if e is None or not 0 <= box < len(e.boxes):
            raise ValueError(f"{image}: no box {box + 1}")
        t = nfc(str(e.boxes[box].get("transcription", "")))
        if not 0 <= col < len(t) or t[col] != old:
            raise ValueError(f"{image} box {box + 1} column {col}: expected {old!r}")
        e.boxes[box]["transcription"] = t[:col] + new + t[col + 1 :]
        e.changed = True


def read_label_file(path: str | Path) -> LabelFile:
    raw = Path(path).read_bytes()
    bom = raw.startswith(b"\xef\xbb\xbf")
    lines = raw.decode("utf-8-sig").split("\n")
    entries: dict[str, LabelEntry] = {}
    for n, line in enumerate(lines):
        body = line.rstrip("\r")
        if not body.strip():
            continue
        name, sep, js = body.partition("\t")
        if not sep:
            raise ValueError(f"{path}:{n + 1}: no tab between image path and JSON")
        try:
            boxes = json.loads(js)
        except json.JSONDecodeError as exc:
            raise ValueError(f"{path}:{n + 1}: bad JSON ({exc})") from None
        if not isinstance(boxes, list) or not all(isinstance(b, dict) for b in boxes):
            raise ValueError(f"{path}:{n + 1}: the JSON must be a list of boxes")
        entries[name.replace("\\", "/").rsplit("/", 1)[-1]] = LabelEntry(n, name, boxes)
    return LabelFile(lines, entries, bom)


def read_label(path: str | Path) -> dict[str, list[str]]:
    """`{image name: [transcription, ...]}` in file order. The folder part of the path is dropped."""
    return read_label_file(path).pages()


def write_label(label: LabelFile, path: str | Path) -> Path:
    """Write the file: lines of unchanged images byte for byte, changed ones re-dumped like PPOCRLabel."""
    out = list(label.lines)
    for e in label.entries.values():
        if e.changed:
            cr = "\r" if label.lines[e.line].endswith("\r") else ""
            out[e.line] = e.path + "\t" + json.dumps(e.boxes, ensure_ascii=False) + cr
    data = "\n".join(out).encode("utf-8")
    p = Path(path)
    p.write_bytes((b"\xef\xbb\xbf" if label.bom else b"") + data)
    return p


def stream_origin(
    chunks: list[tuple[str, list[str]]], drop: str = ""
) -> tuple[str, list[tuple[str, int, int]]]:
    """The text of `[(image, raw box texts)]` without whitespace (and without the characters of `drop`), and for each
    of its characters `(image, box index from 0, column in the NFC box text)`."""
    chars: list[str] = []
    org: list[tuple[str, int, int]] = []
    for img, lines in chunks:
        for bi, raw in enumerate(lines):
            for ci, c in enumerate(nfc(raw)):
                if c.isspace() or c in drop:
                    continue
                chars.append(c)
                org.append((img, bi, ci))
    return "".join(chars), org


def nom_origin(ordered_pages: list[tuple[str, list[str]]]) -> list[tuple[str, int, int]]:
    """For each character of the cleaned Nom stream: `(image, box index, column in the transcription)`."""
    return stream_origin(ordered_pages)[1]


def lint_label(label: LabelFile) -> dict[str, list[dict]]:
    """Things in a Label.txt the spec wants cleaned there (the tool never edits the text): note marks, line-end
    hyphens, variation selectors, text that is not NFC, stray whitespace. Boxes count from 1."""
    out: dict[str, list[dict]] = {
        k: [] for k in ("note_mark", "line_end_hyphen", "selector", "not_nfc", "stray_whitespace")
    }
    for img, e in label.entries.items():
        for bi, b in enumerate(e.boxes, 1):
            t = str(b.get("transcription", ""))
            where = {"img_id": img, "box": bi}
            if _NOTE.search(t):
                out["note_mark"].append(where)
            if t.rstrip().endswith("-"):
                out["line_end_hyphen"].append(where)
            if has_selector(t):
                out["selector"].append(where)
            if nfc(t) != t:
                out["not_nfc"].append(where)
            if t != t.strip() or "  " in t or "\t" in t:
                out["stray_whitespace"].append(where)
    return out


def clean_vi_lines(lines: list[str], strip_notes: bool = False) -> list[str]:
    out = []
    for s in lines:
        s = nfc(s)
        if strip_notes:
            s = _NOTE.sub("", s)
        s = " ".join(s.split())
        if s:
            out.append(s)
    return out


def clean_nom_lines(lines: list[str]) -> list[str]:
    out = []
    for s in lines:
        s = "".join(nfc(s).split())
        if s:
            out.append(s)
    return out


def _last_word(s: str) -> str:
    return re.split(r"\s", s.rstrip())[-1] if s.strip() else ""


def join_vi(
    chunks: list[tuple[str, list[str]]],
    hyphen: str = "word",
    keep_words: frozenset[str] = frozenset(),
    manual: frozenset[str] = frozenset(),
    records: list[dict] | None = None,
) -> tuple[str, list[tuple[int, str]]]:
    """Join lines of all pages into one string. A line ending in `-` is joined to the next one:
    `hyphen="space"`: the dash goes and a space stays (`tin-` `tưởng` -> `tin tưởng`); `"keep"`: the dash stays;
    `"word"` (default): the dash stays when both parts start with a capital or the joined word (hyphens included)
    is in `keep_words` (names file) or `manual` (the hyphen list), else it goes as in `"space"`.
    Every joined hyphen is appended to `records` as `{img_id, box, left, right, result, action, reason, reviewed}`;
    `reviewed` is 1 only for a word in `manual`.
    Returns the text and `[(start offset, image name)]` per page."""
    parts: list[str] = []
    starts: list[tuple[int, str]] = []
    pos = 0
    low_manual = {w.lower() for w in manual}
    low_keep = {w.lower() for w in keep_words}
    for name, lines in chunks:
        first = True
        for box, ln in enumerate(lines, 1):
            if parts:
                if parts[-1].endswith("-"):
                    left = _last_word(
                        parts[-1]
                    )  # a line ends the last part; its last word is whole
                    right = ln.split(" ", 1)[0]
                    joined = left + right
                    if hyphen == "keep":
                        action, reason = "kept", "default"
                    elif hyphen == "space":
                        action, reason = "dropped", "default"
                    elif joined.lower() in low_manual:
                        action, reason = "kept", "manual"
                    elif joined.lower() in low_keep:
                        action, reason = "kept", "names"
                    elif left[:1].isupper() and right[:1].isupper():
                        action, reason = "kept", "capitals"
                    else:
                        action, reason = "dropped", "default"
                    if action == "dropped":
                        parts[-1] = parts[-1][:-1]
                        parts.append(" ")
                        # one char of dash replaced by one space: length unchanged
                    if records is not None:
                        records.append(
                            {"img_id": name, "box": box, "left": left, "right": right,
                             "result": joined if action == "kept" else f"{left[:-1]} {right}",
                             "action": action, "reason": reason,
                             "reviewed": 1 if reason == "manual" else 0}
                        )  # fmt: skip
                else:
                    parts.append(" ")
                    pos += 1
            if first:
                starts.append((pos, name))
                first = False
            parts.append(ln)
            pos += len(ln)
        if first:
            starts.append((pos, name))
    return "".join(parts), starts


def hyphen_inconsistent(text: str, manual: frozenset[str] = frozenset()) -> list[dict]:
    """Words that appear with and without a hyphen (`A-ve`, `Ave`): grouped by the lower-cased form without hyphens;
    a group with a word of the manual list is silenced."""
    low_manual = {w.lower() for w in manual}
    groups: dict[str, dict[str, list[int]]] = {}
    for m in re.finditer(r"[^\W_]+(?:-[^\W_]+)*", text):
        w = m.group()
        groups.setdefault(w.replace("-", "").lower(), {}).setdefault(w, []).append(m.start())
    out = []
    for key, forms in sorted(groups.items()):
        if (
            len(forms) > 1
            and any("-" in f for f in forms)
            and not any(f.lower() in low_manual for f in forms)
        ):
            out.append({"key": key, "forms": {f: p[:5] for f, p in sorted(forms.items())}})
    return out


def join_nom(chunks: list[tuple[str, list[str]]]) -> tuple[str, list[tuple[int, str]]]:
    parts, starts, pos = [], [], 0
    for name, lines in chunks:
        starts.append((pos, name))
        s = "".join(lines)
        parts.append(s)
        pos += len(s)
    return "".join(parts), starts


@dataclass
class PagePair:
    ch: list[str] = field(default_factory=list)
    vi: list[str] = field(default_factory=list)
    note: str = ""


def read_image_map(path: str | Path) -> list[PagePair]:
    """`<book>_image_map.json`: `{"pairs": [{"ch": [...], "vi": [...], "note": ...}]}`, in reading order."""
    data = json.loads(Path(path).read_text(encoding="utf-8"))
    pairs = []
    for p in data.get("pairs", []):
        pair = PagePair(list(p.get("ch", [])), list(p.get("vi", [])), p.get("note", ""))
        if not pair.ch and not pair.vi:
            raise ValueError("image_map: a pair with both sides empty")
        pairs.append(pair)
    return pairs


def pair_pages(ch_names: list[str], vi_names: list[str], *, order: str = "asc") -> list[PagePair]:
    """No image map: pair by page number when most numbers agree (T2), else by position (T1)."""
    chs = sorted(ch_names, key=page_key, reverse=(order == "desc"))
    vis = sorted(vi_names, key=page_key)
    cn = {page_key(n)[0] for n in chs}
    vn = {page_key(n)[0] for n in vis}
    if chs and vis and len(cn & vn) >= 0.5 * min(len(cn), len(vn)):
        nums = sorted(cn | vn, reverse=(order == "desc"))
        return [
            PagePair(
                [n for n in chs if page_key(n)[0] == k], [n for n in vis if page_key(n)[0] == k]
            )
            for k in nums
        ]
    return (
        [PagePair([c], [v]) for c, v in zip(chs, vis, strict=False)]
        + [PagePair([c], []) for c in chs[len(vis) :]]
        + [PagePair([], [v]) for v in vis[len(chs) :]]
    )


__all__ = [
    "LabelEntry", "LabelFile", "PagePair", "clean_nom_lines", "clean_vi_lines", "hyphen_inconsistent", "join_nom",
    "join_vi", "lint_label", "nom_origin", "page_key", "pair_pages", "read_image_map", "read_label",
    "read_label_file", "stem", "stream_origin", "write_label",
]  # fmt: skip
