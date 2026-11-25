import re
import sqlite3
import unicodedata
from functools import lru_cache
from pathlib import Path
from typing import List, Optional

VARIATION_SELECTOR_RE = re.compile(r"[\uFE00-\uFE0F\U000E0100-\U000E01EF]")
_VI_WORD_RE = re.compile(r"[^\W\d_]+")


def _vi_base(c: str) -> str:
    """Ch\u1EEF c\u00E1i g\u1ED1c kh\u00F4ng d\u1EA5u (\u1EC3 -> e, \u0111 -> d) \u0111\u1EC3 nh\u1EADn ra hai nguy\u00EAn \u00E2m Tesseract \u0111\u1ECDc \u0111\u00FAp."""
    return unicodedata.normalize("NFD", c)[0].lower().replace("\u0111", "d")


def _match_case(src: str, dst: str) -> str:
    if src.isupper():
        return dst.upper()
    if src[:1].isupper():
        return dst[:1].upper() + dst[1:]
    return dst


class TextCleaner:
    @staticmethod
    @lru_cache(maxsize=1)
    def valid_vi_syllables(db_path: str = "data/dict.db") -> frozenset:
        """T\u1EADp \u00E2m ti\u1EBFt Qu\u1ED1c ng\u1EEF h\u1EE3p l\u1EC7 = m\u1ECDi \u00E2m \u0111\u1ECDc trong t\u1EEB \u0111i\u1EC3n (r\u1ED7ng n\u1EBFu ch\u01B0a build dict.db)."""
        if not Path(db_path).exists():
            return frozenset()
        with sqlite3.connect(db_path) as conn:
            rows = conn.execute("SELECT DISTINCT reading FROM char_readings").fetchall()
        return frozenset(unicodedata.normalize("NFC", r[0]).lower() for r in rows if r[0])

    @classmethod
    def fix_vi_ocr(cls, text: str) -> str:
        """
        S\u1EEDa l\u1ED7i OCR Qu\u1ED1c ng\u1EEF c\u00F3 t\u00EDnh h\u1EC7 th\u1ED1ng c\u1EE7a Tesseract (d\u1EA5u \u0111\u1ECDc \u0111\u00FAp `t\u1ED9\u00F4i`, `d\u0111\u1EE9c`, `cbo`/`tb\u00EC`).
        Ch\u1EC9 thay m\u1ED9t \u00E2m ti\u1EBFt khi n\u00F3 KH\u00D4NG h\u1EE3p l\u1EC7 v\u00E0 b\u1EA3n s\u1EEDa h\u1EE3p l\u1EC7 theo t\u1EEB \u0111i\u1EC3n, n\u00EAn kh\u00F4ng \u0111\u1EE5ng t\u1EDBi
        t\u1EEB c\u1ED5 / t\u00EAn ri\u00EAng \u0111\u00E3 \u0111\u00FAng. ponytail: heuristic theo lu\u1EADt, c\u1EA7n r\u00E0 so\u00E1t th\u1EE7 c\u00F4ng ph\u1EA7n c\u00F2n l\u1EA1i.
        """
        valid = cls.valid_vi_syllables()
        if not valid or not text:
            return text

        def fix(m: re.Match) -> str:
            w = m.group(0)
            low = unicodedata.normalize("NFC", w).lower()
            if low in valid:
                return w
            cands = [low.replace("d\u0111", "\u0111")]
            for i in range(len(low) - 1):
                if low[i] != low[i + 1] and _vi_base(low[i]) == _vi_base(low[i + 1]) and _vi_base(low[i]) in "aeiouy":
                    cands += [low[:i + 1] + low[i + 2:], low[:i] + low[i + 1:]]
            cands.append(re.sub(r"(?<=[ctkpgn])b", "h", low))
            for c in cands:
                if c != low and c in valid:
                    return _match_case(w, c)
            return w

        return _VI_WORD_RE.sub(fix, unicodedata.normalize("NFC", text))


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

