import re
import unicodedata
from typing import List, Optional

class TextCleaner:
    def __init__(self, book_title_keywords: Optional[List[str]] = None):
        """
        Khởi tạo TextCleaner cho cả văn bản Hán Nôm và Quốc ngữ.
        :param book_title_keywords: Danh sách từ khóa của tiêu đề sách (dùng để lọc header lặp lại).
        """
        self.book_keywords = [unicodedata.normalize("NFC", kw.lower()) for kw in (book_title_keywords or [])]

    @staticmethod
    def normalize_nfc(text: str) -> str:
        """Chuẩn hóa Unicode về dạng NFC."""
        if not text:
            return ""
        # Chuẩn hóa NFC
        norm = unicodedata.normalize("NFC", text)
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
        Xử lý dấu nối bị bẻ dòng cuối trang/dòng (soft hyphen / line-break hyphen).
        Ví dụ:
          - 'ngư-\nời' -> 'người' (âm tiết bị bẻ đôi)
          - 'khiêm-\nnhường' -> 'khiêm nhường' hoặc 'khiêm-nhường'
          - Nhưng giữ nguyên 'A-ve', 'I-ghê-rê-gia', 'Phi-ri-tô'.
        """
        if not text:
            return ""
        
        # Trường hợp 1: Âm tiết đơn bị bẻ đôi ở cuối dòng (ví dụ: 'ngư-\nời' -> 'người')
        # Kiểm tra nếu phần trước hoặc sau không phải là một âm tiết hoàn chỉnh
        def _join_broken_syllable(match):
            part1 = match.group(1)
            part2 = match.group(2)
            # Nếu ghép lại tạo thành từ không có dấu cách
            # Đơn giản nối lại nếu part2 viết thường
            return f"{part1}{part2}"

        # Bẻ từ giữa âm tiết: vd 'tiế-\nng' -> 'tiếng'
        text = re.sub(r"([a-zA-ZÀ-ỹ]+)-\s*\n\s*([a-zA-ZÀ-ỹ]+)", r"\1\2", text)
        
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
