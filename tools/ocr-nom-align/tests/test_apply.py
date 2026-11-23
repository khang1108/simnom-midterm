from __future__ import annotations

import csv
import json

from click.testing import CliRunner

from ocr_nom_align.cli import main
from ocr_nom_align.validate import check_diff, parse_diff
from tests.helpers import make_book, write_char_label

CH = {"B.001.jpg": ["経告毋。", "天主造地。"], "B.002.jpg": ["神人聖。"]}
VI = {"B.001.jpg": ["Kinh cáo mẫu. Thiên chúa tạo địa."], "B.002.jpg": ["Thần nhân thánh."]}
FB = {"B.001.jpg": ["経告母。", "天主造地。"], "B.002.jpg": ["神人聖。"]}


def book(tmp_path, table):
    return make_book(tmp_path, table, CH, VI, fb=FB)


def mark_reviewed(path, value=1):
    with path.open(encoding="utf-8-sig", newline="") as f:
        rows = list(csv.DictReader(f))
    for r in rows:
        r["text_diff"] = r["text_diff"].replace('"reviewed":0', f'"reviewed":{value}')
    with path.open("w", encoding="utf-8-sig", newline="") as f:
        w = csv.writer(f)
        w.writerow(list(rows[0]))
        for r in rows:
            w.writerow(list(r.values()))


def read_rows(path):
    with path.open(encoding="utf-8-sig", newline="") as f:
        return list(csv.DictReader(f))


def args(b, *extra):
    return [
        "apply",
        str(b["csv"]),
        "--ch",
        str(b["ch"]),
        "--vi",
        str(b["vi"]),
        "--xlsx",
        str(b["xlsx"]),
        *extra,
    ]


def test_round_trip_accept_and_files_agree(table, tmp_path):
    b = book(tmp_path, table)
    before = read_rows(b["csv"])
    assert "suggest" in before[0]["text_diff"]
    mark_reviewed(b["csv"])
    out = tmp_path / "applied"
    run = CliRunner().invoke(main, args(b, "--out-dir", str(out)))
    assert run.exit_code == 0, run.output
    assert "applied=1" in run.output
    rows = read_rows(out / "book.csv")
    assert rows[0]["ch_txt"] == "経告母。" and parse_diff(rows[0]["text_diff"]) == []
    assert "母" in (out / "Label.txt").read_text(encoding="utf-8") and "毋" not in (
        out / "Label.txt"
    ).read_text(encoding="utf-8")
    res = check_diff(
        out / "book.csv",
        xlsx=out / "book.xlsx",
        ch_label=out / "Label.txt",
        vi_label=b["vi"],
        final=True,
    )
    assert not [m for lvl, m in res if lvl == "error"]
    # other rows and the originals are untouched
    assert rows[1:] == before[1:]
    assert "毋" in b["ch"].read_text(encoding="utf-8")


def test_unreviewed_stays_pending_and_reject_rest_makes_it_red(table, tmp_path):
    b = book(tmp_path, table)
    out = tmp_path / "o1"
    run = CliRunner().invoke(main, args(b, "--out-dir", str(out)))
    assert (
        run.exit_code == 1 and "check-diff --final" in run.output
    )  # a pending suggestion cannot be submitted
    out = tmp_path / "o2"
    run = CliRunner().invoke(main, args(b, "--reject-rest", "--out-dir", str(out)))
    assert run.exit_code == 0, run.output
    assert "rejected=1" in run.output
    el = parse_diff(read_rows(out / "book.csv")[0]["text_diff"])[0]
    assert (
        list(el) == ["nom_pos", "nom_sub_text", "vi_pos", "vi_sub_text", "type"]
        and el["type"] == "error"
    )
    assert read_rows(out / "book.csv")[0]["ch_txt"] == "経告毋。"  # the text is unchanged
    assert (out / "Label.txt").read_bytes() == b["ch"].read_bytes()


