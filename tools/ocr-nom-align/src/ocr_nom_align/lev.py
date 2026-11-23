"""Weighted Levenshtein over token sequences, with the edit script.

Ties in the backtrace (walking from the end) prefer a gap to a diagonal step, so surplus tokens land
last: `経告命命命` against `Kinh Cáo Mình` leaves the *second and third* 命 as the surplus.
"""

from __future__ import annotations

from collections.abc import Callable, Sequence

_EPS = 1e-9


def _matrix(a: Sequence, b: Sequence, sub: Callable, gap: float) -> list[list[float]]:
    n, m = len(a), len(b)
    d = [[0.0] * (m + 1) for _ in range(n + 1)]
    for i in range(1, n + 1):
        d[i][0] = i * gap
    for j in range(1, m + 1):
        d[0][j] = j * gap
    for i in range(1, n + 1):
        ai, prev, row = a[i - 1], d[i - 1], d[i]
        for j in range(1, m + 1):
            row[j] = min(prev[j - 1] + sub(ai, b[j - 1]), prev[j] + gap, row[j - 1] + gap)
    return d


def edit_cost(a: Sequence, b: Sequence, sub: Callable, gap: float = 1.0) -> float:
    return _matrix(a, b, sub, gap)[len(a)][len(b)]


def edit_script(
    a: Sequence, b: Sequence, sub: Callable, gap: float = 1.0, tie: str = "gap"
) -> tuple[float, list[tuple[str, int | None, int | None]]]:
    """`(cost, ops)`; op is `("s", i, j)` (pair, equal or not), `("d", i, None)` (only in a) or `("i", None, j)`."""
    d = _matrix(a, b, sub, gap)
    i, j, ops = len(a), len(b), []
    while i > 0 or j > 0:
        if (
            tie == "diag"  # a pair first, then a deletion, then an insertion (second-OCR alignment)
            and i > 0
            and j > 0
            and abs(d[i][j] - (d[i - 1][j - 1] + sub(a[i - 1], b[j - 1]))) < _EPS
        ):
            ops.append(("s", i - 1, j - 1))
            i, j = i - 1, j - 1
        elif i > 0 and abs(d[i][j] - (d[i - 1][j] + gap)) < _EPS:
            ops.append(("d", i - 1, None))
            i -= 1
        elif j > 0 and abs(d[i][j] - (d[i][j - 1] + gap)) < _EPS:
            ops.append(("i", None, j - 1))
            j -= 1
        else:
            ops.append(("s", i - 1, j - 1))
            i, j = i - 1, j - 1
    ops.reverse()
    return d[len(a)][len(b)], ops


__all__ = ["edit_cost", "edit_script"]
