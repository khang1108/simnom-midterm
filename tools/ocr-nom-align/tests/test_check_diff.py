from __future__ import annotations

import csv
import json

from click.testing import CliRunner

from ocr_nom_align.cli import main
from ocr_nom_align.diff import predicted_diff
from ocr_nom_align.tableio import COLUMNS, dump_diff
from ocr_nom_align.validate import check_diff, check_row
from tests.helpers import make_book, write_char_label

CH = {"B.001.jpg": ["経告命。天主造地。"]}
VI = {"B.001.jpg": ["Kinh cáo mệnh. Thiên chúa tạo địa."]}


def codes(res, level=None):
    out = []
    for lvl, line in res:
        if level in (None, lvl):
            parts = line.split(": ")
            out.append(parts[1] if parts[0].startswith("row ") else parts[0])
    return out


def edit_csv(path, fn):
    with path.open(encoding="utf-8-sig", newline="") as f:
        rows = list(csv.DictReader(f))
    for r in rows:
        fn(r)
    with path.open("w", encoding="utf-8-sig", newline="") as f:
        w = csv.writer(f)
        w.writerow(COLUMNS)
        for r in rows:
            w.writerow([r[c] for c in COLUMNS])


def good_row(**kw):
    row = {"img_id": "B.001.jpg", "sentence_id": "B.001.1", "ch_txt": "経告命", "vi_txt": "Kinh cáo mệnh",
           "text_diff": "[]"}  # fmt: skip
    row.update(kw)
    return row


def el(**kw):
    base = {
        "nom_pos": [[0, 1]],
        "nom_sub_text": "経",
        "vi_pos": [[0, 4]],
        "vi_sub_text": "Kinh",
        "type": "error",
    }
    base.update(kw)
    return base


def row_with(*els, **kw):
    return good_row(text_diff=json.dumps(list(els), ensure_ascii=False), **kw)


def test_row_codes_each_once():
    cases = {
        "KEYS": row_with({"nom_pos": [[0, 1]], "type": "error"}),
        "OOB": row_with(el(nom_pos=[[2, 9]], nom_sub_text="命")),
        "SUB": row_with(el(nom_sub_text="告")),
        "OVERLAP": row_with(
            el(), el(nom_pos=[[0, 2]], nom_sub_text="経告", vi_pos=[[5, 8]], vi_sub_text="cáo")
        ),
        "EDGE": row_with(el(vi_pos=[[0, 5]], vi_sub_text="Kinh ")),
        "MASK": good_row(
            ch_txt="経[MASK]告",
            vi_txt="Kinh cáo",
            text_diff=json.dumps(
                [
                    el(
                        nom_pos=[[0, 8]],
                        nom_sub_text="経[MASK]告",
                        vi_pos=[[0, 8]],
                        vi_sub_text="Kinh cáo",
                    )
                ],
                ensure_ascii=False,
            ),
        ),  # fmt: skip
        "SELECTOR": good_row(ch_txt="経\ufe00告命"),
        "EMPTY": good_row(vi_txt=""),
        "FORM": good_row(vi_txt="Kinh cáo\nmệnh"),
        "REVIEWED": row_with(el(type="warn", reviewed=2)),
        "SUGGEST": row_with(el(type="warn", reviewed=0, suggest="母")),
    }
    for code, row in cases.items():
        got = [m.split(":")[0] for m in check_row(row)]
        assert code in got, (code, check_row(row))


def test_pending_suggestion_is_warning_and_final_error(table, tmp_path):
    b = make_book(tmp_path, table, {"B.001.jpg": ["経告毋。"]}, {"B.001.jpg": ["Kinh cáo mẫu."]},
                  fb={"B.001.jpg": ["経告母。"]})  # fmt: skip
    res = check_diff(b["csv"], ch_label=b["ch"], vi_label=b["vi"])
    assert "SUGGEST_PENDING" in codes(res, "warning") and not codes(res, "error")
    res = check_diff(b["csv"], ch_label=b["ch"], vi_label=b["vi"], final=True)
    assert "SUGGEST_PENDING" in codes(res, "error")
    res = check_diff(b["csv"], strict=True)
    assert "SUGGEST_PENDING" in codes(res, "error")  # --strict: warnings fail too


def test_sync_detects_one_character_in_csv_and_in_label(table, tmp_path):
    b = make_book(tmp_path, table, CH, VI)
    assert not codes(
        check_diff(b["csv"], xlsx=b["xlsx"], ch_label=b["ch"], vi_label=b["vi"]), "error"
    )
    edit_csv(
        b["csv"],
        lambda r: (
            r.update(ch_txt=r["ch_txt"].replace("命", "地"))
            if r["sentence_id"] == "B.001.1"
            else None
        ),
    )
    res = check_diff(b["csv"], ch_label=b["ch"], vi_label=b["vi"])
    assert any("SYNC" in line and "ch_txt" in line and "B.001.jpg" in line for _, line in res)
    b2 = make_book(tmp_path / "x", table, CH, VI)
    b2["ch"].write_text(b2["ch"].read_text(encoding="utf-8").replace("命", "地"), encoding="utf-8")
    assert "SYNC" in codes(check_diff(b2["csv"], ch_label=b2["ch"], vi_label=b2["vi"]), "error")


def test_sync_ignores_hyphen_and_whitespace_for_vietnamese(table, tmp_path):
    b = make_book(tmp_path, table, CH, VI)
    vi = b["vi"].read_text(encoding="utf-8").replace("Kinh cáo", "Kinh-cáo")
    b["vi"].write_text(vi, encoding="utf-8")
    assert not codes(
        check_diff(b["csv"], ch_label=b["ch"], vi_label=b["vi"]), "error"
    )  # `-` is ignored
    res = check_diff(b["csv"], ch_label=b["ch"], vi_label=b["vi"], sync_exact=True)
    assert "SYNC_EXACT" in codes(res, "warning")


