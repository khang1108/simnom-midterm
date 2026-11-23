from __future__ import annotations

import json

from ocr_nom_align import NomAlignConfig, ReadingTable, align_book, text_diff
from ocr_nom_align.config import NomAlignConfig as Cfg
from ocr_nom_align.ranges import RangeError, Ranges
from ocr_nom_align.suggest import SimilarTable, Suggester, align_fallback
from ocr_nom_align.tableio import dump_diff, render_xlsx, write_csv, write_xlsx
from ocr_nom_align.validate import check_row, check_xlsx, similarity
from tests.helpers import READINGS


def tbl():
    return ReadingTable({c: {k} for c, k in READINGS.items()})


def row(ch, vi, d, sid="B.001.1"):
    return {
        "img_id": "B.001.jpg",
        "sentence_id": sid,
        "ch_txt": ch,
        "vi_txt": vi,
        "text_diff": json.dumps(d, ensure_ascii=False),
    }


def test_fallback_suggestion_keeps_positions_and_text():
    t = tbl()
    sg = Suggester(t)
    r = text_diff("経毋母福", "Kinh Thân Mẫu Phúc", t, Cfg(), sg, {1: "申"}, 0)
    assert r.elements == [
        {
            "nom_pos": [[1, 2]],
            "nom_sub_text": "毋",
            "vi_pos": [[5, 9]],
            "vi_sub_text": "Thân",
            "type": "warn",
            "reviewed": 0,
            "suggest": "申",
            "suggest_by": "fallback",
        }
    ]
    assert (
        r.suggested_fallback == 1
        and check_row(row("経毋母福", "Kinh Thân Mẫu Phúc", r.elements)) == []
    )


def test_similar_by_rank_not_hash():
    t = tbl()
    t.add("甲", "thân")
    t.add("乙", "thân")
    sim = SimilarTable({"毋": ["乙", "甲"]})
    assert Suggester(t, sim).suggest("毋", "Thân") == ("乙", "similar")
    sim = SimilarTable({"毋": ["甲", "乙"]})
    assert Suggester(t, sim).suggest("毋", "Thân") == ("甲", "similar")


def test_fallback_wins_over_similar_and_no_hit_stays_red():
    t = tbl()
    sg = Suggester(t, SimilarTable({"毋": ["申"]}))
    assert sg.suggest("毋", "Thân", "申")[1] == "fallback"
    assert Suggester(t).suggest("毋", "Thân", "毋") is None
    r = text_diff("経毋母福", "Kinh Thân Mẫu Phúc", t, Cfg(), Suggester(t))
    assert r.elements[0]["type"] == "error" and "reviewed" not in r.elements[0]


def test_fallback_of_other_length_aligned_by_edit_distance():
    m = align_fallback("経毋母福", "経申母X福", 0.5)
    assert m == {1: "申"}  # the inserted X gives nothing
    assert align_fallback("経毋母福", "経母", 0.5) == {}  # deletions give nothing
    assert align_fallback("経毋母福", "天地人之初神", 0.5) is None  # too different


def test_book_with_second_ocr_and_skipped_image():
    ch = {"B.001.jpg": ["経毋母福。"], "B.002.jpg": ["天主造地。"]}
    fb = {"B.001.jpg": ["経申母福。"]}
    vi = {"B.001.jpg": ["Kinh Thân Mẫu Phúc."], "B.002.jpg": ["Thiên Chúa Tạo Địa."]}
    t = tbl()
    r = align_book(ch, vi, t, Cfg(), suggester=Suggester(t), fb_pages=fb)
    assert r.rows[0].text_diff[0]["suggest"] == "申"
    assert r.report["fallback_skipped_images"] == ["B.002.jpg"]
    assert r.report["suggested_fallback"] == 1


def test_contract_key_order_reviewed_and_suggest_rules():
    base = {"nom_pos": [[1, 2]], "nom_sub_text": "毋", "vi_pos": [[5, 9]], "vi_sub_text": "Thân"}
    ch, vi = "経毋母福", "Kinh Thân Mẫu Phúc"
    ok = {"type": "warn", **base}
    assert check_row(row(ch, vi, [ok])) == []  # reviewed absent
    assert (
        check_row(row(ch, vi, [dict(reversed(list({**base, "type": "error"}.items())))])) == []
    )  # key order free
    assert check_row(row(ch, vi, [{**ok, "reviewed": 2}]))
    assert check_row(row(ch, vi, [{**ok, "suggest": "申"}]))  # without suggest_by
    assert (
        check_row(row(ch, vi, [{**ok, "suggest": "申", "suggest_by": "fallback", "reviewed": 1}]))
        == []
    )
    assert check_row(row(ch, vi, [{**base, "type": "error", "reviewed": 0}]))
    assert check_row(row("経毋\ufe0f母福", vi, []))  # selector
    assert check_row(row("", vi, []))  # empty side


