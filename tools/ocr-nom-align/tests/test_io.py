from __future__ import annotations

import json

from click.testing import CliRunner

from ocr_nom_align import (
    NomAlignConfig,
    align_book,
    check_csv,
    check_xlsx,
    similarity,
    write_csv,
    write_xlsx,
)
from ocr_nom_align.cli import main
from ocr_nom_align.tableio import read_csv
from ocr_nom_align.validate import check_row
from tests.helpers import READINGS, write_label


def book(table):
    ch = {"B.001.jpg": ["経申母福。経告命命命。翁聖丕離批"], "B.002.jpg": ["経申母福。"]}
    vi = {
        "B.001.jpg": ["Kinh Thân Cha Phúc. Kinh Cáo Mệnh. Ông Thánh Philiphê"],
        "B.002.jpg": ["Kinh Thân Mẫu Phúc."],
    }
    return align_book(ch, vi, table, NomAlignConfig(warn_names=True))


def test_csv_xlsx_roundtrip_and_colours(table, tmp_path):
    res = book(table)
    c = write_csv(res.rows, tmp_path / "b.csv")
    x = write_xlsx(res.rows, tmp_path / "b.xlsx")
    assert c.read_bytes().startswith(b"\xef\xbb\xbf")
    assert check_csv(c) == []
    assert check_xlsx(c, x) == []
    rows = read_csv(c)
    assert list(rows[0]) == ["img_id", "sentence_id", "ch_txt", "vi_txt", "text_diff"]
    types = {e["type"] for r in rows for e in json.loads(r["text_diff"])}
    assert types == {"error", "warn"}


def test_xlsx_colour_mismatch_is_caught(table, tmp_path):
    res = book(table)
    c = write_csv(res.rows, tmp_path / "b.csv")
    res.rows[0].text_diff = []  # xlsx written with no colour, csv still has the diff
    x = write_xlsx(res.rows, tmp_path / "b.xlsx")
    assert any("colours differ" in e for e in check_xlsx(c, x))


def test_check_row_catches_bad_diffs():
    base = {
        "img_id": "B.001.jpg",
        "sentence_id": "B.001.1",
        "ch_txt": "翁聖丕離批",
        "vi_txt": "Ông Thánh",
    }

    def el(npos, vpos, typ="error", nsub=None, vsub=None):
        return {"nom_pos": npos, "nom_sub_text": nsub if nsub is not None else "".join(base["ch_txt"][a:b] for a, b in npos),
                "vi_pos": vpos, "vi_sub_text": vsub if vsub is not None else "".join(base["vi_txt"][a:b] for a, b in vpos), "type": typ}  # fmt: skip

    def chk(d):
        return check_row({**base, "text_diff": json.dumps(d, ensure_ascii=False)})

    assert chk([el([[1, 3]], [])]) == []
    assert chk([el([[1, 3]], []), el([[2, 5]], [], "warn")])  # overlap
    assert chk([el([[0, 2]], [[3, 4]])])  # vi range starts on a space
    assert chk([el([[0, 9]], [])])  # outside the cell
    assert chk([el([[1, 3]], [], nsub="x")])
    assert chk([el([], [])])
    assert chk([el([[1, 3]], [], "bad")])
    assert check_row({**base, "text_diff": "[]"}) == []
    assert check_row({**base, "text_diff": "null"}) == []
    assert check_row({**base, "text_diff": ""})  # empty cell is not null
    assert check_row({**base, "sentence_id": "X.1"})
    assert check_row({**base, "ch_txt": "a\nb"})


def test_similarity_formula():
    def r(ch, vi, diff):
        return {"ch_txt": ch, "vi_txt": vi, "text_diff": json.dumps(diff, ensure_ascii=False)}

    red1 = {
        "nom_pos": [[2, 3]],
        "nom_sub_text": "母",
        "vi_pos": [[10, 13]],
        "vi_sub_text": "Cha",
        "type": "error",
    }
    red2 = {
        "nom_pos": [[3, 5]],
        "nom_sub_text": "命命",
        "vi_pos": [],
        "vi_sub_text": "",
        "type": "error",
    }
    yel = {
        "nom_pos": [[2, 5]],
        "nom_sub_text": "丕離批",
        "vi_pos": [[10, 18]],
        "vi_sub_text": "Philiphê",
        "type": "warn",
    }
    rows = [
        r("経申母福。", "Kinh Thân Mẫu Phúc.", []),  # 4
        r("経告命命命。", "Kinh Cáo Mệnh.", [red2]),  # 5
        r("翁聖丕離批", "Ông Thánh Philiphê", [yel]),  # 5, 3 yellow
        r("経申母福天主造", "Kinh Thân Cha Phúc Thiên Chúa Tạo", [red1]),  # 7
        {"ch_txt": "経申母福。", "vi_txt": "Lạy Nữ Vương.", "text_diff": "null"},
    ]
    s = similarity(rows)
    assert s["nom_chars_phonetic"] == 21 and s["yellow_chars"] == 3 and s["red_chars"] == 3
    assert abs(s["similarity"] - (1 - 3 / 18) * 100) < 1e-9
    assert s["null_rows"] == 1 and abs(s["null_rate"] - 0.2) < 1e-9


def test_mask_not_counted_in_similarity():
    rows = [{"ch_txt": "経[MASK]福。", "vi_txt": "Kinh[MASK]Phúc.", "text_diff": "[]"}]
    assert similarity(rows)["scored_chars"] == 2


def test_cli_run_check_score(table, tmp_path):
    ch = write_label(tmp_path / "chL.txt", {"B.001.jpg": ["経申母福。経告命命命。"]}, "ch")
    vi = write_label(
        tmp_path / "viL.txt", {"B.001.jpg": ["Kinh Thân Mẫu Phúc. Kinh Cáo Mệnh."]}, "vi"
    )
    lex = tmp_path / "lab_dict.csv"
    lex.write_text(
        "char,syllable,note\n" + "\n".join(f"{c},{k},hv:1" for c, k in READINGS.items()) + "\n",
        encoding="utf-8",
    )
    out, xl = tmp_path / "o" / "B.csv", tmp_path / "o" / "B.xlsx"
    runner = CliRunner()
    res = runner.invoke(
        main,
        [
            "run",
            "--mode",
            "phonetic",
            "--ch",
            str(ch),
            "--vi",
            str(vi),
            "--table",
            str(lex),
            "--book",
            "B",
            "--out-dir",
            str(tmp_path / "o"),
        ],
    )
    assert res.exit_code == 0, res.output
    assert "similarity=" in res.output
    assert runner.invoke(main, ["check", str(out), "--xlsx", str(xl)]).exit_code == 0
    assert json.loads(runner.invoke(main, ["score", str(out)]).output)["red_chars"] == 2
    assert json.loads((out.parent / "B_align_report.json").read_text(encoding="utf-8"))[
        "kinds"
    ] == {"1-1": 2}


def test_cli_needs_a_table(tmp_path):
    ch = write_label(tmp_path / "c.txt", {"B.001.jpg": ["経申母福。"]})
    vi = write_label(tmp_path / "v.txt", {"B.001.jpg": ["Kinh Thân Mẫu Phúc."]}, "vi")
    res = CliRunner().invoke(
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
            "B",
            "--out-dir",
            str(tmp_path),
        ],
        env={"NOM_ALIGN_TABLE": ""},
    )
    assert res.exit_code != 0 and "reading table" in res.output
