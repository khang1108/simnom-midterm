import re
import unicodedata
from typing import List, Optional

VARIATION_SELECTOR_RE = re.compile(r"[\uFE00-\uFE0F\U000E0100-\U000E01EF]")


class TextCleaner:
    def __init__(self, book_title_keywords: Optional[List[str]] = None):
        """
        Khởi tạo TextCleaner cho cả văn bản Hán Nôm và Quốc ngữ.
        :param book_title_keywords: Danh sách từ khóa của tiêu đề sách (dùng để lọc header lặp lại).
        """
        self.book_keywords = [unicodedata.normalize("NFC", kw.lower()) for kw in (book_title_keywords or [])]

    @staticmethod
    def strip_variation_selectors(text: str) -> str:
        """Loại bỏ ký tự chọn dạng (U+FE00..U+FE0F và U+E0100..U+E01EF) theo Quy định v2.4."""
        if not text:
            return ""
        return VARIATION_SELECTOR_RE.sub("", text)

    @classmethod
    def normalize_nfc(cls, text: str) -> str:
        """Chuẩn hóa Unicode về dạng NFC và loại bỏ ký tự chọn dạng / điều khiển."""
        if not text:
            return ""
        # Chuẩn hóa NFC và loại bỏ variation selector (chiếm pos nhưng không hiển thị)
        norm = cls.strip_variation_selectors(unicodedata.normalize("NFC", text))
        # Loại bỏ các ký tự điều khiển vô hình (trừ newline và tab)
        norm = re.sub(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]", "", norm)
        return norm

    @staticmethod
    def clean_spaces(text: str) -> str:
        """Chuẩn hóa khoảng trắng."""
        if not text:
            return ""
        # Thay thế nhiều khoảng trắng ngang bằng 1 khoảng trắng
        text = re.sub(r"[ \t\r\f\v]+", " ", text)
        # Bỏ khoảng trắng trước dấu câu
        text = re.sub(r"\s+([.,!?:;\"'。！？；：、，）])", r"\1", text)
        # Bỏ khoảng trắng sau dấu mở ngoặc
        text = re.sub(r"([（(])\s+", r"\1", text)
        return text.strip()

    @staticmethod
    def fix_line_break_hyphens(text: str) -> str:
        """
        Xử lý dấu nối bị bẻ dòng cuối trang/dòng (line-end hyphen) theo Quy định v2.3/v2.4:
        - Nếu cả hai mảnh bắt đầu bằng chữ hoa (tên riêng / viết tắt, vd: 'Sài-\nGòn') -> giữ gạch ngang ('Sài-Gòn').
        - Trường hợp thường (vd: 'tin-\ntưởng') -> bỏ dấu gạch ngang và tách thành hai âm tiết ('tin tưởng').
        """
        if not text:
            return ""

        def _join_broken_syllable(match: re.Match) -> str:
            part1 = match.group(1)
            part2 = match.group(2)
            if part1[:1].isupper() and part2[:1].isupper():
                return f"{part1}-{part2}"
            return f"{part1} {part2}"

        text = re.sub(r"([A-Za-zÀ-ỹ]+)-\s*\n\s*([A-Za-zÀ-ỹ]+)", _join_broken_syllable, text)

        # Bỏ newline dư thừa nhưng giữ đoạn văn
        text = re.sub(r"(?<!\n)\n(?!\n)", " ", text)
        return text

    def is_page_number_or_header(self, line: str) -> bool:
        """
        Kiểm tra xem dòng văn bản có phải là số trang hoặc tiêu đề lặp (running header) không.
        """
        line_clean = line.strip()
        if not line_clean:
            return True

        # Nhận diện số trang: '12', '- 45 -', '( 590 )', 'Trang 12', 'tr. 45'
        if re.fullmatch(r"[-–—\s*(]*\d+[-–—\s*)]*", line_clean):
            return True
        if re.fullmatch(r"(?:trang|tr\.|page)\s*\d+", line_clean, flags=re.IGNORECASE):
            return True

        # Nhận diện header lặp lại theo tiêu đề sách
        line_lower = unicodedata.normalize("NFC", line_clean.lower())
        for kw in self.book_keywords:
            if kw in line_lower and len(line_clean) < len(kw) + 15:
                return True

        return False

    def clean_text_lines(self, lines: List[str]) -> str:
        """
        Làm sạch danh sách các dòng văn bản từ OCR:
        - Bỏ header/footer/số trang
        - Nối dòng và chuẩn hóa Unicode NFC
        """
        valid_lines = []
        for line in lines:
            line_norm = self.normalize_nfc(line)
            if not self.is_page_number_or_header(line_norm):
                valid_lines.append(line_norm.strip())

        joined = "\n".join(valid_lines)
        joined = self.fix_line_break_hyphens(joined)
        return self.clean_spaces(joined)

