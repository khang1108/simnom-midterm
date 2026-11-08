import sqlite3
import unicodedata
from pathlib import Path
from typing import Set, List, Optional

DB_PATH = Path("data/dict.db")

class DictionaryLookup:
    def __init__(self, db_path: Path = DB_PATH):
        if not db_path.exists():
            raise FileNotFoundError(f"Database not found at {db_path}. Please run index_dict.py first.")
        self.conn = sqlite3.connect(f"file:{db_path}?mode=ro", uri=True)
        self._cache_readings = {}
        self._cache_variants = {}

    def normalize(self, text: str) -> str:
        if not text:
            return ""
        return unicodedata.normalize("NFC", text.strip())

    def get_readings(self, char: str, vi_only: bool = True) -> Set[str]:
        """Lấy tất cả các âm đọc Quốc ngữ khả dĩ của một chữ Hán Nôm."""
        char = self.normalize(char)
        if not char:
            return set()
        cache_key = f"{char}:{vi_only}"
        if cache_key in self._cache_readings:
            return self._cache_readings[cache_key]
        
        cur = self.conn.cursor()
        if vi_only:
            cur.execute("SELECT DISTINCT reading FROM char_readings WHERE head = ? AND system IN ('qn', 'hv', 'nom')", (char,))
        else:
            cur.execute("SELECT DISTINCT reading FROM char_readings WHERE head = ?", (char,))
            
        readings = {row[0].lower() for row in cur.fetchall()}
        
        # Nếu chưa thấy, thử tra qua dị thể
        if not readings:
            variants = self.get_variants(char)
            for var in variants:
                if vi_only:
                    cur.execute("SELECT DISTINCT reading FROM char_readings WHERE head = ? AND system IN ('qn', 'hv', 'nom')", (var,))
                else:
                    cur.execute("SELECT DISTINCT reading FROM char_readings WHERE head = ?", (var,))
                for row in cur.fetchall():
                    readings.add(row[0].lower())
                    
        self._cache_readings[cache_key] = readings
        return readings

    def get_variants(self, char: str) -> Set[str]:
        """Lấy danh sách các chữ dị thể (variants) của chữ Hán Nôm."""
        char = self.normalize(char)
        if not char:
            return set()
        if char in self._cache_variants:
            return self._cache_variants[char]
            
        cur = self.conn.cursor()
        cur.execute("SELECT DISTINCT variant FROM variants WHERE head = ?", (char,))
        vars_1 = {row[0] for row in cur.fetchall()}
        cur.execute("SELECT DISTINCT head FROM variants WHERE variant = ?", (char,))
        vars_2 = {row[0] for row in cur.fetchall()}
        
        all_vars = (vars_1 | vars_2) - {char}
        self._cache_variants[char] = all_vars
        return all_vars

    def is_phonetic_match(self, char: str, syllable: str) -> bool:
        """Kiểm tra xem âm tiết Quốc ngữ có phải là âm đọc hợp lệ của chữ Nôm không."""
        syllable = self.normalize(syllable).lower()
        readings = self.get_readings(char)
        return syllable in readings

# Test run if executed directly
if __name__ == "__main__":
    dic = DictionaryLookup()
    sample_chars = ["一", "天", "主", "經", "母", "福", "丕"]
    for c in sample_chars:
        print(f"Chữ '{c}': readings = {dic.get_readings(c)}")
    print("Match 一 vs nhất:", dic.is_phonetic_match("一", "nhất"))
    print("Match 天 vs thiên:", dic.is_phonetic_match("天", "thiên"))
    print("Match 天 vs địa:", dic.is_phonetic_match("天", "địa"))
