from __future__ import annotations

from ocr_nom_align.sentences import split_nom, split_vi


def cut(text, spans):
    return [text[a:b] for a, b in spans]


def test_nom_split_and_keep_closers():
    t = "経申母福。経福実糝䋦。経告命」。"
    assert cut(t, split_nom(t)[0]) == ["経申母福。", "経福実糝䋦。", "経告命」。"]


def test_nom_short_sentence_joins_previous():
    t = "経申母福。天。経福実糝䋦。"
    assert cut(t, split_nom(t, 2)[0]) == ["経申母福。天。", "経福実糝䋦。"]


def test_vi_split_basic():
    t = "Kinh Thân Mẫu Phúc. Kinh Phúc Thật Tám Mối. Kinh Cáo Mình."
    assert cut(t, split_vi(t)[0]) == [
        "Kinh Thân Mẫu Phúc.",
        "Kinh Phúc Thật Tám Mối.",
        "Kinh Cáo Mình.",
    ]


def test_vi_no_split_on_initial_abbreviation_or_lowercase():
    t = "Ông A. Rô lạy Chúa. Tp. Huế đẹp lắm. Năm 1571. Vua lên ngôi"
    assert cut(t, split_vi(t)[0]) == [
        "Ông A. Rô lạy Chúa.",
        "Tp. Huế đẹp lắm.",
        "Năm 1571.",
        "Vua lên ngôi",
    ]
    t2 = "Lạy Cha v.v. và Con."
    assert len(split_vi(t2)[0]) == 1


def test_vi_split_on_semicolon_and_colon():
    t = "Thân Mẫu Phúc; Kinh Cáo Mình: Lạy Chúa."
    assert len(split_vi(t)[0]) == 3
