"""ocr-nom-align: sentence-level alignment of Sino-Nom text with its Vietnamese reading via Levenshtein.

Public API: `align_book`, `text_diff`, `fill_text_diff`, `ReadingTable`, `write_csv`, `write_xlsx`, `check_csv`, `similarity`.
"""

from __future__ import annotations

__version__ = "0.2.0"

from .align import AlignFailed, BookResult, Row, align_book
from .config import NomAlignConfig, RunConfig, load_env, read_names
from .diff import DiffResult, predicted_diff, text_diff
from .pages import (
    LabelFile,
    PagePair,
    lint_label,
    pair_pages,
    read_image_map,
    read_label,
    read_label_file,
    write_label,
)
from .ranges import RangeError, Ranges
from .readings import ReadingTable, TableError
from .report import build_report
from .rows import fill_text_diff, keep_reviewed, read_pairs
from .suggest import SimilarTable, Suggester
from .sync import ApplyError, apply_suggestions
from .tableio import render_xlsx, write_csv, write_xlsx
from .validate import check_csv, check_diff, check_xlsx, similarity

__all__ = [
    "AlignFailed", "ApplyError", "BookResult", "LabelFile", "apply_suggestions", "check_diff", "lint_label", "read_label_file", "write_label", "RangeError", "Ranges", "SimilarTable", "Suggester", "keep_reviewed", "render_xlsx", "DiffResult", "NomAlignConfig", "PagePair", "ReadingTable", "Row", "RunConfig",
    "TableError", "__version__", "align_book", "build_report", "check_csv", "check_xlsx", "fill_text_diff",
    "load_env", "pair_pages", "predicted_diff", "read_image_map", "read_label", "read_names", "read_pairs",
    "similarity", "text_diff", "write_csv", "write_xlsx",
]  # fmt: skip
