"""`text_diff` of one row: where the Sino-Nom text and its Vietnamese reading differ.

Levenshtein over tokens (characters against syllables). A pair is *equal* when the syllable is a reading of the
character. Runs of unequal pairs and gaps become one element each; a run is `warn` (yellow) for a number against
Nom characters or a listed name of another length, otherwise `error` (red). A single unequal pair that a second OCR
text or the similar-character table can mend is a one-pair `warn` with `suggest` / `suggest_by` (the text and the
alignment do not change). `[MASK]` splits both texts: segment k of one side pairs with segment k of
the other, and the mask itself is never in a `pos`.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from functools import lru_cache

from .config import NomAlignConfig
from .lev import edit_script
from .readings import ReadingTable
from .suggest import Suggester
from .tokens import MASK, PLACEHOLDER, Tok, mask_spans, nfc, nom_tokens, syllable_key, vi_tokens


@dataclass
class DiffResult:
    elements: list[dict]
    n_nom: int = 0
    n_vi: int = 0
    compat: int = 0  # aligned pairs that are equal or unknown (not a known mismatch)
    unknown: list[str] = field(default_factory=list)  # Nom characters found in no table
    suggested_fallback: int = 0
    suggested_similar: int = 0
    warn_by_reason: dict[str, int] = field(
        default_factory=dict
    )  # name | number | heuristic | suggest_*

    @property
    def match_ratio(self) -> float:
        m = max(self.n_nom, self.n_vi)
        return self.compat / m if m else 1.0


def classify(ch: Tok, syl: Tok, table: ReadingTable) -> str:
    """`match` | `mismatch` | `unknown` | `placeholder` | `num`."""
    if ch.text == PLACEHOLDER:
        return "placeholder"
    if syl.kind == "num":
        return "num"
    rs = table.readings(ch.text)
    if not rs:
        return "unknown"
    return "match" if table.key(syl.text) in rs else "mismatch"


def pair_cost(kind: str, cfg: NomAlignConfig) -> float:
    return {
        "match": 0.0,
        "mismatch": cfg.mismatch_cost,
        "placeholder": cfg.mismatch_cost,
        "unknown": cfg.unknown_cost,
        "num": cfg.unknown_cost,
    }[kind]


def _ok(kind: str, cfg: NomAlignConfig) -> bool:
    return kind == "match" or (kind == "unknown" and cfg.unknown_policy == "match")


def _element(
    ch: str, vi: str, nt: list[Tok], vt: list[Tok], typ: str, reviewed: int | None = None,
    suggest: str | None = None, by: str | None = None,
) -> dict:  # fmt: skip
    nom_pos = [[nt[0].start, nt[-1].end]] if nt else []
    vi_pos = [[vt[0].start, vt[-1].end]] if vt else []
    el = {
        "nom_pos": nom_pos,
        "nom_sub_text": ch[nom_pos[0][0] : nom_pos[0][1]] if nom_pos else "",
        "vi_pos": vi_pos,
        "vi_sub_text": vi[vi_pos[0][0] : vi_pos[0][1]] if vi_pos else "",
        "type": typ,
    }
    if typ == "warn":  # `reviewed` is written on every warn, in this order
        el["reviewed"] = reviewed or 0
        if suggest is not None:
            el["suggest"], el["suggest_by"] = suggest, by
    return el


@lru_cache(maxsize=8)
def _name_seqs(names: tuple[str, ...]) -> frozenset[tuple[str, ...]]:
    return frozenset(
        tuple(syllable_key(t.text) for t in vi_tokens(nfc(n))) for n in names if n.strip()
    )


def _is_name(vt: list[Tok], names: tuple[str, ...]) -> bool:
    """The Vietnamese side of a run is a whole proper name or a run of syllables inside one."""
    seq = tuple(syllable_key(t.text) for t in vt)
    if not seq:
        return False
    return any(
        seq == full[k : k + len(seq)]
        for full in _name_seqs(names)
        for k in range(len(full) - len(seq) + 1)
    )


def _group_type(nt: list[Tok], vt: list[Tok], cfg: NomAlignConfig) -> tuple[str, str]:
    """`(type, reason)`: `error`, or `warn` with `number` | `name` | `heuristic`."""
    if any(t.text == PLACEHOLDER for t in nt):
        return "error", ""
    if cfg.warn_numbers and nt and any(t.kind == "num" for t in vt):
        return "warn", "number"
    # a listed name is yellow only when the counts differ; the same count is judged by the table
    if cfg.names and nt and len(nt) != len(vt) and _is_name(vt, cfg.names):
        return "warn", "name"
    if (
        cfg.warn_names
        and nt
        and vt
        and len(nt) != len(vt)
        and all(t.text[:1].isupper() for t in vt)
    ):
        return "warn", "heuristic"
    return "error", ""


def text_diff(
    ch: str,
    vi: str,
    table: ReadingTable,
    cfg: NomAlignConfig | None = None,
    suggester: Suggester | None = None,
    fb_map: dict[int, str] | None = None,
    ch_start: int = 0,
) -> DiffResult:
    """Diff of two NFC cells. Positions refer to `ch` and `vi` exactly as given (call `nfc` first).
    `fb_map`: second-OCR characters by offset in the Nom stream; `ch_start`: stream offset of `ch[0]`."""
    cfg = cfg or NomAlignConfig()
    cs, vs = mask_spans(ch), mask_spans(vi)
    if len(cs) != len(vs):  # masks do not pair up: ignore them and align jointly
        cs, vs = [(0, len(ch))], [(0, len(vi))]
        ch_t = [t for a, b in mask_spans(ch) for t in nom_tokens(ch, a, b)]
        vi_t = [t for a, b in mask_spans(vi) for t in vi_tokens(vi, a, b)]
        segs = [(ch_t, vi_t)]
    else:
        segs = [
            (nom_tokens(ch, a, b), vi_tokens(vi, c, d))
            for (a, b), (c, d) in zip(cs, vs, strict=True)
        ]
    res = DiffResult([])
    for nt, vt in segs:
        res.n_nom += len(nt)
        res.n_vi += len(vt)
        _, ops = edit_script(
            nt, vt, lambda a, b: pair_cost(classify(a, b, table), cfg), cfg.gap_cost
        )
        run_n: list[Tok] = []
        run_v: list[Tok] = []

        def flush(run_n=run_n, run_v=run_v) -> None:
            if run_n or run_v:
                typ, why = _group_type(run_n, run_v, cfg)
                res.elements.append(_element(ch, vi, run_n, run_v, typ, 1 if why == "name" else 0))
                if why:
                    res.warn_by_reason[why] = res.warn_by_reason.get(why, 0) + 1
                run_n.clear()
                run_v.clear()

        for op, i, j in ops:
            if op == "s":
                kind = classify(nt[i], vt[j], table)
                if kind != "mismatch":
                    res.compat += 1 if kind != "placeholder" else 0
                if kind == "unknown":
                    res.unknown.append(nt[i].text)
                if _ok(kind, cfg):
                    flush()
                    continue
                if suggester is not None and kind in ("mismatch", "unknown"):
                    hit = suggester.suggest(
                        nt[i].text, vt[j].text, (fb_map or {}).get(ch_start + nt[i].start)
                    )
                    if hit:
                        flush()
                        c, by = hit
                        res.elements.append(_element(ch, vi, [nt[i]], [vt[j]], "warn", 0, c, by))
                        res.suggested_fallback += by == "fallback"
                        res.suggested_similar += by == "similar"
                        res.warn_by_reason[f"suggest_{by}"] = (
                            res.warn_by_reason.get(f"suggest_{by}", 0) + 1
                        )
                        continue
                run_n.append(nt[i])
                run_v.append(vt[j])
            elif op == "d":
                run_n.append(nt[i])
            else:
                run_v.append(vt[j])
        flush()
    return res


def predicted_diff(ch: str, vi: str) -> list[dict]:
    """A row predicted wholesale (Nom from the reading, or reading from Nom): one yellow element each side."""
    ch, vi = nfc(ch), nfc(vi)
    nt = [t for a, b in mask_spans(ch) for t in nom_tokens(ch, a, b)]
    vt = [t for a, b in mask_spans(vi) for t in vi_tokens(vi, a, b)]
    return [_element(ch, vi, nt, vt, "warn", 0)] if nt or vt else []


__all__ = ["MASK", "DiffResult", "classify", "pair_cost", "predicted_diff", "text_diff"]
