"""Regressions found in the full check of the v2.4 work."""

from __future__ import annotations

import csv
import json

from click.testing import CliRunner

from ocr_nom_align.cli import main
from ocr_nom_align.validate import check_row
from tests.helpers import make_book, write_char_label

CH = {"B.001.jpg": ["経告毋。", "天主造地。"], "B.002.jpg": ["神人聖。"]}
VI = {"B.001.jpg": ["Kinh cáo mẫu. Thiên chúa tạo địa."], "B.002.jpg": ["Thần nhân thánh."]}
FB = {"B.001.jpg": ["経告母。", "天主造地。"], "B.002.jpg": ["神人聖。"]}


def test_check_diff_with_only_ch_char_uses_the_box_file_order(table, tmp_path):
    b = make_book(tmp_path, table, CH, VI, fb=FB)
    cl = write_char_label(b["dir"] / "ch" / "Label_char.txt", CH)
    res = CliRunner().invoke(main, ["check-diff", str(b["csv"]), "--ch-char", str(cl)])
    assert "SYNC_CHAR" not in res.output and "LABELCHAR" not in res.output, res.output


def test_suggest_with_non_integer_position_is_an_error_not_a_crash():
    el = {"nom_pos": [["a", "b"]], "nom_sub_text": "母", "vi_pos": [[0, 3]],
          "vi_sub_text": "mẫu", "type": "warn", "reviewed": 0, "suggest": "毋",
          "suggest_by": "similar"}  # fmt: skip
    row = {"img_id": "B.001.jpg", "sentence_id": "B.001.1", "ch_txt": "母", "vi_txt": "mẫu",
           "text_diff": json.dumps([el], ensure_ascii=False)}  # fmt: skip
    assert any(m.startswith(("SUGGEST", "OOB")) for m in check_row(row))


def test_render_keeps_a_hand_fixed_text_diff(table, tmp_path):
    b = make_book(tmp_path, table, CH, VI)
    with b["csv"].open(encoding="utf-8-sig", newline="") as f:
        rows = list(csv.DictReader(f))
    rows[1]["text_diff"] = "[]"  # a human cleared the row
    with b["csv"].open("w", encoding="utf-8-sig", newline="") as f:
        w = csv.writer(f)
        w.writerow(list(rows[0]))
        w.writerows(list(r.values()) for r in rows)
    out = tmp_path / "fixed.xlsx"
    res = CliRunner().invoke(main, ["render", str(b["csv"]), "--xlsx", str(out)])
    assert res.exit_code == 0, res.output
    chk = CliRunner().invoke(main, ["check-diff", str(b["csv"]), "--xlsx", str(out)])
    assert chk.exit_code == 0, chk.output
