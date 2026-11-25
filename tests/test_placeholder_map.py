import csv
import json

from scripts.build_placeholder_map import build, check, write


def test_placeholder_map_locates_every_geta_and_validates(tmp_path):
    b = tmp_path / "B"
    (b / "ch").mkdir(parents=True)
    (b / "B_image_map.json").write_text(json.dumps({"pairs": [{"ch": ["B.002.jpg"], "vi": ["B.001.jpg"]}]}), encoding="utf-8")
    box = lambda t: {"transcription": t, "points": [[0, 0], [1, 0], [1, 1], [0, 1]]}
    (b / "ch" / "Label.txt").write_text("ch/B.002.jpg\t" + json.dumps([box("天地"), box("〓人")], ensure_ascii=False) + "\n", encoding="utf-8")
    (b / "ch" / "Label_char.txt").write_text("ch/B.002.jpg\t" + json.dumps([box(c) for c in "天地〓人"], ensure_ascii=False) + "\n", encoding="utf-8")
    diff = [{"nom_pos": [[2, 3]], "nom_sub_text": "〓", "vi_pos": [[10, 14]], "vi_sub_text": "lớn", "type": "error"}]
    with (b / "B.csv").open("w", encoding="utf-8-sig", newline="") as f:
        w = csv.writer(f)
        w.writerow(["img_id", "sentence_id", "ch_txt", "vi_txt", "text_diff"])
        w.writerow(["B.002.jpg", "B.002.1", "天地〓人。", "Thiên địa lớn nhân.", json.dumps(diff, ensure_ascii=False)])
    items = build(b, "B")
    assert [(i["label"], i["align"]) for i in items] == [
        ({"img_id": "B.002.jpg", "box_index": 1, "pos": 0, "char_box_index": 2}, {"sentence_id": "B.002.1", "pos": 2})]
    assert check(b, "B", items) == []
    assert check(b, "B", [{**items[0], "unicode": "U+3013"}])
    assert write(b, "B") == 1
