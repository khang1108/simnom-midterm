import re
import unicodedata
from typing import List, Set, Tuple

class StatisticalSBDSplitter:
    """
    [NLP METHOD V1] Bộ phân đoạn ranh giới câu (Sentence Boundary Disambiguation - SBD).
    Áp dụng các kỹ thuật NLP thống kê và ngôn ngữ học cấu trúc:
    
    1. Quốc ngữ: 
       - Kỹ thuật Punkt-style (Kiss & Strunk): Phân biệt dấu chấm kết thúc câu với 
         dấu chấm viết tắt / trích dẫn dựa trên xác suất tiền ngữ cảnh, mẫu viết hoa 
         kế tiếp (capitalization pattern) và trích dẫn kinh thánh / chương mục.
       - Xử lý các thực thể tôn giáo đặc thù: 'Đ.C.', 'Lm.', 'St.', 'Th.', 'tr.', 'Mt 5, 3.'
    
    2. Hán Nôm:
       - Grammar-informed Sentence Segmentation: Nhận diện ranh giới câu trong cổ văn 
         không dấu (vô tiêu điểm) dựa trên tập Hư từ ngữ khí cuối câu (Sentence-Final Particles):
         {也, 矣, 乎, 哉, 焉, 耳, 歟, 邪, 兮} kết hợp dấu câu nguyên bản 。！？；：.
    """

    # Hư từ ngữ khí kết thúc câu kinh điển trong Hán Nôm và Cổ văn
    NOM_FINAL_PARTICLES = set("也矣乎哉焉耳歟邪兮")
    NOM_EXPLICIT_PUNCT = set("。！？；：")

    # Danh sách các từ viết tắt tôn giáo, học vị, quy ước sách báo
    COMMON_ECCLESIASTICAL_ABBRS = {
        "đ.c.", "đc.", "lm.", "st.", "th.", "tr.", "s.", "đ.", "tp.", "v.v.",
        "p.", "j.", "m.", "b.", "fr.", "sr.", "gs.", "ts.", "ths.", "bs.", "tk."
    }

    # Tên các sách kinh thánh viết tắt trong trích dẫn Công giáo: vd: 'Mt.', 'Lc.', 'Ga.', 'Mc.', 'Tv.'
    BIBLE_BOOK_ABBRS = {
        "mt", "mc", "lc", "ga", "cv", "rm", "cr", "gl", "ep", "pl", "cl",
        "ts", "tm", "tt", "pm", "dt", "gc", "pr", "gn", "jd", "kh", "st",
        "xh", "lv", "ds", "nl", "gs", "tp", "rt", "sm", "v", "sk", "ed",
        "nh", "tb", "gt", "et", "mb", "gb", "tv", "cn", "gl", "dc", "kn",
        "hc", "is", "gr", "tc", "br", "ez", "dn", "hs", "ge", "am", "ob",
        "gn", "mi", "nh", "hk", "xp", "hg", "zc", "ml"
    }

    @classmethod
    def is_abbreviation_or_citation(cls, prev_token: str, next_token: str) -> bool:
        """
        [NLP Feature] Đánh giá xem dấu chấm sau prev_token có phải là từ viết tắt 
        hoặc trích dẫn hay không, dựa trên cấu trúc hình thái và ngữ cảnh.
        """
        prev_clean = prev_token.lower().rstrip(".,;:!?\"')")
        
        # 1. Viết tắt đa chấm (ví dụ: 'v.v.', 'đ.c.', 's.j.')
        if re.fullmatch(r"(?:[a-zà-ỹ]\.){1,}[a-zà-ỹ]?", prev_clean):
            return True

        # 2. Thuộc từ điển viết tắt thông dụng
        if prev_clean in cls.COMMON_ECCLESIASTICAL_ABBRS or f"{prev_clean}." in cls.COMMON_ECCLESIASTICAL_ABBRS:
            return True

        # 3. Trích dẫn kinh thánh dạng 'Ga 3, 16.' hoặc 'Mt 5.'
        if prev_clean in cls.BIBLE_BOOK_ABBRS and next_token and re.match(r"^\d+", next_token):
            return True

        # 4. Số La Mã hoặc số thứ tự: 'Chương IV.', 'Thế kỷ XIX.', 'Phần I.'
        if re.fullmatch(r"[ivxldcm]+", prev_clean) and not (next_token and next_token[0].isupper()):
            return True

        # 5. Viết tắt một chữ cái đứng trước danh từ riêng viết hoa (vd: 'P. Gendreau')
        if len(prev_clean) == 1 and next_token and next_token[0].isupper():
            return True

        return False

    @classmethod
    def split_quoc_ngu(cls, text: str) -> List[str]:
        """
        Tách câu Quốc ngữ bằng phương pháp SBD thống kê kết hợp luật ngữ cảnh.
        """
        if not text:
            return []

        text = unicodedata.normalize("NFC", text.strip())
        tokens = text.split()
        if not tokens:
            return []

        sentences: List[str] = []
        current_sentence_tokens: List[str] = []

        for idx, token in enumerate(tokens):
            current_sentence_tokens.append(token)
            next_token = tokens[idx + 1] if idx + 1 < len(tokens) else ""

            # Kiểm tra xem token có chứa dấu ngắt câu cuối không
            match = re.search(r"([.?!;:։]+[\"'\u201d\u00bb]?)$", token)
            if match:
                punct = match.group(1)
                
                # Nếu dấu ngắt là ! hoặc ? -> xác suất rất cao là hết câu
                if any(c in punct for c in "!?"):
                    sentences.append(" ".join(current_sentence_tokens))
                    current_sentence_tokens = []
                    continue

                # Nếu là dấu chấm (.) hoặc hai chấm / chấm phẩy (: ;)
                if "." in punct:
                    # Kiểm tra xem có phải từ viết tắt hoặc trích dẫn không
                    if cls.is_abbreviation_or_citation(token, next_token):
                        continue # Chưa hết câu, tiếp tục gom token
                    
                    # Kiểm tra từ tiếp theo: nếu có từ tiếp theo mà viết thường -> thường không phải câu mới
                    if next_token and next_token[0].islower():
                        continue

                # Thỏa mãn ranh giới câu hợp lệ
                sentences.append(" ".join(current_sentence_tokens))
                current_sentence_tokens = []

        if current_sentence_tokens:
            sentences.append(" ".join(current_sentence_tokens))

        return [s.strip() for s in sentences if s.strip()]

    @classmethod
    def split_han_nom(cls, text: str) -> List[str]:
        """
        Tách câu Hán Nôm bằng phương pháp Grammar-informed:
        - Nhận diện dấu câu hiển ngôn 。！？；：
        - Nhận diện Hư từ kết thúc câu cổ văn {也, 矣, 乎, 哉, 焉, 耳, 歟, 邪, 兮} 
          khi văn bản thiếu tiêu điểm.
        """
        if not text:
            return []

        text = unicodedata.normalize("NFC", text.strip())
        sentences: List[str] = []
        curr_chars: List[str] = []

        idx = 0
        n = len(text)
        while idx < n:
            char = text[idx]
            curr_chars.append(char)

            # Trường hợp 1: Gặp dấu câu hiển ngôn
            if char in cls.NOM_EXPLICIT_PUNCT:
                # Gom luôn các dấu đóng ngoặc hoặc nháy nếu có liền sau
                while idx + 1 < n and text[idx + 1] in "」』）)\"' \t":
                    idx += 1
                    curr_chars.append(text[idx])
                sentences.append("".join(curr_chars).strip())
                curr_chars = []

            # Trường hợp 2: Gặp Hư từ ngữ khí cuối câu trong cổ văn (nếu câu đã đủ độ dài tối thiểu >= 4 chữ)
            elif char in cls.NOM_FINAL_PARTICLES and len(curr_chars) >= 4:
                # Kiểm tra ký tự kế tiếp: nếu ký tự kế tiếp là khoảng trắng hoặc dấu xuống dòng hoặc ký tự bắt đầu câu mới
                next_char = text[idx + 1] if idx + 1 < n else ""
                if next_char in " \t\n\r" or next_char in cls.NOM_EXPLICIT_PUNCT:
                    # Nếu có dấu câu liền sau thì để nhánh trên xử lý
                    pass
                else:
                    # Ranh giới câu tiềm năng theo ngữ pháp cổ văn
                    sentences.append("".join(curr_chars).strip())
                    curr_chars = []

            idx += 1

        if curr_chars:
            remainder = "".join(curr_chars).strip()
            if remainder:
                sentences.append(remainder)

        return [s for s in sentences if s] or [text]
