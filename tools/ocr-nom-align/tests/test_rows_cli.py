from __future__ import annotations

import csv
import json

from click.testing import CliRunner

from ocr_nom_align import NomAlignConfig, ReadingTable, fill_text_diff, read_pairs
from ocr_nom_align.cli import main
from ocr_nom_align.tableio import read_csv
from tests.helpers import READINGS, write_label


def write_table(path):
    path.write_text("\n".join(f"{c},{s}" for c, s in READINGS.items()) + "\n", encoding="utf-8")
    return path


def write_pairs(path, rows):
    with path.open("w", encoding="utf-8", newline="") as f:
        w = csv.writer(f)
        w.writerow(["img_id", "sentence_id", "ch_txt", "vi_txt", "kind"])
        w.writerows(rows)
    return path


def test_read_pairs_csv_and_jsonl(tmp_path):
    p = write_pairs(tmp_path / "p.csv", [["B.001.jpg", "B.001.1", "天主", "Thiên Chúa", ""]])
    assert read_pairs(p)[0].kind == "1-1"
    j = tmp_path / "p.jsonl"
    j.write_text(
        json.dumps(
            {
                "img_id": "B.001.jpg",
                "sentence_id": "B.001.1",
                "ch_txt": "天",
                "vi_txt": "Thiên",
                "kind": "n-1",
            }
        )
        + "\n",
        encoding="utf-8",
    )
    assert read_pairs(j)[0].kind == "n-1"


def test_fill_text_diff_kinds(tmp_path):
    table = ReadingTable({c: {k} for c, k in READINGS.items()})
    p = write_pairs(
        tmp_path / "p.csv",
        [
            ["B.001.jpg", "B.001.1", "経告命命命。", "Kinh Cáo Mệnh.", ""],
            ["B.001.jpg", "B.001.2", "天主", "Thiên Chúa", ""],
            ["B.001.jpg", "B.001.3", "天主", "Thiên Chúa", "n-1"],
        ],
    )
    rows, rep = fill_text_diff(read_pairs(p), table, NomAlignConfig())
    assert rows[0].text_diff and rows[0].text_diff[0]["nom_sub_text"] == "命命"
    assert rows[1].text_diff == []
    assert rows[2].text_diff is None  # a merged row is null: a translation
    assert rep["unknown_chars"] == {}


def test_cli_diff_check_score(tmp_path):
    t = write_table(tmp_path / "lab_dict.csv")
    p = write_pairs(
        tmp_path / "p.csv", [["B.001.jpg", "B.001.1", "経告命命命。", "Kinh Cáo Mình.", ""]]
    )
    out = tmp_path / "b" / "Book.csv"
    r = CliRunner()
    res = r.invoke(
        main,
        [
            "diff",
            "--mode",
            "phonetic",
            str(p),
            "--out",
            str(out),
            "--xlsx",
            str(out.with_suffix(".xlsx")),
            "--report",
            str(tmp_path / "r.json"),
            "--table",
            str(t),
        ],
    )
    assert res.exit_code == 0, res.output
    assert "similarity=" in res.output
    assert (
        r.invoke(main, ["check", str(out), "--xlsx", str(out.with_suffix(".xlsx"))]).output.strip()
        == "ok"
    )
    assert json.loads((tmp_path / "r.json").read_text(encoding="utf-8"))["kinds"] == {"1-1": 1}
    assert (
        r.invoke(main, ["score", str(out), "--min", "99"]).exit_code == 1
    )  # one red element in a short row


def test_cli_run_book(tmp_path):
    t = write_table(tmp_path / "lab_dict.csv")
    ch = write_label(tmp_path / "ch.txt", {"B.001.jpg": ["経告命命命。", "天主造天地。"]}, "ch")
    vi = write_label(
        tmp_path / "vi.txt", {"B.001.jpg": ["Kinh Cáo Mệnh.", "Thiên Chúa tạo thiên địa."]}, "vi"
    )
    out = tmp_path / "out"
    r = CliRunner().invoke(
        main,
        [
            "run",
            "--mode",
            "phonetic",
            "--ch",
            str(ch),
            "--vi",
            str(vi),
            "--book",
            "Book",
            "--out-dir",
            str(out),
            "--table",
            str(t),
            "--detail",
        ],
    )
    assert r.exit_code == 0, r.output
    for name in ("Book.csv", "Book.xlsx", "Book_align_report.json", "Book_align_detail.jsonl"):
        assert (out / name).is_file(), name
    rows = read_csv(out / "Book.csv")
    assert [x["sentence_id"] for x in rows] == ["B.001.1", "B.001.2"]
    assert (
        CliRunner()
        .invoke(main, ["check", str(out / "Book.csv"), "--xlsx", str(out / "Book.xlsx")])
        .exit_code
        == 0
    )


def test_cli_table_from_env_and_missing(tmp_path):
    t = write_table(tmp_path / "lab_dict.csv")
    r = CliRunner().invoke(main, ["readings", "天地"], env={"NOM_ALIGN_TABLE": str(t)})
    assert (
        r.exit_code == 0 and "thiên" in r.output and "đia" in r.output
    )  # keys drop tone marks only
    r = CliRunner().invoke(main, ["readings", "天"], env={"NOM_ALIGN_TABLE": ""})
    assert r.exit_code == 1 and "empty reading table" in r.output


def test_cli_demo_names_file(tmp_path):
    t = write_table(tmp_path / "lab_dict.csv")
    names = tmp_path / "names.txt"
    names.write_text("# names\nPhi-lip-phê\nPhiliphê\n", encoding="utf-8")
    r = CliRunner().invoke(
        main, ["demo", "丕離批", "Philiphê", "--table", str(t), "--names", str(names)]
    )
    assert r.exit_code == 0, r.output
    assert '"type": "warn"' in r.output and '"reviewed": 1' in r.output
    # same count (3 characters, 3 syllables): judged by the table, not by the names file
    r = CliRunner().invoke(
        main, ["demo", "丕離批", "Phi-lip-phê", "--table", str(t), "--names", str(names)]
    )
    assert '"type": "warn"' not in r.output
