from __future__ import annotations

import json
from pathlib import Path

import pytest

from ocr_nom_align import NomAlignConfig, align_book
from ocr_nom_align.align import build_sentences
from ocr_nom_align.diff import text_diff
from ocr_nom_align.pages import lint_label, read_label_file, write_label
from ocr_nom_align.sentences import apply_merges, split_nom, split_vi
from ocr_nom_align.suggest import SimilarTable
from tests.helpers import write_label as write_test_label


def test_names_rule_only_when_counts_differ(table):
    r = text_diff("経告命", "Kinh Phi lip phê", table, NomAlignConfig(names=("Phi-lip-phê",)))
    warn = [e for e in r.elements if e["type"] == "warn"]
    assert warn and all(
        e["reviewed"] == 1 for e in warn
    )  # 2 characters against 3 syllables: yellow
    same = text_diff("経告命", "Kinh Phi lip", table, NomAlignConfig(names=("Phi-lip",)))
    assert [e["type"] for e in same.elements] == ["error"]  # the same count is judged by the table
    num = text_diff("経告命", "Kinh cáo 12", table)
    assert [e["reviewed"] for e in num.elements if e["type"] == "warn"] == [0]


def test_similar_table_broken_literal_and_bom(tmp_path):
    p = tmp_path / "s.csv"
    p.write_text('\ufeff"Input Character","Top 20 Similar Characters"\n"母","[\'毋\', \'毎\']"\n"毋","[oops"\n"𠀖","[]"\n',
                 encoding="utf-8")  # fmt: skip
    t = SimilarTable.load(p)
    assert t.similar("母") == ["毋", "毎"] and t.similar("毋") == [] and t.parse_errors == 1


def test_example_files_load():
    root = Path(__file__).resolve().parent.parent / "examples"
    t = SimilarTable.load(root / "similar.csv")
    assert t.parse_errors == 0 and t.data
    assert json.loads((root / "ranges.json").read_text(encoding="utf-8"))["meaning"]
    assert "A-ve" in (root / "hyphen_keep.txt").read_text(encoding="utf-8")


def test_short_list_merge_below_and_apply_merges():
    text = "Kinh cáo mệnh thiên chúa tạo. Ok. Một hai ba bốn năm sáu."
    spans, short = split_vi(text, 0, 5)
    assert len(spans) == 3 and [text[a:b] for a, b in short] == ["Ok."]  # listed, still kept
    merged, _ = split_vi(text, 3, 0)
    assert len(merged) == 2
    assert apply_merges(spans, {1: "prev"}) == [(0, spans[1][1]), spans[2]]
    assert apply_merges(spans, {1: "next"}) == [spans[0], (spans[1][0], spans[2][1])]
    assert apply_merges(spans, {1: "keep"}) == spans
    with pytest.raises(ValueError):
        apply_merges(spans, {0: "prev"})
    nspans, nshort = split_nom("経告命。天。天主造地人。", 0, 3)
    assert len(nspans) == 3 and len(nshort) == 1


def test_merges_file_applies_and_stale_line_is_an_error():
    cfg = NomAlignConfig()
    chunks = [("p.001.jpg", ["Kinh cáo mệnh. Ok. Thiên chúa tạo địa."])]
    base = build_sentences(chunks, "vi", cfg)
    assert len(base) == 3
    rec = {
        "side": "vi",
        "img_id": "p.001.jpg",
        "sentence_id": "p.001.jpg#2",
        "text": "Ok.",
        "merge": "prev",
    }
    merged = build_sentences(chunks, "vi", cfg, merges=[rec])
    assert len(merged) == 2 and merged[0].text == "Kinh cáo mệnh. Ok."
    keep = build_sentences(chunks, "vi", cfg, merges=[{**rec, "merge": "keep"}])
    assert len(keep) == 3  # keep needs no action
    with pytest.raises(ValueError, match="stale"):
        build_sentences(chunks, "vi", cfg, merges=[{**rec, "text": "Khác."}])


def test_strip_notes_off_keeps_marks_and_lint_lists_them(table, tmp_path):
    lab = write_test_label(
        tmp_path / "vi.txt", {"p.001.jpg": ["Kinh cáo[1] mệnh-", " đi\u0323a  (2)"]}, "vi"
    )
    lint = lint_label(read_label_file(lab))
    assert lint["note_mark"] and lint["line_end_hyphen"] == [{"img_id": "p.001.jpg", "box": 1}]
    assert lint["stray_whitespace"] and lint["not_nfc"]
    res = align_book({"p.001.jpg": ["経告命。"]}, {"p.001.jpg": ["Kinh cáo[1] mệnh."]}, table)
    assert "[1]" in res.rows[0].vi_txt
    res = align_book({"p.001.jpg": ["経告命。"]}, {"p.001.jpg": ["Kinh cáo[1] mệnh."]}, table,
                     NomAlignConfig(strip_notes=True))  # fmt: skip
    assert "[1]" not in res.rows[0].vi_txt


def test_write_label_changes_only_touched_images(tmp_path):
    p = tmp_path / "Label.txt"
    p.write_bytes(
        b'ch/a.001.jpg\t[{"transcription":"abc","points":[[0,0]]}]\r\n'
        b'ch/a.002.jpg\t[{"transcription":"xyz","points":[[0,0]]}]\r\n'
    )
    lf = read_label_file(p)
    lf.set_char("a.002.jpg", 0, 1, "y", "Y")
    out = tmp_path / "out.txt"
    write_label(lf, out)
    got = out.read_bytes().split(b"\r\n")
    assert got[0] == p.read_bytes().split(b"\r\n")[0]  # untouched line: byte for byte
    assert b"xYz" in got[1]
    with pytest.raises(ValueError):
        lf.set_char("a.002.jpg", 0, 1, "q", "Z")


def test_notebook_sets_explicit_mode():
    nb = (Path(__file__).resolve().parent.parent / "notebooks" / "align.ipynb").read_text(
        encoding="utf-8"
    )
    assert "auto" not in nb.replace("automatic", "") or '"auto"' not in nb
    assert 'MODE = \\"phonetic\\"' in nb or 'MODE = \\"meaning\\"' in nb
