import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from ocr_nom_align.validate import check_csv, check_xlsx

from src.aligner.book_aligner import BookAligner
from src.evaluator.exporter import AlignmentExporter
from src.ocr.ppocr_adapter import PPOCRAdapter
from src.segmenter.core.cleaner import TextCleaner


class DictionaryStub:
    def is_phonetic_match(self, char, syllable):
        return {"天": "thiên", "地": "địa", "経": "kinh", "申": "thân", "母": "mẫu", "福": "phúc"}.get(char) == syllable.lower()


class V24ComplianceTests(unittest.TestCase):
    def test_exporter_xlsx_colors_pass_official_check_xlsx(self):
        rows = [
            {
                "img_id": "Book.001.jpg",
                "sentence_id": "Book.001.1",
                "ch_txt": "経申母福。",
                "vi_txt": "Kinh Thân Cha Phúc.",
                "text_diff": [
                    {
                        "nom_pos": [[2, 3]],
                        "nom_sub_text": "母",
                        "vi_pos": [[10, 13]],
                        "vi_sub_text": "Cha",
                        "type": "error",
                    }
                ],
            },
            {
                "img_id": "Book.001.jpg",
                "sentence_id": "Book.001.2",
                "ch_txt": "翁聖丕離批",
                "vi_txt": "Ông Thánh Philiphê",
                "text_diff": [
                    {
                        "nom_pos": [[2, 5]],
                        "nom_sub_text": "丕離批",
                        "vi_pos": [[10, 18]],
                        "vi_sub_text": "Philiphê",
                        "type": "warn",
                        "reviewed": 1,
                    }
                ],
            },
        ]
        for r in rows:
            self.assertEqual(AlignmentExporter.validate_row(r), [])

        with tempfile.TemporaryDirectory() as tmp:
            csv_path = Path(tmp) / "Book.csv"
            xlsx_path = Path(tmp) / "Book.xlsx"
            AlignmentExporter.export_csv(rows, str(csv_path))
            AlignmentExporter.export_xlsx(rows, str(xlsx_path))
            self.assertEqual(check_csv(csv_path), [])
            self.assertEqual(check_xlsx(csv_path, xlsx_path), [])

    def test_validate_row_rejects_v24_violations(self):
        base = {
            "img_id": "Book.001.jpg",
            "sentence_id": "Book.001.1",
            "ch_txt": "天",
            "vi_txt": "Thiên",
            "text_diff": [],
        }
        # Half-empty rows
        self.assertTrue(AlignmentExporter.validate_row({**base, "ch_txt": ""}))
        self.assertTrue(AlignmentExporter.validate_row({**base, "vi_txt": "   "}))

        # Unicode variation selector in ch_txt
        self.assertTrue(AlignmentExporter.validate_row({**base, "ch_txt": "天\uFE00"}))

        # [MASK] inside or overlapping pos
        mask_row = {
            **base,
            "ch_txt": "経[MASK]福。",
            "vi_txt": "Kinh[MASK]Phúc.",
            "text_diff": [
                {
                    "nom_pos": [[0, 7]],
                    "nom_sub_text": "経[MASK]",
                    "vi_pos": [[0, 4]],
                    "vi_sub_text": "Kinh",
                    "type": "error",
                }
            ],
        }
        self.assertTrue(any("[MASK]" in e for e in AlignmentExporter.validate_row(mask_row)))

        # Extra key ('reviewed') on 'error'
        err_extra = {
            **base,
            "ch_txt": "母",
            "vi_txt": "Cha",
            "text_diff": [
                {
                    "nom_pos": [[0, 1]],
                    "nom_sub_text": "母",
                    "vi_pos": [[0, 3]],
                    "vi_sub_text": "Cha",
                    "type": "error",
                    "reviewed": 1,
                }
            ],
        }
        self.assertTrue(AlignmentExporter.validate_row(err_extra))

        # Invalid reviewed=2 on warn
        warn_bad_rev = {
            **base,
            "ch_txt": "毋",
            "vi_txt": "Mẫu",
            "text_diff": [
                {
                    "nom_pos": [[0, 1]],
                    "nom_sub_text": "毋",
                    "vi_pos": [[0, 3]],
                    "vi_sub_text": "Mẫu",
                    "type": "warn",
                    "reviewed": 2,
                }
            ],
        }
        self.assertTrue(AlignmentExporter.validate_row(warn_bad_rev))

        # Invalid suggest_by on warn
        warn_bad_suggest = {
            **base,
            "ch_txt": "毋",
            "vi_txt": "Mẫu",
            "text_diff": [
                {
                    "nom_pos": [[0, 1]],
                    "nom_sub_text": "毋",
                    "vi_pos": [[0, 3]],
                    "vi_sub_text": "Mẫu",
                    "type": "warn",
                    "reviewed": 0,
                    "suggest": "母",
                    "suggest_by": "invalid_source",
                }
            ],
        }
        self.assertTrue(AlignmentExporter.validate_row(warn_bad_suggest))

    def test_split_boxes_to_chars_mask_selector_and_order(self):
        boxes = [
            {
                "transcription": " 天\uFE00 [MASK] 地 ",
                "points": [[300, 100], [360, 100], [360, 500], [300, 500]],
            },
            {
                "transcription": "福",
                "points": [[100, 100], [160, 100], [160, 200], [100, 200]],
            },
        ]
        sorted_cols = PPOCRAdapter.sort_boxes_reading_order(boxes, script_type="ch")
        char_boxes = PPOCRAdapter.split_boxes_to_chars(sorted_cols)
        self.assertEqual([b["transcription"] for b in char_boxes], ["天", "[MASK]", "地", "福"])
        # Không có khoảng trắng hay variation selector
        for b in char_boxes:
            t = b["transcription"]
            self.assertFalse(any(c.isspace() for c in t))
            self.assertNotIn("\uFE00", t)

    def test_cleaner_hyphens_and_variation_selectors(self):
        self.assertEqual(TextCleaner.normalize_nfc("天\uFE00地\U000E0100"), "天地")
        self.assertEqual(TextCleaner.fix_line_break_hyphens("tin-\ntưởng"), "tin tưởng")
        self.assertEqual(TextCleaner.fix_line_break_hyphens("Sài-\nGòn"), "Sài-Gòn")

    def test_book_aligner_no_half_empty_rows_and_filter_body_boxes(self):
        # Kiểm tra align_book không tạo hàng rỗng một vế khi một bên nhiều câu hơn
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "ch").mkdir()
            (root / "vi").mkdir()
            (root / "ch" / "Label.txt").write_text(
                f"ch/Book.001.jpg\t{json.dumps([{'transcription': '天地'}], ensure_ascii=False)}\n",
                encoding="utf-8",
            )
            (root / "vi" / "Label.txt").write_text(
                f"vi/Book.001.jpg\t{json.dumps([{'transcription': 'Thiên. Địa. Giả.'}], ensure_ascii=False)}\n",
                encoding="utf-8",
            )
            (root / "Book_image_map.json").write_text(
                json.dumps({"pairs": [{"ch": ["Book.001.jpg"], "vi": ["Book.001.jpg"]}]}),
                encoding="utf-8",
            )
            captured = []
            with patch.object(AlignmentExporter, "export_csv", side_effect=lambda rows, _: captured.extend(rows)), \
                 patch.object(AlignmentExporter, "export_xlsx"):
                BookAligner(DictionaryStub()).align_book(str(root), "Book")
            self.assertTrue(len(captured) >= 1)
            for row in captured:
                self.assertTrue(row["ch_txt"].strip())
                self.assertTrue(row["vi_txt"].strip())
                self.assertEqual(AlignmentExporter.validate_row(row), [])

        # Kiểm tra filter_body_boxes loại bỏ lề ngoài khung và viền khung, giữ lại cột ngắn trong khung
        ch_boxes = [
            {"transcription": "卉二", "points": [[3450, 4180], [3626, 4180], [3626, 4505], [3450, 4505]]},
            {"transcription": "中中中", "points": [[1500, 1560], [1540, 1560], [1540, 2244], [1500, 2244]]},
            {"transcription": "室", "points": [[680, 894], [778, 894], [778, 2604], [680, 2604]]},
            {"transcription": "些咍傷几庫咍執英俺爲", "points": [[2000, 950], [2130, 950], [2130, 5200], [2000, 5200]]},
            {"transcription": "阿們", "points": [[1770, 1000], [1900, 1000], [1900, 1300], [1770, 1300]]},
        ]
        kept_ch = BookAligner.filter_body_boxes(ch_boxes, script_type="ch")
        self.assertEqual([b["transcription"] for b in kept_ch], ["些咍傷几庫咍執英俺爲", "阿們"])


if __name__ == "__main__":
    unittest.main()
