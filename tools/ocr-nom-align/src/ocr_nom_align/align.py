"""Sentence alignment of a whole book: Nom sentences against Vietnamese sentences, then `text_diff` per row.

1. Page text of both sides is joined in reading order, so a sentence cut by a page break is whole again; every
   sentence belongs to the image where it starts (`img_id`, `sentence_id = <image stem>.<n>`).
2. Both sides are split at punctuation (a hint only).
3. A banded DP over sentence boundaries picks moves 1-1, 1-n, n-1, 2-2 (and skips). A move costs the Levenshtein
   distance of the Nom characters against the Vietnamese syllables (reading table), plus penalties for merging.
4. Each chosen group becomes a row; 1-1 rows that read as a phonetic translation get `text_diff`, the rest `null`.
"""

from __future__ import annotations

import math
import re
from bisect import bisect_right
from dataclasses import dataclass, field

from .config import NomAlignConfig
from .diff import pair_cost, text_diff
from .lev import edit_cost
from .pages import (
    PagePair,
    clean_nom_lines,
    clean_vi_lines,
    hyphen_inconsistent,
    join_nom,
    join_vi,
    pair_pages,
    stem,
)
from .ranges import Ranges
from .readings import ReadingTable
from .sentences import apply_merges, split_nom, split_vi
from .suggest import Suggester, fallback_map
from .tokens import (
    MASK,
    Tok,
    count_nom,
    count_vi,
    mask_spans,
    nfc,
    nom_tokens,
    syllable_key,
    vi_tokens,
)


class AlignFailed(Exception):  # noqa: N818 (same name as ocr-align)
    pass


@dataclass
class Sentence:
    text: str
    img: str
    idx: int  # position in its stream
    n: int  # number on its image (1-based)
    start: int = 0  # offset of its first character in its stream
    end: int = 0
    short: bool = False
    toks: list = field(
        default_factory=list
    )  # Nom: characters; Vietnamese: comparison keys ("#" for a number)

    @property
    def sid(self) -> str:
        return f"{stem(self.img)}.{self.n}"


@dataclass
class Row:
    img_id: str
    sentence_id: str
    ch_txt: str
    vi_txt: str
    text_diff: list[dict] | None
    kind: str  # "1-1" | "1-n" | "n-1" | "n-m" | "nom-only" | "vi-only"
    vi_img: str = ""
    phonetic: bool = False
    nom_start: int = -1  # offset of ch_txt[0] in the Nom stream (-1: no Nom side)


@dataclass
class BookResult:
    rows: list[Row]
    orphans_nom: list[Sentence]
    orphans_vi: list[Sentence]
    report: dict
    short: list[tuple[str, Sentence]] = field(
        default_factory=list
    )  # (side, sentence) below `short_warn`


def _rec_n(rec: dict) -> int:
    m = re.search(r"[.#](\d+)$", str(rec.get("sentence_id", "")))
    if not m:
        raise ValueError(f"merges: bad sentence_id {rec.get('sentence_id')!r}")
    return int(m.group(1))


def build_sentences(
    chunks: list[tuple[str, list[str]]],
    side: str,
    cfg: NomAlignConfig,
    manual: frozenset[str] = frozenset(),
    records: list[dict] | None = None,
    merges: list[dict] | None = None,
) -> list[Sentence]:
    """Sentences of one side from `[(image, cleaned lines)]` in reading order. `merges`: records of the short-sentence
    file (`side, img_id, sentence_id, text, merge`); a `prev` / `next` joins that sentence to its neighbour. A record
    whose text no longer matches its sentence is an error."""
    if side == "nom":
        text, starts = join_nom(chunks)
        spans, short = split_nom(text, cfg.merge_short, cfg.short_warn)
        count = count_nom
    else:
        text, starts = join_vi(chunks, cfg.hyphen, frozenset(cfg.names), manual, records)
        spans, short = split_vi(text, cfg.merge_short, cfg.short_warn)
        count = count_vi
    offs = [s for s, _ in starts]

    def img_of(a: int) -> str:
        # a sentence belongs to the last page that starts at or before its first character
        # (pages without lines share an offset with the next page: take the last one)
        return starts[max(0, bisect_right(offs, a) - 1)][1]

    todo: dict[int, str] = {}
    if merges:
        seen: dict[tuple[str, int], tuple[int, str]] = {}
        per: dict[str, int] = {}
        for k, (a, b) in enumerate(spans):
            im = img_of(a)
            per[im] = per.get(im, 0) + 1
            seen[(im, per[im])] = (k, text[a:b])
        for rec in merges:
            if rec.get("side") != side or rec.get("merge", "keep") == "keep":
                continue
            hit = seen.get((rec.get("img_id"), _rec_n(rec)))
            if hit is None or hit[1] != rec.get("text"):
                raise ValueError(
                    f"merges: stale line for {rec.get('sentence_id')!r} on {rec.get('img_id')!r}: "
                    "the sentence is not there any more (the split changed); list the short sentences again"
                )
            todo[hit[0]] = rec["merge"]
    if todo:
        spans = apply_merges(spans, todo)
        short = [
            (a, b) for a, b in spans if cfg.short_warn > 0 and count(text[a:b]) < cfg.short_warn
        ]
    short = set(short)
    out, per_img = [], {}
    for k, (a, b) in enumerate(spans):
        img = img_of(a)
        per_img[img] = per_img.get(img, 0) + 1
        s = Sentence(text[a:b], img, k, per_img[img], a, b)
        s.toks = _tokens(s.text, side)
        s.short = (a, b) in short
        out.append(s)
    return out


