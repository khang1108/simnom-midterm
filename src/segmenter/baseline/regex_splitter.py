import re
import unicodedata
from typing import List

class RegexSentenceSplitter:
    """
    [BASELINE V0] Bộ tách câu dựa trên luật biểu thức chính quy (Regex Rule-based).
    - Quốc ngữ: Tách dựa trên các ký tự .?!;: kết hợp danh sách từ viết tắt cứng (hardcoded).
    - Hán Nôm: Tách dựa trên các ký tự 。！？；：.
    
    Phương pháp này đóng vai trò mốc cơ sở (baseline) để so sánh thực nghiệm với các 
    mô hình NLP nâng cao (Statistical SBD & Grammar-informed).
    """

    # Danh sách từ viết tắt cứng cơ bản
    BASIC_ABBREVIATIONS = {
        "đ.c.", "st.", "th.", "tr.", "v.v.", "tp.", "ts.", "ths.", "gs.", "bs.", "lm."
    }

    VI_PUNCT_REGEX = re.compile(r"([.?!;:]+[\"'\u201d\u00bb]?)(?:\s+|$)")
    NOM_PUNCT_REGEX = re.compile(r"([。！？；：]+|(?<![\w\u4e00-\u9fff])[.?!;:](?!\w))")

    @classmethod
    def split_quoc_ngu(cls, text: str) -> List[str]:
        """Tách câu Quốc ngữ bằng Regex cơ sở."""
        if not text:
            return []

        text = unicodedata.normalize("NFC", text.strip())
        placeholders = {}

        def _protect(match):
            key = f"__ABBR_{len(placeholders)}__"
            placeholders[key] = match.group(0)
            return key

        # Bảo vệ số thập phân: 1.5, 3.14
        protected_text = re.sub(r"\b\d+\.\d+\b", _protect, text)
        
        # Bảo vệ viết tắt dạng 1 chữ cái kèm dấu chấm: Đ.C., v.v.
        protected_text = re.sub(r"\b(?:[A-Za-zÀ-ỹ]\.){2,}", _protect, protected_text)

        # Bảo vệ các từ viết tắt đơn đứng trước từ viết hoa
        for abbr in ["St.", "Th.", "Tr.", "tr.", "Lm.", "Đ.C."]:
            pattern = re.compile(rf"\b{re.escape(abbr)}(?=\s+[A-ZÀ-Ỹ])")
            protected_text = pattern.sub(_protect, protected_text)

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
        """Tách câu Hán Nôm bằng Regex dấu câu 。！？；：."""
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

        return [s for s in raw_sentences if s] or [text]

