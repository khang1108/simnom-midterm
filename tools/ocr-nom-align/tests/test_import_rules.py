"""No other module repo, no flow code, no third-party network or image libraries in this package."""

from __future__ import annotations

import ast
from pathlib import Path

SRC = Path(__file__).resolve().parents[1] / "src" / "ocr_nom_align"
FORBIDDEN = {"ocr_merge", "ocr_engines", "ocr_spellcheck", "ocr_layout", "ocr_export", "ocr_eval",
             "ocr_align", "ocr_flow", "ocr_lexicon", "boto3", "huggingface_hub", "PIL", "requests"}  # fmt: skip


def imported(path: Path) -> set[str]:
    out = set()
    for node in ast.walk(ast.parse(path.read_text(encoding="utf-8"))):
        if isinstance(node, ast.Import):
            out |= {a.name.split(".")[0] for a in node.names}
        elif isinstance(node, ast.ImportFrom) and node.module and node.level == 0:
            out.add(node.module.split(".")[0])
    return out


def test_no_forbidden_imports():
    for f in SRC.glob("*.py"):
        assert not imported(f) & FORBIDDEN, f.name


def test_only_cli_uses_click():
    for f in SRC.glob("*.py"):
        assert ("click" in imported(f)) == (f.name == "cli.py"), f.name


def test_every_module_imports():
    """Catches dead modules left over from an old API: a stale import fails here."""
    import importlib

    for f in SRC.glob("*.py"):
        if f.stem not in {"__main__", "__init__"}:
            importlib.import_module(f"ocr_nom_align.{f.stem}")
