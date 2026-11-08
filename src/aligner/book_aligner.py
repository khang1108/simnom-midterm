import os
import json
import logging
from typing import List, Dict, Any, Optional
from src.aligner.dp_align import PhoneticDPAligner
from src.dict_engine.lookup import DictionaryLookup
from src.segmenter import (
    TextCleaner, 
    PageStitcher, 
    RegexSentenceSplitter, 
    StatisticalSBDSplitter
)
from src.evaluator.exporter import AlignmentExporter

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger(__name__)

class BookAligner:
    def __init__(self, dict_lookup: Optional[DictionaryLookup] = None, method: str = "nlp"):
        self.dict_lookup = dict_lookup or DictionaryLookup()
        self.dp_aligner = PhoneticDPAligner(self.dict_lookup)
        self.cleaner = TextCleaner()
        self.method = method
        self.splitter = StatisticalSBDSplitter if method == "nlp" else RegexSentenceSplitter
        logger.info(f"Khởi tạo BookAligner với phương pháp: {self.method.upper()} (Splitter: {self.splitter.__name__})")

    @staticmethod
    def load_label_file(label_path: str) -> Dict[str, List[Dict[str, Any]]]:
        """Đọc file Label.txt (PPOCRLabel format) thành dictionary: {filename: [boxes]}."""
        pages = {}
        if not os.path.exists(label_path):
            return pages

        with open(label_path, "r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line or "\t" not in line:
                    continue
                parts = line.split("\t", 1)
                img_path = parts[0]
                img_name = os.path.basename(img_path)
                try:
                    boxes = json.loads(parts[1])
                    pages[img_name] = boxes
                except Exception as e:
                    logger.warning(f"Lỗi parse JSON trong {label_path} dòng {img_name}: {e}")
        return pages

    def align_book(
        self,
        book_dir: str,
        book_name: str,
        output_dir: Optional[str] = None
    ) -> Dict[str, Any]:
        """
        Thực hiện toàn bộ quy trình dóng hàng cho một cuốn sách:
        1. Đọc Label.txt của ch/ và vi/
        2. Ghép câu qua trang (stitching) theo thứ tự đọc
        3. Dóng hàng phonetic từng cặp câu Nôm - Quốc ngữ
        4. Xuất file .csv (UTF-8 BOM) và .xlsx (tô 3 màu)
        5. Đánh giá và trả về metrics
        """
        output_dir = output_dir or book_dir
        ch_label_path = os.path.join(book_dir, "ch", "Label.txt")
        vi_label_path = os.path.join(book_dir, "vi", "Label.txt")
        image_map_path = os.path.join(book_dir, f"{book_name}_image_map.json")

        if not os.path.exists(ch_label_path):
            raise FileNotFoundError(f"Không tìm thấy file {ch_label_path}")
        if not os.path.exists(vi_label_path):
            raise FileNotFoundError(f"Không tìm thấy file {vi_label_path}")

        ch_pages_data = self.load_label_file(ch_label_path)
        vi_pages_data = self.load_label_file(vi_label_path)

        # Đọc image_map nếu có
        image_map = []
        if os.path.exists(image_map_path):
            try:
                with open(image_map_path, "r", encoding="utf-8") as f:
                    image_map = json.load(f)
            except Exception as e:
                logger.warning(f"Không đọc được {image_map_path}: {e}")

        # Chuẩn bị danh sách trang theo thứ tự đọc
        # Nôm T1: Sắp xếp giảm dần theo số trang (ví dụ .636 -> .319)
        ch_images = sorted(ch_pages_data.keys(), reverse=True)
        # Quốc ngữ T1: Sắp xếp tăng dần theo số trang (ví dụ .001 -> .318)
        vi_images = sorted(vi_pages_data.keys())

        # Tạo cấu trúc trang cho stitcher
        ch_page_list = []
        for img in ch_images:
            boxes = ch_pages_data[img]
            # Nối text của các box theo thứ tự đọc đã sắp xếp sẵn trong Label.txt
            page_text = " ".join(b.get("transcription", "") for b in boxes if b.get("transcription"))
            ch_page_list.append({"img_id": img, "text": page_text})

        vi_page_list = []
        for img in vi_images:
            boxes = vi_pages_data[img]
            page_text = " ".join(b.get("transcription", "") for b in boxes if b.get("transcription"))
            vi_page_list.append({"img_id": img, "text": page_text})

        # Ghép câu xuyên trang
        logger.info(f"Đang ghép câu xuyên trang cho {len(ch_page_list)} trang Nôm (splitter={self.splitter.__name__})...")
        nom_sentences = PageStitcher.stitch_and_split_pages(
            ch_page_list, script="ch", cleaner=self.cleaner, splitter=self.splitter
        )
        logger.info(f"Đang ghép câu xuyên trang cho {len(vi_page_list)} trang Quốc ngữ (splitter={self.splitter.__name__})...")
        vi_sentences = PageStitcher.stitch_and_split_pages(
            vi_page_list, script="vi", cleaner=self.cleaner, splitter=self.splitter
        )

        logger.info(f"Tổng số câu Nôm: {len(nom_sentences)}, Tổng số câu Quốc ngữ: {len(vi_sentences)}")

        # Dóng hàng các câu
        aligned_rows = []
        max_len = max(len(nom_sentences), len(vi_sentences))

        for idx in range(max_len):
            nom_item = nom_sentences[idx] if idx < len(nom_sentences) else None
            vi_item = vi_sentences[idx] if idx < len(vi_sentences) else None

            if nom_item and vi_item:
                nom_text = nom_item["text"]
                vi_text = vi_item["text"]
                align_res = self.dp_aligner.align_sentence(nom_text, vi_text)
                
                row = {
                    "img_id": nom_item["img_id"],
                    "sentence_id": nom_item["sentence_id"],
                    "ch_txt": align_res["ch_txt"],
                    "vi_txt": align_res["vi_txt"],
                    "text_diff": align_res["text_diff"]
                }
            elif nom_item and not vi_item:
                row = {
                    "img_id": nom_item["img_id"],
                    "sentence_id": nom_item["sentence_id"],
                    "ch_txt": nom_item["text"],
                    "vi_txt": "",
                    "text_diff": None  # Không có bản dịch để so sánh -> null
                }
            else: # vi_item and not nom_item
                # Trong cấu trúc Rubric, sentence_id căn cứ theo trang Nôm
                # Nếu thừa câu Quốc ngữ cuối sách
                row = {
                    "img_id": "",
                    "sentence_id": "",
                    "ch_txt": "",
                    "vi_txt": vi_item["text"],
                    "text_diff": None
                }

            # Kiểm tra tính hợp lệ của hàng
            if row["sentence_id"]:
                validation_errors = AlignmentExporter.validate_row(row)
                if validation_errors:
                    logger.warning(f"Cảnh báo hàng {row.get('sentence_id')}: {validation_errors}")

            aligned_rows.append(row)

        # Xuất file kết quả
        csv_out = os.path.join(output_dir, f"{book_name}.csv")
        xlsx_out = os.path.join(output_dir, f"{book_name}.xlsx")

        logger.info(f"Đang xuất file CSV: {csv_out}")
        AlignmentExporter.export_csv(aligned_rows, csv_out)

        logger.info(f"Đang xuất file Excel tô màu: {xlsx_out}")
        AlignmentExporter.export_xlsx(aligned_rows, xlsx_out)

        # Đánh giá metrics
        metrics = AlignmentExporter.evaluate_dataset(aligned_rows)
        logger.info(f"Kết quả đánh giá sách '{book_name}':")
        logger.info(f"  - Tổng số hàng: {metrics['total_rows']}")
        logger.info(f"  - Số hàng dịch âm 1-1: {metrics['transliterated_rows']}")
        logger.info(f"  - Số hàng null: {metrics['null_rows']} ({metrics['null_ratio_percent']}%)")
        logger.info(f"  - Tổng số chữ Nôm tính điểm: {metrics['total_scored_nom_chars']}")
        logger.info(f"  - Số chữ không tương đồng (đỏ): {metrics['unmatched_error_chars']}")
        logger.info(f"  - Tỷ lệ chữ vàng (warn): {metrics['yellow_ratio_percent']}%")
        logger.info(f"  - ĐỘ TƯƠNG ĐỒNG: {metrics['similarity_percent']}% (Đạt: {metrics['is_passing']})")

        return {
            "metrics": metrics,
            "csv_path": csv_out,
            "xlsx_path": xlsx_out,
            "aligned_rows_count": len(aligned_rows)
        }

