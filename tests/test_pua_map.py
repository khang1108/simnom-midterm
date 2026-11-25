from src.ocr.runner import GLYPH_FIX_FILE, load_pua_map


def test_pua_map_translates_kim_private_chars():
    m = load_pua_map()
    assert "\U000f070b\U000f000b\U000f047c\U000f0815".translate(m) == "\U0003197a\U000313fa\U00031eb5〓"
    assert all(0xF0000 <= k <= 0xFFFFD or 0xE000 <= k <= 0xF8FF for k in m)


def test_fix_vi_ocr_only_repairs_invalid_syllables():
    import pytest
    from src.segmenter.core.cleaner import TextCleaner
    if not TextCleaner.valid_vi_syllables():
        pytest.skip("data/dict.db chưa được build")
    assert TextCleaner.fix_vi_ocr("kẻể có tộôi, Dđức Chúa cbo") == "kẻ có tội, Đức Chúa cho"
    assert TextCleaner.fix_vi_ocr("Phê-rô v.v...") == "Phê-rô v.v..."


def test_glyph_fix_maps_kim_misreads():
    assert "\U00020bc7吔髀".translate(load_pua_map(GLYPH_FIX_FILE)) == "吧吧\U0002a854"


def test_rover_takes_tesseract_word_only_when_it_matches_nom():
    from ocr_nom_align.tokens import syllable_key as k
    from src.ocr.runner import merge_vi_hypotheses
    keys = {k(x) for x in ["đàng", "được", "đấng", "chưng"]}
    assert merge_vi_hypotheses("Vì chúng, dàng ấy Dấng", "Vì chưng, đàng áy Đấng", keys) == "Vì chưng, đàng ấy Đấng"
    assert merge_vi_hypotheses("đi", "di", keys) == "đi"
