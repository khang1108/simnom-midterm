"""Guards the notebook shape (same as ocr-engines): CONFIG -> BOOTSTRAP -> SETUP -> RUN -> REVIEW -> ENV.

The notebook only calls the CLI. `ocr_flow` appears there for the bootstrap and the environment
fingerprint, never in the package (`test_import_rules.py`).
"""

from __future__ import annotations

import ast
import json
import re
from pathlib import Path

from ocr_nom_align.cli import main

NB = Path(__file__).resolve().parents[1] / "notebooks" / "align.ipynb"
CONFIG_NAMES = {
    "GITHUB_TOKEN", "GIT_REPO", "GIT_BRANCH", "REPO_DIR", "FLOW_REPO", "FLOW_BRANCH", "FLOW_DIR",
    "BOOK", "CH_LABEL", "VI_LABEL", "IMAGE_MAP", "TABLES", "NAMES", "MODE", "DETAIL", "SCORE_MIN",
    "OUT_DIR", "_secret",
}  # fmt: skip


def _cells() -> list[dict]:
    return json.loads(NB.read_text(encoding="utf-8"))["cells"]


def _code() -> list[str]:
    return ["".join(c["source"]) for c in _cells() if c["cell_type"] == "code"]


def _clean(src: str) -> str:
    return "\n".join(re.sub(r"^(\s*)[!%].*$", r"\1pass", ln) for ln in src.split("\n"))


def test_shape_is_config_bootstrap_setup_run_review_env():
    code = _code()
    assert code[0].startswith("# CONFIG") and code[1].startswith("# BOOTSTRAP")
    assert code[-3].startswith("# RUN") and code[-2].startswith("# REVIEW")
    assert code[-1].startswith("# ENV")
    assert all(c.startswith("# SETUP") for c in code[2:-3])
    head = "".join(_cells()[0]["source"])
    assert "UNVERIFIED on hardware" in head and "`align`" in head


def test_every_cell_is_valid_python_and_has_no_saved_output():
    for i, c in enumerate(_cells()):
        assert not c.get("outputs"), f"cell {i} has saved output"
        if c["cell_type"] == "code":
            ast.parse(_clean("".join(c["source"])))


def test_config_vocabulary():
    tree = ast.parse(_clean(_code()[0]))
    names = {n.targets[0].id for n in tree.body if isinstance(n, ast.Assign)}
    names |= {n.name for n in tree.body if isinstance(n, ast.FunctionDef)}
    assert names == CONFIG_NAMES


def test_bootstrap_keeps_the_token_in_a_header():
    boot = next(c for c in _code() if c.startswith("# BOOTSTRAP"))
    assert "Bearer {GITHUB_TOKEN}" in boot and "/tarball/{_sha}" in boot and ".commit-sha" in boot
    assert 'git", "clone"' not in boot and "x-access-token" not in boot
    assert not re.search(r"https?://[^\s\"']*\{GITHUB_TOKEN\}", boot)
    assert "bootstrap.setup(" in boot and "gpu=False" in boot
    assert boot.count("tarball/") == 1
    for token in ("print(GITHUB_TOKEN", "echo $GITHUB_TOKEN"):
        assert token not in "\n".join(_code())


def _flags(command: str) -> set[str]:
    return {o for p in main.commands[command].params for o in p.opts}


def test_cells_call_only_real_cli_flags():
    text = "\n".join(_code())
    run, review = (c for c in _code() if c.startswith(("# RUN", "# REVIEW")))
    for flag in re.findall(r'"(--[a-z-]+)"', run) + ["--detail"]:
        assert flag in _flags("run"), flag
    assert '"--xlsx"' in review and "--xlsx" in _flags("check")
    assert '"--min"' in review and "--min" in _flags("score")
    assert "install -q" not in text and "git+https" not in text
