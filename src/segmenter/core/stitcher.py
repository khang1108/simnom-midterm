import unicodedata
from typing import List, Dict, Any, Optional
from src.segmenter.core.cleaner import TextCleaner
from src.segmenter.baseline.regex_splitter import RegexSentenceSplitter

class PageStitcher:
    """
    Module ghép câu/từ bị ngắt do chuyển trang theo đúng quy tắc Rubric v2.1:
    - Nối các phần tử bị đứt đoạn giữa các trang liền kề theo thứ tự đọc trước khi tách câu.
    - Câu được ghép lấy img_id của hình ảnh chứa phần đầu câu.
    - sentence_id được đánh số thứ tự từ 1 trên hình ảnh đó (<img_id_without_ext>.<index>).
    """

    NOM_TERMINAL_PUNCT = set("。！？；：也矣乎哉焉耳歟邪")
    VI_TERMINAL_PUNCT = set(".?!;:")

    @classmethod
    def stitch_and_split_pages(
        cls, 
        pages: List[Dict[str, Any]], 
        script: str = "ch",
        cleaner: Optional[TextCleaner] = None,
        splitter: Any = None
    ) -> List[Dict[str, Any]]:
        """
        :param pages: Danh sách các trang đã sắp xếp theo ĐÚNG THỨ TỰ ĐỌC.
                      Mỗi phần tử: {"img_id": str, "text": str}
        :param script: 'ch' (Hán Nôm) hoặc 'vi' (Quốc ngữ)
        :param cleaner: Thể hiện TextCleaner để làm sạch văn bản
        :param splitter: Module/Lớp tách câu (Mặc định dùng RegexSentenceSplitter)
        :return: Danh sách các câu đã ghép và gán sentence_id theo định dạng:
                 [{"img_id": str, "sentence_id": str, "text": str}]
        """
        if not pages:
            return []

        cleaner = cleaner or TextCleaner()
        splitter = splitter or RegexSentenceSplitter
        terminal_punct = cls.NOM_TERMINAL_PUNCT if script == "ch" else cls.VI_TERMINAL_PUNCT

        stitched_sentences: List[Dict[str, Any]] = []
        dangling_prefix = ""
        dangling_img_id = ""

        for page in pages:
            img_id = page["img_id"]
            raw_text = page.get("text", "")
            cleaned_text = cleaner.normalize_nfc(raw_text).strip()

            if not cleaned_text:
                continue

            # Nếu trang trước có câu dở dang
            if dangling_prefix:
                cleaned_text = dangling_prefix + " " + cleaned_text
                cleaned_text = cleaner.fix_line_break_hyphens(cleaned_text)
                cleaned_text = cleaner.clean_spaces(cleaned_text)
                current_head_img_id = dangling_img_id
                dangling_prefix = ""
                dangling_img_id = ""
            else:
                current_head_img_id = img_id

            # Tách các câu trong trang này bằng splitter được cung cấp
            if script == "ch":
                sentences = splitter.split_han_nom(cleaned_text)
            else:
                sentences = splitter.split_quoc_ngu(cleaned_text)

            if not sentences:
                continue

            # Kiểm tra xem câu cuối cùng có kết thúc trọn vẹn bằng dấu kết thúc không
            last_sentence = sentences[-1].strip()
            ends_with_terminal = last_sentence and last_sentence[-1] in terminal_punct

            if not ends_with_terminal:
                # Câu cuối chưa kết thúc, lưu lại để ghép với trang kế tiếp
                dangling_prefix = last_sentence
                dangling_img_id = current_head_img_id if len(sentences) == 1 else img_id
                sentences_to_add = sentences[:-1]
            else:
                sentences_to_add = sentences

            # Thêm các câu hoàn chỉnh
            for idx, s in enumerate(sentences_to_add):
                assigned_img_id = current_head_img_id if idx == 0 else img_id
                stitched_sentences.append({
                    "img_id": assigned_img_id,
                    "text": s.strip()
                })

        # Nếu trang cuối cùng còn dangling_prefix
        if dangling_prefix:
            stitched_sentences.append({
                "img_id": dangling_img_id,
                "text": dangling_prefix.strip()
            })

        # Đánh số sentence_id theo chuẩn <img_id_without_ext>.<index>
        page_sentence_counters: Dict[str, int] = {}
        result: List[Dict[str, Any]] = []

        for item in stitched_sentences:
            target_img_id = item["img_id"]
            page_sentence_counters[target_img_id] = page_sentence_counters.get(target_img_id, 0) + 1
            idx = page_sentence_counters[target_img_id]
            base_id = target_img_id.replace(".jpg", "").replace(".png", "")
            
            result.append({
                "img_id": target_img_id,
                "sentence_id": f"{base_id}.{idx}",
                "text": item["text"]
            })

        return result

