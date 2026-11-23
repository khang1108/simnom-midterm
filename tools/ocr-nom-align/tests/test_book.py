from __future__ import annotations

from ocr_nom_align import NomAlignConfig, PagePair, align_book, pair_pages
from ocr_nom_align.pages import join_vi, page_key


def test_page_key_and_pairing_by_number():
    assert page_key("B.002_1.jpg") < page_key("B.010.jpg")
    pairs = pair_pages(["B.001.jpg", "B.002.jpg"], ["B.001.jpg", "B.003.jpg"])
    assert [(p.ch, p.vi) for p in pairs] == [
        (["B.001.jpg"], ["B.001.jpg"]),
        (["B.002.jpg"], []),
        ([], ["B.003.jpg"]),
    ]


def test_pairing_by_position_when_numbers_differ():
    pairs = pair_pages(["B.010.jpg", "B.009.jpg"], ["B.001.jpg", "B.002.jpg"], order="desc")
    assert [(p.ch, p.vi) for p in pairs] == [
        (["B.010.jpg"], ["B.001.jpg"]),
        (["B.009.jpg"], ["B.002.jpg"]),
    ]


def test_hyphen_join():
    t, st = join_vi([("a", ["Tôi tin-"]), ("b", ["tưởng Chúa"])], "space")
    assert t == "Tôi tin tưởng Chúa" and st == [(0, "a"), (8, "b")]
    t, _ = join_vi([("a", ["Sài-"]), ("b", ["Gòn"])], "keep")
    assert t == "Sài-Gòn"


def test_one_to_one_book(table):
    ch = {"B.001.jpg": ["経申母福。経告命。"], "B.002.jpg": ["天主造地。"]}
    vi = {"B.001.jpg": ["Kinh Thân Mẫu Phúc. Kinh Cáo Mệnh."], "B.002.jpg": ["Thiên Chúa Tạo Địa."]}
    r = align_book(ch, vi, table)
    assert [x.sentence_id for x in r.rows] == ["B.001.1", "B.001.2", "B.002.1"]
    assert [x.kind for x in r.rows] == ["1-1"] * 3
    assert all(x.text_diff == [] for x in r.rows)
    assert r.orphans_nom == r.orphans_vi == []


def test_sentence_cut_by_page_break_is_whole_and_numbered_on_first_image(table):
    ch = {"B.001.jpg": ["経申母福。経告"], "B.002.jpg": ["命。天主造地。"]}
    vi = {"B.001.jpg": ["Kinh Thân Mẫu Phúc. Kinh Cáo"], "B.002.jpg": ["Mệnh. Thiên Chúa Tạo Địa."]}
    r = align_book(ch, vi, table)
    assert [(x.img_id, x.sentence_id, x.ch_txt) for x in r.rows] == [
        ("B.001.jpg", "B.001.1", "経申母福。"),
        ("B.001.jpg", "B.001.2", "経告命。"),
        ("B.002.jpg", "B.002.1", "天主造地。"),
    ]
    assert r.rows[1].vi_txt == "Kinh Cáo Mệnh."


def test_merge_when_vi_has_no_boundary(table):
    ch = {"B.001.jpg": ["経申母福。経告命。天主造地。"]}
    vi = {"B.001.jpg": ["Kinh Thân Mẫu Phúc, Kinh Cáo Mệnh. Thiên Chúa Tạo Địa."]}
    r = align_book(ch, vi, table)
    assert [x.kind for x in r.rows] == ["n-1", "1-1"]
    assert r.rows[0].sentence_id == "B.001.1" and r.rows[0].text_diff is None
    assert r.rows[1].text_diff == []


def test_merged_diff_phonetic_option(table):
    ch = {"B.001.jpg": ["経申母福。経告命。天主造地。"]}
    vi = {"B.001.jpg": ["Kinh Thân Mẫu Phúc, Kinh Cáo Mệnh. Thiên Chúa Tạo Địa."]}
    r = align_book(ch, vi, table, NomAlignConfig(merged_diff="phonetic"))
    assert r.rows[0].kind == "n-1" and r.rows[0].text_diff == []


