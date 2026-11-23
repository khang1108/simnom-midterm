import os
import re
import json
import logging
import statistics
import unicodedata
from pathlib import Path
from typing import List, Dict, Any, Optional, Tuple
from src.aligner.dp_align import PhoneticDPAligner
from src.dict_engine.lookup import DictionaryLookup
from src.ocr.ppocr_adapter import PPOCRAdapter
from src.segmenter import (
    TextCleaner,
    PageStitcher,
    RegexSentenceSplitter,
    StatisticalSBDSplitter
)
from src.evaluator.exporter import AlignmentExporter

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger(__name__)

# Khớp số trang / tiêu đề Quốc ngữ dạng "- 48 - (589 )" hoặc "- ĐỒ - (58¿ )" ở mép trên/dưới
_VI_HEADER_PATTERN = re.compile(r"^[-–—]\s*[^-\s]{1,8}\s*[-–—]\s*\([^)]{1,12}\)\s*$")
_VI_NUM_HEADER_PATTERN = re.compile(r"^[-–—\s\d()¿/]+$")


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

        with open(label_path, "r", encoding="utf-8-sig") as f:
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

    @staticmethod
    def is_vi_header_or_footer(text: str, box: Optional[Dict[str, Any]] = None, min_body_y: Optional[float] = None) -> bool:
        """Nhận diện dòng số trang / tiêu đề đầu trang Quốc ngữ cần loại bỏ theo Quy định v2.4."""
        t = TextCleaner.normalize_nfc(text).strip()
        if not t:
            return True
        if _VI_NUM_HEADER_PATTERN.fullmatch(t) or _VI_HEADER_PATTERN.fullmatch(t):
            return True
        if TextCleaner().is_page_number_or_header(t):
            return True
        # Dòng đơn lẻ nằm hẳn trên vùng thân trang và có dạng header đánh số trang ("- ... - (...)")
        if box and min_body_y is not None:
            pts = box.get("points")
            if isinstance(pts, list) and len(pts) >= 4:
                y_max = max(p[1] for p in pts)
                if y_max < min_body_y - 120 and t.startswith("-") and ")" in t:
                    return True
        return False

    @classmethod
    def filter_body_boxes(cls, boxes: List[Dict[str, Any]], script_type: str = "ch") -> List[Dict[str, Any]]:
        """
        Loại bỏ các box rác ngoài khung nội dung chính (số trang, đường viền khung, gáy sách)
        theo Quy định v2.4 mà vẫn bảo toàn các cột/dòng ngắn hợp lệ bên trong khung.
        """
        if not boxes:
            return []

        if script_type == "vi":
            # Ước lượng đỉnh vùng thân trang từ các dòng văn bản thông thường (len >= 15)
            body_ys = []
            for b in boxes:
                txt = TextCleaner.normalize_nfc(str(b.get("transcription", ""))).strip()
                pts = b.get("points")
                if len(txt) >= 15 and isinstance(pts, list) and len(pts) >= 4 and not _VI_HEADER_PATTERN.fullmatch(txt):
                    body_ys.append(min(p[1] for p in pts))
            min_body_y = min(body_ys) if body_ys else None

            kept = []
            for b in boxes:
                txt = str(b.get("transcription", ""))
                if not cls.is_vi_header_or_footer(txt, b, min_body_y=min_body_y):
                    kept.append(b)
            return kept

        # script_type == "ch"
        # Thu thập hình học các cột thân trang tiêu chuẩn (độ dài >= 8 ký tự và có đủ 4 điểm)
        body_cols = []
        for b in boxes:
            txt = "".join(TextCleaner.normalize_nfc(str(b.get("transcription", ""))).split())
            pts = b.get("points")
            if len(txt) >= 8 and isinstance(pts, list) and len(pts) >= 4:
                xs = [p[0] for p in pts]
                ys = [p[1] for p in pts]
                body_cols.append((min(xs), max(xs), min(ys), max(ys), max(xs) - min(xs)))

        # Nếu không có đủ hình học hoặc là dữ liệu ngắn / tổng hợp, giữ nguyên tất cả box không rỗng
        if not body_cols:
            return [b for b in boxes if TextCleaner.normalize_nfc(str(b.get("transcription", ""))).strip()]

        bx_min = min(c[0] for c in body_cols)
        bx_max = max(c[1] for c in body_cols)
        by_min = min(c[2] for c in body_cols)
        by_max = max(c[3] for c in body_cols)
        med_w = statistics.median(c[4] for c in body_cols) or 100.0

        kept = []
        for b in boxes:
            txt = "".join(TextCleaner.normalize_nfc(str(b.get("transcription", ""))).split())
            if not txt:
                continue
            pts = b.get("points")
            if not (isinstance(pts, list) and len(pts) >= 4):
                kept.append(b)
                continue
            xs = [p[0] for p in pts]
            ys = [p[1] for p in pts]
            x1, x2 = min(xs), max(xs)
            y1, y2 = min(ys), max(ys)
            xc = (x1 + x2) * 0.5
            yc = (y1 + y2) * 0.5
            w = max(1.0, float(x2 - x1))
            h = max(1.0, float(y2 - y1))

            # Ngoài biên trái/phải của khung (chữ Nôm đọc phải->trái nên cột kết ngắn có thể nằm ngay bên trái bx_min)
            if xc < bx_min - med_w * 1.45 or xc > bx_max + med_w * 0.8:
                continue
            # Ngoài biên trên/dưới của khung
            if yc < by_min - med_w * 0.5 or yc > by_max + med_w * 0.5:
                continue
            # Đường kẻ khung mảnh bị OCR nhầm thành chữ (chiều rộng < 48% độ rộng cột chuẩn)
            if w < med_w * 0.48:
                continue
            # Ký tự đơn lẻ bị kéo giãn bất thường dọc theo đường viền (tỷ lệ cao/rộng > 3.5)
            if len(txt) == 1 and (h / w) > 3.5:
                continue
            kept.append(b)

        return kept

    def align_and_project_page(self, nom_page: str, vi_sents: List[str]) -> List[Tuple[str, str]]:
        """
        [NLP Method] Dóng hàng quy hoạch động cấp độ trang (Page-level DP Alignment)
        và chiếu ranh giới câu từ Quốc ngữ sang Hán Nôm để tránh hiện tượng trượt lệch (zero drift).
        """
        nom_clean = "".join(c for c in nom_page if not c.isspace())
        nom_tokens = [(m.group(), m.start(), m.end())
                      for m in re.finditer(r"\[MASK\]|.", nom_clean)]

        vi_full = " ".join(vi_sents)
        vi_tokens = []
        for match in re.finditer(r"[^\s.,!?:;\"'()\[\]]+", vi_full):
            syl = match.group()
            vi_tokens.append((syl, match.start(), match.end()))

        n = len(nom_tokens)
        m = len(vi_tokens)
        if n == 0 or m == 0:
            return [(nom_clean, vi_full)] if (nom_clean or vi_full) else []

        # Ma trận quy hoạch động DP
        dp = [[float("inf")] * (m + 1) for _ in range(n + 1)]
        backtrack = [[None] * (m + 1) for _ in range(n + 1)]
        dp[0][0] = 0.0

        for i in range(1, n + 1):
            dp[i][0] = dp[i - 1][0] + 1.0
            backtrack[i][0] = (i - 1, 0)
        for j in range(1, m + 1):
            dp[0][j] = dp[0][j - 1] + 1.0
            backtrack[0][j] = (0, j - 1)

        for i in range(1, n + 1):
            n_char = nom_tokens[i - 1][0]
            for j in range(1, m + 1):
                v_syl = vi_tokens[j - 1][0]
                cost = 0.0 if self.dict_lookup.is_phonetic_match(n_char, v_syl) else 1.0

                # Match / Substitution
                if dp[i - 1][j - 1] + cost < dp[i][j]:
                    dp[i][j] = dp[i - 1][j - 1] + cost
                    backtrack[i][j] = (i - 1, j - 1)
                # Deletion
                if dp[i - 1][j] + 1.0 < dp[i][j]:
                    dp[i][j] = dp[i - 1][j] + 1.0
                    backtrack[i][j] = (i - 1, j)
                # Insertion
                if dp[i][j - 1] + 1.0 < dp[i][j]:
                    dp[i][j] = dp[i][j - 1] + 1.0
                    backtrack[i][j] = (i, j - 1)

        # Traceback tìm ánh xạ từ vi token index sang nom token index
        vi_to_nom = {}
        curr_i, curr_j = n, m
        while curr_i > 0 or curr_j > 0:
            prev = backtrack[curr_i][curr_j]
            if not prev:
                break
            prev_i, prev_j = prev
            if prev_i < curr_i and prev_j < curr_j:
                vi_to_nom[prev_j] = prev_i
            curr_i, curr_j = prev_i, prev_j

        # Phân đoạn câu Nôm tương ứng từng câu Quốc ngữ
        results = []
        curr_vi_tok = 0
        last_nom_end = 0

        for s_idx, vi_s in enumerate(vi_sents):
            s_syls = len(re.findall(r"[^\s.,!?:;\"'()\[\]]+", vi_s))
            s_end_vi_tok = curr_vi_tok + s_syls

            mapped_noms = [vi_to_nom[t] for t in range(curr_vi_tok, min(s_end_vi_tok, m)) if t in vi_to_nom]
            # Các đoạn phải liên tiếp: giữ cả chữ bị DP đánh dấu deletion.
            # Câu cuối nhận phần còn lại kể cả khi không có token được ghép.
            if s_idx == len(vi_sents) - 1:
                n_end = n
            elif mapped_noms:
                n_end = max(last_nom_end, max(mapped_noms) + 1)
            else:
                n_end = last_nom_end
            start_char = nom_tokens[last_nom_end][1] if last_nom_end < n else len(nom_clean)
            end_char = nom_tokens[n_end - 1][2] if n_end else 0
            nom_s = nom_clean[start_char:end_char]
            last_nom_end = n_end

            curr_vi_tok = s_end_vi_tok
            results.append((nom_s, vi_s))

        return results

    @staticmethod
    def _coalesce_pairs(raw_pairs: List[Tuple[str, str, str]]) -> List[Tuple[str, str, str]]:
        """
        Gộp các đoạn chỉ có một vế vào hàng liền kề để đảm bảo không có hàng nào
        bị rỗng ch_txt hoặc vi_txt (tuân thủ Quy định v2.4) mà vẫn giữ nguyên toàn bộ ký tự.
        """
        coalesced: List[List[str]] = []
        pending_nom_img: Optional[str] = None
        pending_nom = ""
        pending_vi = ""

        for ch_img, nom_s, vi_s in raw_pairs:
            nom_clean = nom_s.strip()
            vi_clean = vi_s.strip()
            if not nom_clean and not vi_clean:
                continue

            if nom_clean and vi_clean:
                if pending_nom:
                    ch_img = pending_nom_img or ch_img
                    nom_clean = pending_nom + nom_clean
                    pending_nom = ""
                    pending_nom_img = None
                if pending_vi:
                    vi_clean = f"{pending_vi} {vi_clean}".strip()
                    pending_vi = ""
                coalesced.append([ch_img, nom_clean, vi_clean])
            elif nom_clean and not vi_clean:
                if coalesced:
                    coalesced[-1][1] += nom_clean
                else:
                    if not pending_nom:
                        pending_nom_img = ch_img
                    pending_nom += nom_clean
            else:  # vi_clean and not nom_clean
                if coalesced:
                    coalesced[-1][2] = f"{coalesced[-1][2]} {vi_clean}".strip()
                else:
                    pending_vi = f"{pending_vi} {vi_clean}".strip()

        return [(item[0], item[1], item[2]) for item in coalesced]

    @staticmethod
    def _write_clean_labels(
        clean_dir: Path,
        ch_clean_pages: Dict[str, List[Dict[str, Any]]],
        vi_clean_pages: Dict[str, List[Dict[str, Any]]],
        filter_fn=None,
    ) -> Dict[str, str]:
        """Xuất bản sao sạch Label.txt, Label_char.txt và fileState.txt phục vụ check-diff SYNC."""
        ch_dir = clean_dir / "ch"
        vi_dir = clean_dir / "vi"
        ch_dir.mkdir(parents=True, exist_ok=True)
        vi_dir.mkdir(parents=True, exist_ok=True)

        ch_lines, ch_states, char_lines, char_states = [], [], [], []
        for img_name in sorted(ch_clean_pages.keys()):
            boxes = PPOCRAdapter.sort_boxes_reading_order(ch_clean_pages[img_name], script_type="ch")
            ch_lines.append(
                PPOCRAdapter.format_label_entry("ch", img_name, boxes, script_type="ch", preserve_order=True)
            )
            st = PPOCRAdapter.format_state_entry("ch", img_name)
            ch_states.append(st)

            char_boxes = PPOCRAdapter.split_boxes_to_chars(boxes)
            char_lines.append(
                PPOCRAdapter.format_label_entry("ch", img_name, char_boxes, script_type="ch", preserve_order=True)
            )
            char_states.append(st)

        vi_lines, vi_states = [], []
        for img_name in sorted(vi_clean_pages.keys()):
            boxes = vi_clean_pages[img_name]
            vi_lines.append(
                PPOCRAdapter.format_label_entry("vi", img_name, boxes, script_type="vi", preserve_order=True)
            )
            vi_states.append(PPOCRAdapter.format_state_entry("vi", img_name))

        (ch_dir / "Label.txt").write_text("".join(ch_lines), encoding="utf-8")
        (ch_dir / "fileState.txt").write_text("".join(ch_states), encoding="utf-8")
        (ch_dir / "Label_char.txt").write_text("".join(char_lines), encoding="utf-8")
        (ch_dir / "fileState_char.txt").write_text("".join(char_states), encoding="utf-8")
        (vi_dir / "Label.txt").write_text("".join(vi_lines), encoding="utf-8")
        (vi_dir / "fileState.txt").write_text("".join(vi_states), encoding="utf-8")

        return {
            "ch_label": str(ch_dir / "Label.txt"),
            "ch_char_label": str(ch_dir / "Label_char.txt"),
            "vi_label": str(vi_dir / "Label.txt"),
        }

    def project_book_pairs(
        self,
        book_dir: str,
        book_name: str,
        clean_labels_dir: Optional[str] = None,
    ) -> Dict[str, Any]:
        """
        Đọc Label.txt, lọc box rác ngoài khung, nối câu xuyên trang và chiếu ranh giới câu DP
        để tạo danh sách cặp câu sạch `[{"img_id", "sentence_id", "ch_txt", "vi_txt"}]`.
        """
        ch_label_path = os.path.join(book_dir, "ch", "Label.txt")
        vi_label_path = os.path.join(book_dir, "vi", "Label.txt")
        image_map_path = os.path.join(book_dir, f"{book_name}_image_map.json")

        if not os.path.exists(ch_label_path):
            raise FileNotFoundError(f"Không tìm thấy file {ch_label_path}")
        if not os.path.exists(vi_label_path):
            raise FileNotFoundError(f"Không tìm thấy file {vi_label_path}")

        raw_ch_pages = self.load_label_file(ch_label_path)
        raw_vi_pages = self.load_label_file(vi_label_path)

        ch_pages_data = {
            img: PPOCRAdapter.sort_boxes_reading_order(self.filter_body_boxes(boxes, "ch"), script_type="ch")
            for img, boxes in raw_ch_pages.items()
        }
        vi_pages_data = {
            img: self.filter_body_boxes(boxes, "vi")
            for img, boxes in raw_vi_pages.items()
        }

        clean_paths = {}
        if clean_labels_dir:
            clean_paths = self._write_clean_labels(Path(clean_labels_dir), ch_pages_data, vi_pages_data)

        page_pairs = []
        if os.path.exists(image_map_path):
            try:
                with open(image_map_path, "r", encoding="utf-8") as f:
                    data = json.load(f)
                    page_pairs = data.get("pairs", [])
            except Exception as e:
                logger.warning(f"Không đọc được {image_map_path}: {e}")

        raw_sentence_pairs: List[Tuple[str, str, str]] = []

        if page_pairs:
            logger.info(f"Dóng hàng theo {len(page_pairs)} cặp trang từ {image_map_path}...")
            stitched_pairs = []
            pending: Dict[str, List[str]] = {"ch": [], "vi": []}
            for pair in page_pairs:
                if not pair.get("ch") or not pair.get("vi"):
                    if pending["ch"]:
                        stitched_pairs.append(pending)
                        pending = {"ch": [], "vi": []}
                    stitched_pairs.append(pair)
                    continue
                pending["ch"].extend(pair["ch"])
                pending["vi"].extend(pair["vi"])
                tail = " ".join(
                    PPOCRAdapter.clean_transcription(b.get("transcription", ""))
                    for b in vi_pages_data.get(pair["vi"][-1], [])
                ).rstrip().rstrip('\"\'”»）)」』').rstrip()
                if tail and tail[-1] in PageStitcher.VI_TERMINAL_PUNCT:
                    stitched_pairs.append(pending)
                    pending = {"ch": [], "vi": []}
            if pending["ch"]:
                stitched_pairs.append(pending)

            for pair in stitched_pairs:
                ch_imgs = pair.get("ch", [])
                vi_imgs = pair.get("vi", [])
                if not ch_imgs or not vi_imgs:
                    continue

                ch_parts = []
                ch_spans = []
                ch_offset = 0
                for image in ch_imgs:
                    page_text = TextCleaner.normalize_nfc("".join(
                        PPOCRAdapter.clean_transcription(b.get("transcription", ""))
                        for b in ch_pages_data.get(image, [])
                    ))
                    ch_parts.append(page_text)
                    page_length = sum(not c.isspace() for c in page_text)
                    ch_spans.append((ch_offset, ch_offset + page_length, image))
                    ch_offset += page_length
                ch_text = "".join(ch_parts)

                vi_raw_lines = []
                for image in vi_imgs:
                    for b in vi_pages_data.get(image, []):
                        line_txt = " ".join(PPOCRAdapter.clean_transcription(b.get("transcription", "")).split())
                        if line_txt:
                            vi_raw_lines.append(line_txt)
                vi_text = self.cleaner.clean_spaces(self.cleaner.fix_line_break_hyphens("\n".join(vi_raw_lines)))

                if not ch_text and not vi_text:
                    continue

                vi_sents = self.splitter.split_quoc_ngu(vi_text)
                if self.method == "nlp" and vi_sents:
                    sentence_pairs = self.align_and_project_page(ch_text, vi_sents)
                else:
                    ch_sents = self.splitter.split_han_nom(ch_text)
                    max_s = max(len(ch_sents), len(vi_sents))
                    sentence_pairs = [
                        (ch_sents[i] if i < len(ch_sents) else "", vi_sents[i] if i < len(vi_sents) else "")
                        for i in range(max_s)
                    ]

                nom_offset = 0
                for nom_s, vi_s in sentence_pairs:
                    ch_img = next(
                        (image for start, end, image in ch_spans if start <= nom_offset < end),
                        ch_imgs[-1],
                    )
                    nom_offset += sum(not c.isspace() for c in nom_s)
                    raw_sentence_pairs.append((ch_img, TextCleaner.normalize_nfc(nom_s), TextCleaner.normalize_nfc(vi_s)))
        else:
            ch_images = sorted(ch_pages_data.keys(), reverse=True)
            vi_images = sorted(vi_pages_data.keys())

            ch_page_list = [
                {"img_id": img, "text": "".join(PPOCRAdapter.clean_transcription(b.get("transcription", "")) for b in ch_pages_data[img])}
                for img in ch_images
            ]
            vi_page_list = [
                {"img_id": img, "text": "\n".join(PPOCRAdapter.clean_transcription(b.get("transcription", "")) for b in vi_pages_data[img])}
                for img in vi_images
            ]

            nom_sentences = PageStitcher.stitch_and_split_pages(ch_page_list, script="ch", cleaner=self.cleaner, splitter=self.splitter)
            vi_sentences = PageStitcher.stitch_and_split_pages(vi_page_list, script="vi", cleaner=self.cleaner, splitter=self.splitter)

            max_len = max(len(nom_sentences), len(vi_sentences))
            for idx in range(max_len):
                nom_item = nom_sentences[idx] if idx < len(nom_sentences) else None
                vi_item = vi_sentences[idx] if idx < len(vi_sentences) else None
                ch_img = nom_item["img_id"] if nom_item else (ch_images[0] if ch_images else "")
                nom_s = nom_item["text"] if nom_item else ""
                vi_s = vi_item["text"] if vi_item else ""
                raw_sentence_pairs.append((ch_img, TextCleaner.normalize_nfc(nom_s), TextCleaner.normalize_nfc(vi_s)))

        # Đảm bảo không có hàng nào rỗng một vế trước khi đánh sentence_id
        coalesced = self._coalesce_pairs(raw_sentence_pairs)
        pairs_out = []
        page_sentence_counters: Dict[str, int] = {}
        for ch_img, nom_s, vi_s in coalesced:
            page_sentence_counters[ch_img] = page_sentence_counters.get(ch_img, 0) + 1
            s_i = page_sentence_counters[ch_img]
            base_ch_id = ch_img.replace(".jpg", "").replace(".png", "")
            pairs_out.append({
                "img_id": ch_img,
                "sentence_id": f"{base_ch_id}.{s_i}",
                "ch_txt": nom_s,
                "vi_txt": vi_s,
            })

        return {
            "pairs": pairs_out,
            "clean_paths": clean_paths,
        }

    def align_book(
        self,
        book_dir: str,
        book_name: str,
        output_dir: Optional[str] = None
    ) -> Dict[str, Any]:
        """
        Thực hiện toàn bộ quy trình dóng hàng cho một cuốn sách:
        1. Đọc Label.txt của ch/ và vi/
        2. Ghép cặp trang theo image_map.json (nếu có)
        3. Dóng hàng DP và xuất file .csv (UTF-8 BOM), .xlsx (tô 3 màu chuẩn v2.4)
        4. Đánh giá và trả về metrics
        """
        output_dir = output_dir or book_dir
        projected = self.project_book_pairs(book_dir=book_dir, book_name=book_name)

        aligned_rows = []
        for p in projected["pairs"]:
            res = self.dp_aligner.align_sentence(p["ch_txt"], p["vi_txt"])
            aligned_rows.append({
                "img_id": p["img_id"],
                "sentence_id": p["sentence_id"],
                "ch_txt": res["ch_txt"],
                "vi_txt": res["vi_txt"],
                "text_diff": res["text_diff"],
            })

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