def _tokens(text: str, side: str) -> list:
    if side == "nom":
        return [t.text for a, b in mask_spans(text) for t in nom_tokens(text, a, b)]
    return [
        "#" if t.kind == "num" else syllable_key(t.text)
        for a, b in mask_spans(text)
        for t in vi_tokens(text, a, b)
    ]


class _Scorer:
    def __init__(
        self, nom: list[Sentence], vi: list[Sentence], table: ReadingTable, cfg: NomAlignConfig
    ):
        self.nom, self.vi, self.table, self.cfg = nom, vi, table, cfg
        self.cache: dict[tuple, float] = {}
        tn = sum(len(s.toks) for s in nom)
        tv = sum(len(s.toks) for s in vi)
        self.ratio = (tv / tn) if tn and tv else 1.0
        self._rd: dict[str, frozenset] = {}

    def _sub(self, c: str, k: str) -> float:
        rs = self._rd.get(c)
        if rs is None:
            rs = self._rd[c] = self.table.readings(c)
        if k == "#":
            return self.cfg.unknown_cost
        if not rs:
            return self.cfg.unknown_cost
        return 0.0 if k in rs else self.cfg.mismatch_cost

    def cost(self, i: int, a: int, j: int, b: int) -> float:
        key = (i, a, j, b)
        v = self.cache.get(key)
        if v is None:
            v = self.cache[key] = self._cost(i, a, j, b)
        return v

    def _cost(self, i: int, a: int, j: int, b: int) -> float:
        c = self.cfg
        nt = [t for s in self.nom[i : i + a] for t in s.toks]
        vt = [t for s in self.vi[j : j + b] for t in s.toks]
        if a == 0 or b == 0:
            return c.skip_base + c.skip_per_token * (len(nt) + len(vt))
        pen = c.merge_penalty * (a + b - 2) + (c.nm_penalty if a > 1 and b > 1 else 0.0)
        n, m = len(nt), len(vt)
        if n == 0 or m == 0:
            return pen + max(n, m)
        if c.cost_mode == "length":
            return pen + 4.0 * abs(math.log((m + 1) / (self.ratio * (n + 1))))
        if min(n, m) / max(n, m) < c.min_len_ratio:
            return pen + max(n, m)
        return pen + edit_cost(nt, vt, self._sub, c.gap_cost)


def _centers(nom: list[Sentence], vi: list[Sentence], pairs: list[PagePair] | None) -> list[float]:
    """Expected Vietnamese boundary for every Nom boundary 0..N, from the page pairs (or a straight line)."""
    n, m = len(nom), len(vi)
    anchors = [(0, 0), (n, m)]
    if pairs:
        by_n: dict[str, list[int]] = {}
        by_v: dict[str, list[int]] = {}
        for s in nom:
            by_n.setdefault(s.img, []).append(s.idx)
        for s in vi:
            by_v.setdefault(s.img, []).append(s.idx)
        for p in pairs:
            ni = [k for im in p.ch for k in by_n.get(im, [])]
            vj = [k for im in p.vi for k in by_v.get(im, [])]
            if ni and vj:
                anchors += [(min(ni), min(vj)), (max(ni) + 1, max(vj) + 1)]
    anchors = sorted(set(anchors))
    mono, hi = [], 0
    for a, b in anchors:
        hi = max(hi, b)
        mono.append((a, min(hi, m)))
    xs = [a for a, _ in mono]
    out = []
    for i in range(n + 1):
        k = bisect_right(xs, i) - 1
        if k >= len(mono) - 1:
            out.append(float(mono[-1][1]))
            continue
        (x0, y0), (x1, y1) = mono[k], mono[k + 1]
        out.append(y0 if x1 == x0 else y0 + (y1 - y0) * (i - x0) / (x1 - x0))
    return out