def test_sync_skips_a_side_without_file(table, tmp_path):
    b = make_book(tmp_path, table, CH, VI)
    b["vi"].write_text(
        b["vi"].read_text(encoding="utf-8").replace("Kinh", "Xinh"), encoding="utf-8"
    )
    assert "SYNC" in codes(check_diff(b["csv"], ch_label=b["ch"], vi_label=b["vi"]), "error")
    assert not codes(check_diff(b["csv"], ch_label=b["ch"]), "error")  # Vietnamese side not checked


def _lost_page_book(tmp_path, table, nom_text, diff):
    ch = {"B.001.jpg": ["経告命。"]}
    vi = {"B.001.jpg": ["Kinh cáo mệnh."], "B.002.jpg": ["Thiên chúa."]}
    b = make_book(tmp_path, table, ch, vi)
    rows = [good_row(sentence_id="B.001.1", ch_txt="経告命。", vi_txt="Kinh cáo mệnh.", text_diff="[]"),
            {"img_id": "B.002.jpg", "sentence_id": "B.002.1", "ch_txt": nom_text, "vi_txt": "Thiên chúa.",
             "text_diff": dump_diff(diff)}]  # fmt: skip
    with b["csv"].open("w", encoding="utf-8-sig", newline="") as f:
        w = csv.writer(f)
        w.writerow(COLUMNS)
        for r in rows:
            w.writerow([r[c] for c in COLUMNS])
    missing = tmp_path / "missing_ch"
    missing.mkdir()
    (missing / "B.002.jpg").write_bytes(b"")
    return b, missing


def test_predicted_row_of_a_lost_page_passes_sync(table, tmp_path):
    b, missing = _lost_page_book(tmp_path, table, "天主。", predicted_diff("天主。", "Thiên chúa."))
    run = CliRunner().invoke(main, ["check-diff", str(b["csv"]), "--ch", str(b["ch"]), "--vi", str(b["vi"]),
                                    "--missing-ch", str(missing)])  # fmt: skip
    assert run.exit_code == 0, run.output
    # without the missing folder the same row must match Label.txt: it does not
    run = CliRunner().invoke(
        main, ["check-diff", str(b["csv"]), "--ch", str(b["ch"]), "--vi", str(b["vi"])]
    )
    assert run.exit_code == 1 and "SYNC" in run.output


def test_lost_page_side_must_be_one_whole_warn(table, tmp_path):
    b, missing = _lost_page_book(tmp_path, table, "天主。", [])
    run = CliRunner().invoke(main, ["check-diff", str(b["csv"]), "--ch", str(b["ch"]), "--vi", str(b["vi"]),
                                    "--missing-ch", str(missing)])  # fmt: skip
    assert run.exit_code == 1 and "whole warn" in run.output


def test_same_difference_on_a_normal_row_fails_even_when_fully_yellow(table, tmp_path):
    b = make_book(tmp_path, table, CH, VI)
    yellow = predicted_diff("経告命。", "Kinh cáo mệnh.")

    def fix(r):
        if r["sentence_id"] == "B.001.1":
            r["ch_txt"], r["text_diff"] = (
                "経告地。",
                dump_diff(predicted_diff("経告地。", r["vi_txt"])),
            )

    edit_csv(b["csv"], fix)
    assert yellow
    assert "SYNC" in codes(check_diff(b["csv"], ch_label=b["ch"], vi_label=b["vi"]), "error")


def test_plain_text_csv_runs_only_three_checks(tmp_path):
    p = tmp_path / "plain.csv"
    p.write_text(
        "ch_txt,vi_txt\n経告\ufe00,Kinh\n,x\n天主,Thiên\u0301 chúa\n", encoding="utf-8-sig"
    )
    res = check_diff(p)
    found = set(codes(res, "error"))
    assert found == {"SELECTOR", "EMPTY", "FORM"}, found
    assert any(lvl == "note" and "plain-text" in m for lvl, m in res)


def test_xlsx_colour_and_text_codes(table, tmp_path):
    b = make_book(tmp_path, table, {"B.001.jpg": ["経告毋。"]}, {"B.001.jpg": ["Kinh cáo mẫu."]})
    assert not codes(check_diff(b["csv"], xlsx=b["xlsx"]), "error")
    edit_csv(b["csv"], lambda r: r.update(vi_txt=r["vi_txt"] + " "))
    assert "XLSX" in codes(check_diff(b["csv"], xlsx=b["xlsx"]), "error")


def test_label_char_codes(table, tmp_path):
    b = make_book(tmp_path, table, CH, VI)
    char = b["dir"] / "ch" / "Label_char.txt"

    def run():
        res = check_diff(b["csv"], ch_label=b["ch"], vi_label=b["vi"], ch_char=char)
        return set(codes(res, "error"))

    write_char_label(char, CH)
    assert run() == set()
    chars = list("経告命。天主造地。")
    for label, boxes in {
        "SYNC_CHAR": [*chars[:2], "地", *chars[3:]],  # one character edited
        "LABELCHAR": [*chars[:2], "命。", *chars[3:]],  # a two-character box
    }.items():
        write_char_label(char, {"B.001.jpg": boxes})
        assert label in run(), label
    write_char_label(char, {"B.001.jpg": chars[:-1]})  # a box missing
    assert "LABELCHAR" in run()
    swapped = chars[:]
    swapped[4], swapped[5] = swapped[5], swapped[4]  # swapped boxes
    write_char_label(char, {"B.001.jpg": swapped})
    assert "LABELCHAR" in run()