def test_apply_refuses_when_label_was_edited_after_the_run(table, tmp_path):
    b = book(tmp_path, table)
    mark_reviewed(b["csv"])
    b["ch"].write_text(b["ch"].read_text(encoding="utf-8").replace("告", "命"), encoding="utf-8")
    out = tmp_path / "o"
    run = CliRunner().invoke(main, args(b, "--out-dir", str(out)))
    assert run.exit_code == 1 and "SYNC" in run.output
    assert not out.exists()  # nothing written


def test_other_positions_unchanged(table, tmp_path):
    b = make_book(tmp_path, table, {"B.001.jpg": ["経告毋天。"]}, {"B.001.jpg": ["Kinh cáo mẫu thiên."]},
                  fb={"B.001.jpg": ["経告母天。"]})  # fmt: skip
    mark_reviewed(b["csv"])
    out = tmp_path / "o"
    assert CliRunner().invoke(main, args(b, "--out-dir", str(out))).exit_code == 0
    assert read_rows(out / "book.csv")[0]["ch_txt"] == "経告母天。"


def test_label_char_beside_label_needs_the_flag(table, tmp_path):
    b = book(tmp_path, table)
    mark_reviewed(b["csv"])
    write_char_label(b["dir"] / "ch" / "Label_char.txt", CH)
    out = tmp_path / "o"
    run = CliRunner().invoke(main, args(b, "--out-dir", str(out)))
    assert run.exit_code == 1 and "Label_char.txt exists" in run.output
    assert not out.exists()


def test_label_char_updates_one_box_only(table, tmp_path):
    b = book(tmp_path, table)
    mark_reviewed(b["csv"])
    char = write_char_label(b["dir"] / "ch" / "Label_char.txt", CH)
    out = tmp_path / "o"
    run = CliRunner().invoke(main, args(b, "--ch-char", str(char), "--out-dir", str(out)))
    assert run.exit_code == 0, run.output
    old = char.read_text(encoding="utf-8").splitlines()
    new = (out / "Label_char.txt").read_text(encoding="utf-8").splitlines()
    assert len(old) == len(new)
    diff = [(a, c) for a, c in zip(old, new, strict=True) if a != c]
    assert len(diff) == 1  # only B.001.jpg changed, and in it only one box
    a, c = (json.loads(x.split("\t", 1)[1]) for x in diff[0])
    changed = [
        (i, p["transcription"], q["transcription"])
        for i, (p, q) in enumerate(zip(a, c, strict=True))
        if p != q
    ]
    assert changed == [(2, "毋", "母")]
    assert old[1] == new[1]  # the other image is byte for byte


def test_label_char_box_count_mismatch_exits_1(table, tmp_path):
    b = book(tmp_path, table)
    mark_reviewed(b["csv"])
    char = write_char_label(b["dir"] / "ch" / "Label_char.txt", CH)
    wrong = {**CH, "B.001.jpg": [CH["B.001.jpg"][0][:-1], CH["B.001.jpg"][1]]}
    write_char_label(char, wrong)
    out = tmp_path / "o"
    run = CliRunner().invoke(main, args(b, "--ch-char", str(char), "--out-dir", str(out)))
    assert run.exit_code == 1 and "LABELCHAR" in run.output
    assert not out.exists()


def test_in_place_keeps_backups(table, tmp_path):
    b = book(tmp_path, table)
    mark_reviewed(b["csv"])
    orig_label = b["ch"].read_text(encoding="utf-8")
    run = CliRunner().invoke(main, args(b, "--in-place"))
    assert run.exit_code == 0, run.output
    assert b["ch"].with_name("Label.txt.bak").read_text(encoding="utf-8") == orig_label
    assert "母" in b["ch"].read_text(encoding="utf-8")
    assert b["csv"].with_name("book.csv.bak").exists()


def test_needs_out_dir_or_in_place(table, tmp_path):
    b = book(tmp_path, table)
    run = CliRunner().invoke(main, args(b))
    assert run.exit_code == 1 and "--out-dir" in run.output