def _moves(cfg: NomAlignConfig) -> list[tuple[int, int]]:
    g = cfg.max_group
    mv = [
        (a, b)
        for a in range(1, g + 1)
        for b in range(1, g + 1)
        if a == 1 or b == 1 or (a, b) == (2, 2)
    ]
    return mv + [(1, 0), (0, 1)] if cfg.allow_skip else mv  # no row may have an empty side


def align_sentences(
    nom: list[Sentence],
    vi: list[Sentence],
    table: ReadingTable,
    cfg: NomAlignConfig,
    pairs: list[PagePair] | None = None,
) -> list[tuple[int, int, int, int]]:
    """Moves `(i, a, j, b)` in order: Nom sentences `i..i+a` with Vietnamese `j..j+b` (`a` or `b` may be 0)."""
    n, m = len(nom), len(vi)
    if n == 0 and m == 0:
        return []
    sc = _Scorer(nom, vi, table, cfg)
    center = _centers(nom, vi, pairs)
    mv = _moves(cfg)
    band = cfg.band or (25 if pairs else max(40, int(0.1 * max(n, m))))
    for _attempt in range(4):
        best: list[dict[int, tuple[float, tuple[int, int, int, int] | None]]] = [
            {} for _ in range(n + 1)
        ]
        best[0][0] = (0.0, None)

        def window(i: int, band: int = band) -> range:
            c = center[i]
            return range(max(0, int(c) - band), min(m, int(math.ceil(c)) + band) + 1)

        for i in range(n + 1):
            floor = min((v[0] for v in best[i].values()), default=0.0)
            for j in sorted(best[i]):
                base = best[i][j][0]
                if base > floor + cfg.beam:
                    continue  # far worse than the best state of this row
                for a, b in mv:
                    ni, nj = i + a, j + b
                    if ni > n or nj > m or nj not in window(ni):
                        continue
                    c = base + sc.cost(i, a, j, b)
                    cur = best[ni].get(nj)
                    if cur is None or c < cur[0] - 1e-12:
                        best[ni][nj] = (c, (i, a, j, b))
        if m in best[n]:
            break
        band *= 2
    else:
        raise AlignFailed(
            "no alignment path inside the band: the two texts are too different (wrong pairing?); "
            "with --allow-skip the DP may leave sentences unpaired (diagnosis only)"
        )
    out, i, j = [], n, m
    while (i, j) != (0, 0):
        step = best[i][j][1]
        out.append(step)
        i, j = step[0], step[2]
    out.reverse()
    return out


def _kind(a: int, b: int) -> str:
    if a == 0:
        return "vi-only"
    if b == 0:
        return "nom-only"
    return "1-1" if (a, b) == (1, 1) else ("1-n" if a == 1 else ("n-1" if b == 1 else "n-m"))


def decide_diff(
    ch: str,
    vi: str,
    kind: str,
    table: ReadingTable,
    cfg: NomAlignConfig,
    meaning: bool = False,
    suggester: Suggester | None = None,
    fb_map: dict[int, str] | None = None,
    ch_start: int = 0,
    stats: dict | None = None,
) -> tuple[list[dict] | None, bool, list[str]]:
    """`(text_diff, phonetic, unknown characters)` of one row. `None` is the `null` of a row that is not compared: a
    translation by meaning (`cfg.mode`, or a `meaning` range), or a merged row (1-n, n-1, n-m) unless
    `merged_diff="phonetic"`. The book type is declared, never guessed from the share of wrong characters."""
    want = (
        cfg.mode == "phonetic" and not meaning and (kind == "1-1" or cfg.merged_diff == "phonetic")
    )
    if not want:
        return None, False, []
    res = text_diff(ch, vi, table, cfg, suggester, fb_map, ch_start)
    if stats is not None:
        stats["rows"] = stats.get("rows", 0) + 1
        for k in ("suggested_fallback", "suggested_similar"):
            stats[k] = stats.get(k, 0) + getattr(res, k)
        why = stats.setdefault("yellow_by_reason", {})
        for k, v in res.warn_by_reason.items():
            why[k] = why.get(k, 0) + v
        if res.match_ratio < cfg.phonetic_min_match:
            stats.setdefault("low_match_rows", []).append(ch_start)
    return res.elements, True, res.unknown


