import re
import unicodedata
from typing import List

class SentenceSplitter:
    # Các từ viết tắt thông dụng trong tiếng Việt và tài liệu tôn giáo/cổ
    COMMON_ABBREVIATIONS = {
        "đ.c.", "st.", "th.", "tr.", "v.v.", "tp.", "ts.", "ths.", "gs.", "bs.", "lm.",
        "ông", "bà", "cha", "đức", "thánh", "s.", "đ.", "c.", "p."
    }

    # Dấu ngắt câu tiếng Việt
    VI_PUNCT_REGEX = re.compile(r"([.?!;:]+[\"'\u201d\u00bb]?)(?:\s+|$)")

    # Dấu ngắt câu Hán Nôm
    NOM_PUNCT_REGEX = re.compile(r"([。！？；：]+|(?<![\w\u4e00-\u9fff])[.?!;:](?!\w))")

    @classmethod
    def split_quoc_ngu(cls, text: str) -> List[str]:
        """
        Tách câu cho văn bản Quốc ngữ, xử lý ngoại lệ chữ viết tắt và số thứ tự.
        """
        if not text:
            return []

        text = unicodedata.normalize("NFC", text.strip())
        
        # Tạm thời bảo vệ các chữ viết tắt phổ biến
        # Ví dụ: 'v.v.' -> 'v__v__'
        placeholders = {}
        def _protect(match):
            key = f"__ABBR_{len(placeholders)}__"
            placeholders[key] = match.group(0)
            return key

        # Bảo vệ số thập phân (ví dụ: 1.5, 3.14)
        protected_text = re.sub(r"\b\d+\.\d+\b", _protect, text)
        
        # Bảo vệ viết tắt dạng 1 chữ cái kèm dấu chấm lặp lại: Đ.C., S.J., v.v.
        protected_text = re.sub(r"\b(?:[A-Za-zÀ-ỹ]\.){2,}", _protect, protected_text)

        # Bảo vệ các từ viết tắt đơn: St., Th., tr. khi đứng trước từ viết hoa
        for abbr in ["St.", "Th.", "Tr.", "tr.", "Lm.", "Đ.C."]:
            pattern = re.compile(rf"\b{re.escape(abbr)}(?=\s+[A-ZÀ-Ỹ])")
            protected_text = pattern.sub(_protect, protected_text)

        # Tách câu theo dấu ngắt
        raw_sentences = []
        last_end = 0
        for match in cls.VI_PUNCT_REGEX.finditer(protected_text):
            end = match.end()
            sentence = protected_text[last_end:end].strip()
            if sentence:
                raw_sentences.append(sentence)
            last_end = end
        
        remainder = protected_text[last_end:].strip()
        if remainder:
            raw_sentences.append(remainder)

        # Phục hồi placeholder
        final_sentences = []
        for s in raw_sentences:
            for key, orig in placeholders.items():
                s = s.replace(key, orig)
            s = s.strip()
            if s:
                final_sentences.append(s)

        return final_sentences if final_sentences else [text]

    @classmethod
    def split_han_nom(cls, text: str) -> List[str]:
        """
        Tách câu cho văn bản Hán Nôm theo dấu câu 。！？；：
        """
        if not text:
            return []

        text = unicodedata.normalize("NFC", text.strip())
        raw_sentences = []
        last_end = 0

        for match in cls.NOM_PUNCT_REGEX.finditer(text):
            end = match.end()
            sentence = text[last_end:end].strip()
            if sentence:
                raw_sentences.append(sentence)
            last_end = end

        remainder = text[last_end:].strip()
        if remainder:
            raw_sentences.append(remainder)

        return final if (final := [s for s in raw_sentences if s]) else [text]
