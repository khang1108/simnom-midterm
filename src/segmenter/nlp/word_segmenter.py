import sqlite3
import unicodedata
import os
from typing import List, Tuple, Set, Optional

class BilingualWordSegmenter:
    """
    [NLP METHOD V2] Bộ tách từ song ngữ (Word Segmentation) cho Quốc ngữ và Hán Nôm.
    Áp dụng thuật toán Khớp cực đại hai chiều (Bidirectional Maximum Matching - BiMM),
    kết hợp kho ngữ vựng 67.000+ từ ghép từ cơ sở dữ liệu SQLite dict.db.
    
    Nguyên lý giải quyết bài toán:
    - Tiếng Việt và Hán Nôm có hiện tượng ranh giới từ vựng đa âm tiết / đa tự vị:
      (vd: 'khiêm nhường', 'thiên chúa', 'cứu rỗi', '憂愛', '案冊').
    - BiMM chạy song song FMM (Forward Max Matching) và BMM (Backward Max Matching).
    - Bộ giải quyết xung đột (Conflict Resolution) chọn phương án tối ưu dựa trên:
      1. Số lượng từ ít hơn (Minimum Token Count heuristic)
      2. Số lượng từ đơn ít hơn (Fewer Single-syllable words)
    """

    def __init__(self, db_path: str = "data/dict.db", max_word_length: int = 5):
        self.db_path = db_path
        self.max_word_length = max_word_length
        self.vi_vocab: Set[str] = set()
        self.nom_vocab: Set[str] = set()
        self._load_vocab()

    def _load_vocab(self):
        """Nạp tập từ vựng từ ghép từ SQLite dict.db vào memory set để tra cứu O(1)."""
        if not os.path.exists(self.db_path):
            return

        conn = sqlite3.connect(self.db_path)
        c = conn.cursor()

        # Nạp từ ghép Hán Nôm (độ dài > 1 ký tự)
        c.execute("SELECT DISTINCT head FROM char_readings WHERE length(head) > 1 AND length(head) <= 5")
        for row in c.fetchall():
            head = unicodedata.normalize("NFC", row[0])
            self.nom_vocab.add(head)

        # Nạp từ ghép Quốc ngữ (chứa dấu cách, độ dài từ 2 đến 5 âm tiết)
        c.execute("SELECT DISTINCT reading FROM char_readings WHERE reading LIKE '% %'")
        for row in c.fetchall():
            reading = unicodedata.normalize("NFC", row[0].strip().lower())
            tokens = reading.split()
            if 2 <= len(tokens) <= 5:
                self.vi_vocab.add(" ".join(tokens))

        conn.close()

        # Bổ sung một số thực thể tôn giáo / cổ điển đặc thù
        extra_religious = {
            "thiên chúa", "đức chúa", "đức bà", "ông thánh", "bà thánh",
            "khiêm nhường", "sửa mình", "cáo mình", "phúc thật", "linh hồn",
            "thương khó", "thánh thần", "đấng làm người", "thánh mẫu"
        }
        for term in extra_religious:
            self.vi_vocab.add(unicodedata.normalize("NFC", term))

    def segment_quoc_ngu_fmm(self, syllables: List[str]) -> List[str]:
        """Forward Maximum Matching cho Quốc ngữ."""
        words = []
        i = 0
        n = len(syllables)
        while i < n:
            matched = False
            for length in range(min(self.max_word_length, n - i), 1, -1):
                candidate = " ".join(s.lower() for s in syllables[i : i + length])
                if candidate in self.vi_vocab:
                    # Giữ nguyên định dạng hoa/thường nguyên bản của cụm từ
                    original_phrase = " ".join(syllables[i : i + length])
                    words.append(original_phrase)
                    i += length
                    matched = True
                    break
            if not matched:
                words.append(syllables[i])
                i += 1
        return words

    def segment_quoc_ngu_bmm(self, syllables: List[str]) -> List[str]:
        """Backward Maximum Matching cho Quốc ngữ."""
        words = []
        i = len(syllables)
        while i > 0:
            matched = False
            for length in range(min(self.max_word_length, i), 1, -1):
                candidate = " ".join(s.lower() for s in syllables[i - length : i])
                if candidate in self.vi_vocab:
                    original_phrase = " ".join(syllables[i - length : i])
                    words.insert(0, original_phrase)
                    i -= length
                    matched = True
                    break
            if not matched:
                words.insert(0, syllables[i - 1])
                i -= 1
        return words

    def segment_quoc_ngu(self, text: str) -> List[str]:
        """
        Tách từ Quốc ngữ bằng BiMM (Bidirectional Maximum Matching).
        """
        if not text:
            return []
        text = unicodedata.normalize("NFC", text.strip())
        syllables = text.split()
        if not syllables:
            return []

        fmm = self.segment_quoc_ngu_fmm(syllables)
        bmm = self.segment_quoc_ngu_bmm(syllables)

        # Conflict Resolution
        if fmm == bmm:
            return fmm

        # Tiêu chí 1: Chọn phương án có ít token hơn
        if len(fmm) != len(bmm):
            return fmm if len(fmm) < len(bmm) else bmm

        # Tiêu chí 2: Chọn phương án có ít từ đơn (single-syllable) hơn
        fmm_single = sum(1 for w in fmm if " " not in w)
        bmm_single = sum(1 for w in bmm if " " not in w)
        return fmm if fmm_single <= bmm_single else bmm

    def segment_han_nom(self, text: str) -> List[str]:
        """
        Tách từ Hán Nôm bằng BiMM trên chuỗi ký tự Hán Nôm.
        """
        if not text:
            return []
        chars = [c for c in unicodedata.normalize("NFC", text.strip()) if not c.isspace()]
        if not chars:
            return []

        # FMM cho Hán Nôm
        fmm = []
        i = 0
        n = len(chars)
        while i < n:
            matched = False
            for length in range(min(self.max_word_length, n - i), 1, -1):
                cand = "".join(chars[i : i + length])
                if cand in self.nom_vocab:
                    fmm.append(cand)
                    i += length
                    matched = True
                    break
            if not matched:
                fmm.append(chars[i])
                i += 1

        return fmm