def build_rows(
    nom: list[Sentence],
    vi: list[Sentence],
    moves: list[tuple[int, int, int, int]],
    table: ReadingTable,
    cfg: NomAlignConfig,
    ranges: Ranges | None = None,
    img_order: list[str] | None = None,
    suggester: Suggester | None = None,
    fb_map: dict[int, str] | None = None,
) -> BookResult:
    rows: list[Row] = []
    on: list[Sentence] = []
    ov: list[Sentence] = []
    for i, a, j, b in moves:
        kind = _kind(a, b)
        if kind == "nom-only":
            on += nom[i : i + a]  # only with allow_skip: diagnosis, never a row
            continue
        if kind == "vi-only":
            ov += vi[j : j + b]
            continue
        ch = "".join(s.text for s in nom[i : i + a])
        vt = " ".join(s.text for s in vi[j : j + b])
        first = nom[i]
        rows.append(Row(first.img, first.sid, ch, vt, None, kind, vi[j].img, nom_start=first.start))
    meaning_idx = ranges.resolve(rows, img_order or []) if ranges else set()
    unknown: dict[str, int] = {}
    stats: dict = {}
    for k, row in enumerate(rows):
        row.text_diff, row.phonetic, unk = decide_diff(
            row.ch_txt, row.vi_txt, row.kind, table, cfg, k in meaning_idx, suggester, fb_map,
            row.nom_start, stats,
        )  # fmt: skip
        for u in unk:
            unknown[u] = unknown.get(u, 0) + 1
    low = stats.pop("low_match_rows", [])
    low_ids = [r.sentence_id for r in rows if r.phonetic and r.nom_start in low]
    short = [("nom", s) for s in nom if s.short] + [("vi", s) for s in vi if s.short]
    rep = {"unknown_chars": unknown, "meaning_rows": len(meaning_idx),
           "low_match_rows": low_ids, **stats}  # fmt: skip
    return BookResult(rows, on, ov, rep, short)


def align_book(
    ch_pages: dict[str, list[str]],
    vi_pages: dict[str, list[str]],
    table: ReadingTable,
    cfg: NomAlignConfig | None = None,
    pairs: list[PagePair] | None = None,
    ranges: Ranges | None = None,
    suggester: Suggester | None = None,
    fb_pages: dict[str, list[str]] | None = None,
    hyphen_manual: frozenset[str] = frozenset(),
    hyphen_records: list[dict] | None = None,
    merges: list[dict] | None = None,
) -> BookResult:
    """`ch_pages` / `vi_pages`: `{image: [box transcription, ...]}` as in `read_label`.
    `fb_pages`: the second OCR (Nom only), same shape; with `allow_skip` it is not used (rows are not contiguous)."""
    cfg = cfg or NomAlignConfig()
    if pairs is None:
        pairs = pair_pages(list(ch_pages), list(vi_pages), order=cfg.nom_order)
    notes = []
    ch_order, vi_order = [], []
    for p in pairs:
        if p.ch and not p.vi:
            notes.append(f"no Vietnamese page for {p.ch}")
        if p.vi and not p.ch:
            notes.append(f"no Nom page for {p.vi}")
            continue  # a Vietnamese page without Nom page is not aligned (its Nom page was lost in the scan, so it has no partner)
        ch_order += [x for x in p.ch if x not in ch_order]
        vi_order += [x for x in p.vi if x not in vi_order]
    ch_chunks = [(k, clean_nom_lines(ch_pages[k])) for k in ch_order if k in ch_pages]
    vi_chunks = [
        (k, clean_vi_lines(vi_pages[k], cfg.strip_notes)) for k in vi_order if k in vi_pages
    ]
    nom = build_sentences(ch_chunks, "nom", cfg, merges=merges)
    vi = build_sentences(vi_chunks, "vi", cfg, hyphen_manual, hyphen_records, merges)
    moves = align_sentences(nom, vi, table, cfg, pairs)
    fb_map, skipped = None, []
    if fb_pages is not None and not cfg.allow_skip:
        fb_map, skipped = fallback_map(ch_chunks, fb_pages, cfg.fallback_max_dist)
    res = build_rows(nom, vi, moves, table, cfg, ranges, ch_order, suggester, fb_map)
    res.report.update(
        {"nom_sentences": len(nom), "vi_sentences": len(vi), "notes": notes,
         "mode": cfg.mode, "fallback_skipped_images": skipped,
         "hyphen_inconsistent": hyphen_inconsistent(join_vi(vi_chunks, cfg.hyphen, frozenset(cfg.names), hyphen_manual)[0], hyphen_manual),
         "images_missing_text": sorted({k for p in pairs for k in p.ch + p.vi} - set(ch_pages) - set(vi_pages))}
    )  # fmt: skip
    return res


__all__ = [
    "AlignFailed", "BookResult", "MASK", "Row", "Sentence", "Tok", "align_book", "align_sentences",
    "build_rows", "build_sentences", "decide_diff", "nfc", "pair_cost",
]  # fmt: skip
