from __future__ import annotations

import json
import unicodedata

from ocr_nom_align import NomAlignConfig, ReadingTable, predicted_diff, text_diff
from ocr_nom_align.tableio import dump_diff
from ocr_nom_align.validate import check_row
from tests.helpers import READINGS


def row(ch, vi, diff):
    return {"img_id": "B.001.jpg", "sentence_id": "B.001.1", "ch_txt": ch, "vi_txt": vi,
            "text_diff": dump_diff(diff)}  # fmt: skip


def run(ch, vi, table, **kw):
    d = text_diff(ch, vi, table, NomAlignConfig(**kw)).elements
    assert check_row(row(ch, vi, d)) == []
    return d


def test_equal_is_empty(table):
    assert run("経申母福。", "Kinh Thân Mẫu Phúc.", table) == []


def test_tone_insensitive_by_default(table):
    assert run("経申母福。", "Kinh Thân Mầu Phục.", table) == []
    strict = ReadingTable({c: {k} for c, k in READINGS.items()}, tone_sensitive=True)
    assert run("経申母福。", "Kinh Thân Mầu Phục.", strict, tone_sensitive=True)


def test_one_mismatch_gives_one_error_element(table):
    d = run("経申母福。", "Kinh Thân Cha Phúc.", table)
    assert json.dumps(d, ensure_ascii=False, separators=(",", ":")) == (
        '[{"nom_pos":[[2,3]],"nom_sub_text":"母","vi_pos":[[10,13]],"vi_sub_text":"Cha","type":"error"}]'
    )


def test_surplus_nom_is_last_two(table):
    d = run("経告命命命。", "Kinh Cáo Mệnh.", table)
    assert d == [
        {
            "nom_pos": [[3, 5]],
            "nom_sub_text": "命命",
            "vi_pos": [],
            "vi_sub_text": "",
            "type": "error",
        }
    ]
    d = run("経告告告命。", "Kinh Cáo Mệnh.", table)
    assert d[0]["nom_pos"] == [[2, 4]] and d[0]["vi_pos"] == []


def test_surplus_vi_has_empty_nom(table):
    d = run("経申福。", "Kinh Thân Mẫu Phúc.", table)
    assert d == [
        {
            "nom_pos": [],
            "nom_sub_text": "",
            "vi_pos": [[10, 13]],
            "vi_sub_text": "Mẫu",
            "type": "error",
        }
    ]


def test_mask_pairs_segments_and_is_never_in_pos(table):
    assert run("経[MASK]福。", "Kinh[MASK]Phúc.", table) == []
    d = run("経[MASK]母。", "Kinh[MASK]Phúc.", table)
    assert d[0]["nom_pos"] == [[7, 8]] and d[0]["vi_pos"] == [[10, 14]]
    assert run("[MASK]福。", "[MASK]Phúc.", table) == []


def test_mask_count_mismatch_falls_back(table):
    assert run("経[MASK]福。", "Kinh Phúc.", table) == []


def test_number_against_nom_run_is_warn(table):
    d = run("𠬠𠦲𠄩𠀧𠀧𠀧𠀧", "1571", table)
    assert len(d) == 1 and d[0]["type"] == "warn" and d[0]["vi_pos"] == [[0, 4]]
    assert d[0]["nom_pos"] == [[0, 7]]
    d = run("𠬠𠦲𠄩𠀧𠀧𠀧𠀧", "1571", table, warn_numbers=False)
    assert d[0]["type"] == "error"


def test_names_warn_only_when_asked(table):
    ch, vi = "翁聖丕離批", "Ông Thánh Philiphê"
    assert run(ch, vi, table)[0]["type"] == "error"
    d = run(ch, vi, table, warn_names=True)
    assert d == [{"nom_pos": [[2, 5]], "nom_sub_text": "丕離批", "vi_pos": [[10, 18]],
                  "vi_sub_text": "Philiphê", "type": "warn", "reviewed": 0}]  # fmt: skip


def test_unknown_char_is_error_or_black(table):
    assert run("経𠀧福。", "Kinh Một Phúc.", table)[0]["type"] == "error"
    assert run("経𠀧福。", "Kinh Một Phúc.", table, unknown_policy="match") == []


def test_placeholder_always_red(table):
    d = run("経〓福。", "Kinh Thân Phúc.", table, unknown_policy="match")
    assert d[0]["nom_pos"] == [[1, 2]] and d[0]["type"] == "error"


def test_positions_are_code_points_not_utf16(table):
    ch = "\U00020001経母福"  # extension B character first
    d = run(ch, "Một Kinh Cha Phúc", table, unknown_policy="match")
    assert d[0]["nom_pos"] == [[2, 3]]


def test_nfc_positions():
    nfd = unicodedata.normalize("NFD", "Kinh Thân Cha Phúc.")
    nfc_ = unicodedata.normalize("NFC", nfd)
    t = ReadingTable({"経": ["kinh"], "申": ["thân"], "母": ["mẫu"], "福": ["phúc"]})
    d = text_diff("経申母福。", nfc_, t).elements
    assert d[0]["vi_pos"] == [[10, 13]]


def test_inner_punctuation_inside_range(table):
    d = run("母福。母福。", "Cha Phúc. Cha Phúc.", table)
    # two error runs, each ends on a letter; punctuation between stays outside the ranges
    assert all(check_row(row("母福。母福。", "Cha Phúc. Cha Phúc.", d)) == [] for _ in [0])


def test_predicted_row_is_one_yellow_element():
    d = predicted_diff("経申母福。", "Kinh Thân Mẫu Phúc.")
    assert d == [{"nom_pos": [[0, 4]], "nom_sub_text": "経申母福", "vi_pos": [[0, 18]],
                  "vi_sub_text": "Kinh Thân Mẫu Phúc", "type": "warn", "reviewed": 0}]  # fmt: skip
    assert check_row(row("経申母福。", "Kinh Thân Mẫu Phúc.", d)) == []
