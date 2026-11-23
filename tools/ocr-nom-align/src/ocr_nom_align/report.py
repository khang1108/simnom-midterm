"""The run report: counts, row kinds, similarity, unknown characters, orphans and the config used."""

from __future__ import annotations

from collections.abc import Iterable

from .config import NomAlignConfig


def kinds_count(rows: Iterable) -> dict[str, int]:
    out: dict[str, int] = {}
    for r in rows:
        out[r.kind] = out.get(r.kind, 0) + 1
    return out


def build_report(
    rows: list, stats: dict, cfg: NomAlignConfig, base: dict | None = None, **extra
) -> dict:
    """`rows`: `Row` objects; `stats`: `similarity(...)` of the written CSV; `base`: the aligner's own report."""
    return {**(base or {}), **stats, "kinds": kinds_count(rows), **extra, "config": cfg.to_dict()}


__all__ = ["build_report", "kinds_count"]