def test_colour_sets_in_xlsx(tmp_path):
    t = tbl()
    r = align_book({"B.001.jpg": ["経毋母福。"]}, {"B.001.jpg": ["Kinh Thân Mẫu Phúc."]}, t, Cfg())
    for cols in (("FF0000", "FFFF00"), ("D32F2F", "D99A00")):
        cfg = Cfg(error_color=cols[0], warn_color=cols[1])
        csv_p, x = tmp_path / "b.csv", tmp_path / "b.xlsx"
        write_csv(r.rows, csv_p)
        write_xlsx(r.rows, x, cfg)
        assert check_xlsx(csv_p, x) == []
    try:
        Cfg(error_color="123456")
    except ValueError:
        pass
    else:
        raise AssertionError("colour outside the accepted set must be rejected")
    render_xlsx(csv_p, tmp_path / "r.xlsx")
    assert check_xlsx(csv_p, tmp_path / "r.xlsx") == []


def test_ranges_image_sentence_unknown_and_reversed(table):
    ch = {"B.010.jpg": ["経申母福。経告命。"], "B.009.jpg": ["天主造地。"]}
    vi = {"B.001.jpg": ["Kinh Thân Mẫu Phúc. Kinh Cáo Mệnh."], "B.002.jpg": ["Thiên Chúa Tạo Địa."]}
    from ocr_nom_align import PagePair

    pairs = [PagePair(["B.010.jpg"], ["B.001.jpg"]), PagePair(["B.009.jpg"], ["B.002.jpg"])]
    rg = Ranges(
        [{"from_sentence": "B.010.2", "to_sentence": "B.009.1"}]
    )  # T1: 010 is read before 009
    r = align_book(ch, vi, table, NomAlignConfig(), pairs, rg)
    assert [x.text_diff is None for x in r.rows] == [False, True, True]
    rg = Ranges([{"from_image": "B.010.jpg", "to_image": "B.010.jpg"}])
    r = align_book(ch, vi, table, NomAlignConfig(), pairs, rg)
    assert [x.text_diff is None for x in r.rows] == [True, True, False]
    try:
        align_book(
            ch,
            vi,
            table,
            NomAlignConfig(),
            pairs,
            Ranges([{"from_sentence": "X.1", "to_sentence": "B.009.1"}]),
        )
    except RangeError:
        pass
    else:
        raise AssertionError("unknown id must fail")


def test_similar_table_loader(tmp_path):
    p = tmp_path / "s.csv"
    p.write_text(
        '"Input Character","Top 20 Similar Characters"\n"𠀖","[\'共\', \'𠀗\']"\n"𠀧","not a list"\n',
        encoding="utf-8-sig",
    )
    s = SimilarTable.load(p)
    assert s.similar("𠀖") == ["共", "𠀗"] and s.similar("𠀧") == [] and s.parse_errors == 1


def test_quocngu_dictionary_header(tmp_path):
    p = tmp_path / "d.csv"
    p.write_text('"QuocNgu","SinoNom"\n"hán","漢"\n"tự","字"\n', encoding="utf-8-sig")
    t = ReadingTable.from_paths([p])
    assert t.readings("漢") == frozenset({t.key("hán")})


def test_similarity_counts_reviewed():
    s = similarity(
        [
            {
                "img_id": "B.001.jpg",
                "sentence_id": "B.001.1",
                "ch_txt": "経毋",
                "vi_txt": "Kinh Thân",
                "text_diff": dump_diff(
                    [
                        {
                            "nom_pos": [[1, 2]],
                            "nom_sub_text": "毋",
                            "vi_pos": [[5, 9]],
                            "vi_sub_text": "Thân",
                            "type": "warn",
                            "reviewed": 0,
                            "suggest": "申",
                            "suggest_by": "similar",
                        }
                    ]
                ),
            }
        ]
    )
    assert s["warn_unreviewed"] == 1 and s["suggested_similar_chars"] == 1