def test_meaning_translation_is_null(table):
    ch = {"B.001.jpg": ["経申母福。"]}
    vi = {"B.001.jpg": ["Lạy Nữ Vương xin cầu cho chúng con luôn luôn."]}
    r = align_book(ch, vi, table, NomAlignConfig(mode="meaning"))
    assert r.rows[0].text_diff is None
    r = align_book(ch, vi, table, NomAlignConfig(mode="phonetic"))
    assert r.rows[0].text_diff


def test_no_row_has_an_empty_side_and_allow_skip_lists_orphans(table):
    ch = {"B.001.jpg": ["経申母福。経告命。天主造地。"]}
    vi = {"B.001.jpg": ["Kinh Thân Mẫu Phúc. Thiên Chúa Tạo Địa."]}
    r = align_book(ch, vi, table)
    assert all(x.ch_txt and x.vi_txt for x in r.rows) and not r.orphans_nom
    r = align_book(ch, vi, table, NomAlignConfig(allow_skip=True))
    assert [x.sentence_id for x in r.rows] == ["B.001.1", "B.001.3"]
    assert [s.sid for s in r.orphans_nom] == ["B.001.2"]
    assert all(x.kind in ("1-1", "1-n", "n-1", "n-m") for x in r.rows)


def test_mode_auto_is_rejected():
    import pytest

    with pytest.raises(ValueError):
        NomAlignConfig(mode="auto")


def test_ocr_noise_is_red_not_misaligned(table):
    ch = {"B.001.jpg": ["経申母福。経告命命命。天主造地。"]}
    vi = {"B.001.jpg": ["Kinh Thân Mẫu Phúc. Kinh Cáo Mệnh. Thiên Chúa Tạo Địa."]}
    r = align_book(ch, vi, table)
    assert [x.kind for x in r.rows] == ["1-1"] * 3
    assert r.rows[1].text_diff[0]["nom_sub_text"] == "命命"


def test_image_map_pairs_reverse_nom_order(table):
    ch = {"B.010.jpg": ["経申母福。"], "B.009.jpg": ["天主造地。"]}
    vi = {"B.001.jpg": ["Kinh Thân Mẫu Phúc."], "B.002.jpg": ["Thiên Chúa Tạo Địa."]}
    pairs = [PagePair(["B.010.jpg"], ["B.001.jpg"]), PagePair(["B.009.jpg"], ["B.002.jpg"])]
    r = align_book(ch, vi, table, pairs=pairs)
    assert [x.sentence_id for x in r.rows] == ["B.010.1", "B.009.1"]


def test_missing_pages_are_not_aligned(table):
    ch = {"B.001.jpg": ["経申母福。"], "B.002.jpg": ["天主造地。"]}
    vi = {"B.001.jpg": ["Kinh Thân Mẫu Phúc."]}
    r = align_book(ch, vi, table)
    assert len(r.rows) == 1 and any("B.002.jpg" in n for n in r.report["notes"])


def test_larger_book_is_fast_and_exact(table):
    import random

    rnd = random.Random(1)
    chars = list("経申母福告命天主造地人之初神")
    nom_lines, vi_lines = [], []
    for _ in range(150):
        k = rnd.randint(4, 9)
        cs = [rnd.choice(chars) for _ in range(k)]
        nom_lines.append("".join(cs) + "。")
        from tests.helpers import READINGS

        vi_lines.append(
            " ".join(READINGS[c].capitalize() if i == 0 else READINGS[c] for i, c in enumerate(cs))
            + "."
        )
    ch = {"B.001.jpg": nom_lines}
    vi = {"B.001.jpg": vi_lines}
    r = align_book(ch, vi, table)
    assert len(r.rows) == 150 and all(x.text_diff == [] for x in r.rows)
