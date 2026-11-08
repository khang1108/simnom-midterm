import json
import re
import unicodedata
from typing import List, Dict, Any, Tuple, Optional
from src.dict_engine.lookup import DictionaryLookup

# Dấu câu Hán Nôm và Quốc ngữ
PUNCT_CHARS = set("。，、！？：；「」『』（）()[].,!?:;\"' \t\n\r")

class PhoneticDPAligner:
    def __init__(self, dict_lookup: Optional[DictionaryLookup] = None):
        self.dic = dict_lookup or DictionaryLookup()

    def normalize(self, text: str) -> str:
        return unicodedata.normalize("NFC", text) if text else ""

    def align_sentence(self, nom_sentence: str, vi_sentence: str) -> Dict[str, Any]:
        """
        Dóng hàng một cặp câu Nôm - Quốc ngữ (dịch âm 1-1).
        Trả về kết quả dóng hàng và cấu trúc text_diff theo chuẩn Rubric v2.1.
        """
        nom_norm = self.normalize(nom_sentence)
        vi_norm = self.normalize(vi_sentence)

        # Trích xuất các ký tự Nôm và vị trí Unicode của chúng trong chuỗi nom_norm
        nom_tokens = [] # list of (char, start_idx, end_idx)
        for idx, char in enumerate(nom_norm):
            if char not in PUNCT_CHARS:
                nom_tokens.append((char, idx, idx + 1))

        # Trích xuất các âm tiết Quốc ngữ và vị trí Unicode trong chuỗi vi_norm
        vi_tokens = [] # list of (syllable, start_idx, end_idx)
        # Tách theo từ/âm tiết
        for match in re.finditer(r"[^\s.,!?:;\"'()\[\]]+", vi_norm):
            syllable = match.group()
            # Bỏ qua nếu toàn dấu câu
            if not all(c in PUNCT_CHARS for c in syllable):
                vi_tokens.append((syllable, match.start(), match.end()))

        # Nếu là bản dịch âm chuẩn 1-1 và độ dài bằng nhau: so sánh từng cặp
        text_diff = []
        unmatched_nom_chars = 0
        total_scored_nom_chars = len(nom_tokens)

        # Trường hợp 1: Số lượng ký tự Nôm bằng số lượng âm tiết Quốc ngữ
        if len(nom_tokens) == len(vi_tokens):
            for (n_char, n_start, n_end), (v_syl, v_start, v_end) in zip(nom_tokens, vi_tokens):
                is_match = self.dic.is_phonetic_match(n_char, v_syl)
                if not is_match:
                    unmatched_nom_chars += 1
                    text_diff.append({
                        "nom_pos": [[n_start, n_end]],
                        "nom_sub_text": nom_norm[n_start:n_end],
                        "vi_pos": [[v_start, v_end]],
                        "vi_sub_text": vi_norm[v_start:v_end],
                        "type": "error"
                    })
        else:
            # Trường hợp 2: Số lượng khác nhau (ví dụ tên riêng n-to-m như Philiphê <-> 丕離批, hoặc số 1571)
            # Dùng Needleman-Wunsch / Dynamic Programming
            diff_entries, unmatch_count = self._align_dp(nom_norm, nom_tokens, vi_norm, vi_tokens)
            text_diff.extend(diff_entries)
            unmatched_nom_chars += unmatch_count

        # Tính độ tương đồng (%)
        # Mẫu số: Tổng số chữ Nôm trừ đi các chữ vàng (nếu có)
        yellow_chars = sum(len(e["nom_pos"]) for e in text_diff if e.get("type") == "warn")
        denominator = max(1, total_scored_nom_chars - yellow_chars)
        similarity = max(0.0, (1.0 - (unmatched_nom_chars / denominator)) * 100.0)

        return {
            "ch_txt": nom_norm,
            "vi_txt": vi_norm,
            "text_diff": text_diff,
            "similarity": similarity,
            "total_nom_chars": total_scored_nom_chars,
            "unmatched_chars": unmatched_nom_chars
        }

    def _align_dp(self, nom_str: str, nom_tokens: List[Tuple[str, int, int]],
                  vi_str: str, vi_tokens: List[Tuple[str, int, int]]) -> Tuple[List[Dict[str, Any]], int]:
        """
        Dóng hàng DP khi số lượng ký tự Nôm và âm tiết Quốc ngữ không khớp nhau 1-1.
        """
        n = len(nom_tokens)
        m = len(vi_tokens)
        dp = [[float('inf')] * (m + 1) for _ in range(n + 1)]
        backtrack = [[None] * (m + 1) for _ in range(n + 1)]

        dp[0][0] = 0.0
        for i in range(1, n + 1):
            dp[i][0] = dp[i - 1][0] + 1.0 # Xóa Nôm
            backtrack[i][0] = (i - 1, 0, "del")
        for j in range(1, m + 1):
            dp[0][j] = dp[0][j - 1] + 1.0 # Thêm Quốc ngữ
            backtrack[0][j] = (0, j - 1, "ins")

        for i in range(1, n + 1):
            n_char = nom_tokens[i - 1][0]
            for j in range(1, m + 1):
                v_syl = vi_tokens[j - 1][0]
                cost = 0.0 if self.dic.is_phonetic_match(n_char, v_syl) else 1.0
                
                # Match / Substitution
                if dp[i - 1][j - 1] + cost < dp[i][j]:
                    dp[i][j] = dp[i - 1][j - 1] + cost
                    backtrack[i][j] = (i - 1, j - 1, "match" if cost == 0.0 else "sub")

                # Deletion
                if dp[i - 1][j] + 1.0 < dp[i][j]:
                    dp[i][j] = dp[i - 1][j] + 1.0
                    backtrack[i][j] = (i - 1, j, "del")

                # Insertion
                if dp[i][j - 1] + 1.0 < dp[i][j]:
                    dp[i][j] = dp[i][j - 1] + 1.0
                    backtrack[i][j] = (i, j - 1, "ins")

        # Traceback
        curr_i, curr_j = n, m
        diff_entries = []
        unmatched_count = 0

        while curr_i > 0 or curr_j > 0:
            step = backtrack[curr_i][curr_j]
            if not step:
                break
            prev_i, prev_j, op = step
            if op == "sub":
                n_char, n_start, n_end = nom_tokens[curr_i - 1]
                v_syl, v_start, v_end = vi_tokens[curr_j - 1]
                unmatched_count += 1
                diff_entries.append({
                    "nom_pos": [[n_start, n_end]],
                    "nom_sub_text": nom_str[n_start:n_end],
                    "vi_pos": [[v_start, v_end]],
                    "vi_sub_text": vi_str[v_start:v_end],
                    "type": "error"
                })
            elif op == "del":
                n_char, n_start, n_end = nom_tokens[curr_i - 1]
                unmatched_count += 1
                diff_entries.append({
                    "nom_pos": [[n_start, n_end]],
                    "nom_sub_text": nom_str[n_start:n_end],
                    "vi_pos": [],
                    "vi_sub_text": "",
                    "type": "error"
                })
            elif op == "ins":
                v_syl, v_start, v_end = vi_tokens[curr_j - 1]
                diff_entries.append({
                    "nom_pos": [],
                    "nom_sub_text": "",
                    "vi_pos": [[v_start, v_end]],
                    "vi_sub_text": vi_str[v_start:v_end],
                    "type": "error"
                })
            curr_i, curr_j = prev_i, prev_j

        diff_entries.reverse()
        return diff_entries, unmatched_count

if __name__ == "__main__":
    aligner = PhoneticDPAligner()
    # Test example from rubric
    nom = "経申母福。"
    vi = "Kinh Thân Mẫu Phúc."
    res = aligner.align_sentence(nom, vi)
    print("Test 1 (Khớp 100%):")
    print("  text_diff:", res["text_diff"])
    print("  similarity:", f"{res['similarity']:.2f}%")

    nom2 = "経申母福。"
    vi2 = "Kinh Thân Cha Phúc."
    res2 = aligner.align_sentence(nom2, vi2)
    print("Test 2 (Lỗi 母 <-> Cha):")
    print("  text_diff:", json.dumps(res2["text_diff"], ensure_ascii=False))
    print("  similarity:", f"{res2['similarity']:.2f}%")

