import json
import shutil
import tempfile
import unittest
from pathlib import Path

from PIL import Image

from scripts.prepare_books import (
    build_image_map_pairs,
    format_page_filename,
    parse_page_ranges,
    validate_book_config,
    validate_prepared_book,
)


class PrepareBooksTests(unittest.TestCase):
    def test_real_books_structure_config_is_exact(self):
        cfg_path = Path("configs/books_structure.json")
        all_cfg = json.loads(cfg_path.read_text(encoding="utf-8"))

        t1_pages = validate_book_config(all_cfg["tap1"])
        self.assertEqual(len(t1_pages["vi"]), 303)
        self.assertEqual(len(t1_pages["ch"]), 305)
        self.assertEqual(t1_pages["missing/ch"], [358, 359])
        self.assertEqual(len(t1_pages["intro"]), 4)
        self.assertEqual(len(t1_pages["ref"]), 1)
        self.assertEqual(len(t1_pages["toc"]), 7)
        self.assertEqual(len(t1_pages["blank"]), 10)
        self.assertEqual(len(t1_pages["misc"]), 6)

        t1_pairs = build_image_map_pairs(
            all_cfg["tap1"]["book_name"], all_cfg["tap1"]["pair_segments"], 636
        )
        self.assertEqual(len(t1_pairs), 305)
        self.assertEqual(t1_pairs[0]["vi"], ["T1_Sách Dạy Đấng Làm Người Sửa Mình (Tập 1).011.jpg"])
        self.assertEqual(t1_pairs[0]["ch"], ["T1_Sách Dạy Đấng Làm Người Sửa Mình (Tập 1).624.jpg"])
        self.assertEqual(t1_pairs[-1]["vi"], ["T1_Sách Dạy Đấng Làm Người Sửa Mình (Tập 1).314.jpg"])
        self.assertEqual(t1_pairs[-1]["ch"], ["T1_Sách Dạy Đấng Làm Người Sửa Mình (Tập 1).319.jpg"])

        t2_pages = validate_book_config(all_cfg["tap2"])
        self.assertEqual(len(t2_pages["vi"]), 331)
        self.assertEqual(len(t2_pages["ch"]), 331)
        self.assertEqual(t2_pages["missing/ch"], [])
        self.assertEqual(len(t2_pages["ref"]), 1)
        self.assertEqual(len(t2_pages["toc"]), 7)
        self.assertEqual(len(t2_pages["blank"]), 8)
        self.assertEqual(len(t2_pages["misc"]), 5)

        t2_pairs = build_image_map_pairs(
            all_cfg["tap2"]["book_name"], all_cfg["tap2"]["pair_segments"], 683
        )
        self.assertEqual(len(t2_pairs), 331)
        self.assertEqual(t2_pairs[0]["vi"], ["T1_Sách Dạy Đấng Làm Người Sửa Mình (Tập 2).007.jpg"])
        self.assertEqual(t2_pairs[0]["ch"], ["T1_Sách Dạy Đấng Làm Người Sửa Mình (Tập 2).674.jpg"])
        self.assertEqual(t2_pairs[-1]["vi"], ["T1_Sách Dạy Đấng Làm Người Sửa Mình (Tập 2).337.jpg"])
        self.assertEqual(t2_pairs[-1]["ch"], ["T1_Sách Dạy Đấng Làm Người Sửa Mình (Tập 2).344.jpg"])

    def test_range_parsing_and_filename_padding(self):
        self.assertEqual(parse_page_ranges("1, 3-5, 4"), [1, 3, 4, 5])
        self.assertEqual(parse_page_ranges(""), [])
        with self.assertRaises(ValueError):
            parse_page_ranges("5-3")
        with self.assertRaises(ValueError):
            parse_page_ranges("abc")
        self.assertEqual(format_page_filename("Book", 7, 683), "Book.007.jpg")
        self.assertEqual(format_page_filename("Book", 1005, 1200), "Book.1005.jpg")

    def test_config_rejects_overlap_and_gap(self):
        bad_cfg = {
            "book_name": "Book",
            "expected_pages": 4,
            "folders": {"vi": "1-2", "ch": "2-4"},
            "pair_segments": [{"type": "range", "vi_start": 1, "vi_end": 2, "ch_start": 4, "ch_end": 3}],
        }
        with self.assertRaises(ValueError):
            validate_book_config(bad_cfg)

        gap_cfg = {
            "book_name": "Book",
            "expected_pages": 4,
            "folders": {"vi": "1", "ch": "3-4"},
            "pair_segments": [],
        }
        with self.assertRaises(ValueError):
            validate_book_config(gap_cfg)

    def test_validate_prepared_book_catches_errors(self):
        cfg = {
            "book_name": "Book",
            "expected_pages": 4,
            "folders": {
                "misc": "1",
                "vi": "2",
                "ch": "3,4",
                "missing/ch": "3",
            },
            "pair_segments": [
                {"type": "range", "vi_start": 2, "vi_end": 2, "ch_start": 4, "ch_end": 4},
                {"type": "missing_vi", "ch": [3], "note": "missing vi"},
            ],
        }
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / "Book"
            for sub, pages in [("misc", [1]), ("vi", [2]), ("ch", [3, 4]), ("missing/ch", [3])]:
                (root / sub).mkdir(parents=True, exist_ok=True)
                for p in pages:
                    Image.new("RGB", (100, 140), color="white").save(root / sub / f"Book.{p:03d}.jpg")
            pairs = build_image_map_pairs("Book", cfg["pair_segments"], 4)
            (root / "Book_image_map.json").write_text(json.dumps({"pairs": pairs}), encoding="utf-8")

            self.assertEqual(validate_prepared_book(root, cfg), [])

            # Lỗi khi xóa 1 ảnh trong missing/ch
            (root / "missing" / "ch" / "Book.003.jpg").unlink()
            errs = validate_prepared_book(root, cfg)
            self.assertTrue(any("missing/ch" in e for e in errs))

            # Khôi phục rồi tạo ảnh xoay ngang trong vi/
            shutil.copy2(root / "ch" / "Book.003.jpg", root / "missing" / "ch" / "Book.003.jpg")
            Image.new("RGB", (200, 100), color="white").save(root / "vi" / "Book.002.jpg")
            errs_orient = validate_prepared_book(root, cfg)
            self.assertTrue(any("hướng ngang" in e for e in errs_orient))


if __name__ == "__main__":
    unittest.main()
