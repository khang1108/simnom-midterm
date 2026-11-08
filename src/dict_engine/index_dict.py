import os
import json
import sqlite3
import unicodedata
from pathlib import Path
from tqdm import tqdm

DB_PATH = Path("data/dict.db")
ENTRIES_DIR = Path("data/entries")

def init_db(db_path: Path):
    if db_path.exists():
        db_path.unlink()
    conn = sqlite3.connect(db_path)
    cur = conn.cursor()
    # Speed optimizations for bulk insert
    cur.execute("PRAGMA synchronous = OFF;")
    cur.execute("PRAGMA journal_mode = MEMORY;")
    cur.execute("PRAGMA cache_size = 100000;")
    
    cur.execute("""
    CREATE TABLE char_readings (
        head TEXT NOT NULL,
        reading TEXT NOT NULL,
        system TEXT,
        source TEXT
    );
    """)
    cur.execute("""
    CREATE TABLE variants (
        head TEXT NOT NULL,
        variant TEXT NOT NULL,
        type TEXT
    );
    """)
    conn.commit()
    return conn

def normalize_text(text: str) -> str:
    if not text:
        return ""
    return unicodedata.normalize("NFC", text.strip())

def index_readings(conn, file_path: Path, source_name: str, max_lines=None):
    if not file_path.exists():
        print(f"Skipping {file_path.name} (not found)")
        return
    
    cur = conn.cursor()
    rows = []
    batch_size = 50000
    total_count = 0
    
    print(f"Indexing {file_path.name}...")
    with open(file_path, "r", encoding="utf-8") as f:
        for idx, line in enumerate(f):
            if max_lines and idx >= max_lines:
                break
            line = line.strip()
            if not line:
                continue
            try:
                entry = json.loads(line)
            except Exception:
                continue
            
            head = normalize_text(entry.get("head", ""))
            if not head:
                continue
            
            # Extract readings
            for r in entry.get("readings", []):
                val = normalize_text(r.get("value", "")).lower()
                system = r.get("system", "")
                if val:
                    rows.append((head, val, system, source_name))
            
            # Extract variants if present
            for v in entry.get("variants", []):
                var_char = normalize_text(v.get("char", ""))
                var_type = v.get("type", "")
                if var_char:
                    cur.execute("INSERT INTO variants (head, variant, type) VALUES (?, ?, ?)", 
                                (head, var_char, var_type))
            
            # Extract relations (from cjkvi_variants)
            for rel in entry.get("relations", []):
                to_char = normalize_text(rel.get("to", ""))
                rel_type = rel.get("type", "")
                if to_char:
                    cur.execute("INSERT INTO variants (head, variant, type) VALUES (?, ?, ?)", 
                                (head, to_char, rel_type))

            if len(rows) >= batch_size:
                cur.executemany("INSERT INTO char_readings (head, reading, system, source) VALUES (?, ?, ?, ?)", rows)
                total_count += len(rows)
                rows = []

    if rows:
        cur.executemany("INSERT INTO char_readings (head, reading, system, source) VALUES (?, ?, ?, ?)", rows)
        total_count += len(rows)
        
    conn.commit()
    print(f"  -> Added {total_count} readings from {source_name}")

def create_indexes(conn):
    print("Creating indexes...")
    cur = conn.cursor()
    cur.execute("CREATE INDEX idx_head ON char_readings(head);")
    cur.execute("CREATE INDEX idx_reading ON char_readings(reading);")
    cur.execute("CREATE INDEX idx_variant_head ON variants(head);")
    cur.execute("CREATE INDEX idx_variant_var ON variants(variant);")
    conn.commit()
    print("Indexes created successfully.")

def main():
    conn = init_db(DB_PATH)
    
    # Priority sources for Sino-Nom <-> Quoc Ngu
    sources = [
        ("hannom_rcv.jsonl", "hannom_rcv"),
        ("btcn.jsonl", "btcn"),
        ("dv.jsonl", "dv"),
        ("dnqatv_wikisource.jsonl", "dnqatv"),
        ("hvdic.jsonl", "hvdic"),
        ("unihan.jsonl", "unihan"),
        ("cjkvi_variants.jsonl", "cjkvi_variants")
    ]
    
    for filename, source_name in sources:
        fpath = ENTRIES_DIR / filename
        index_readings(conn, fpath, source_name)
    
    create_indexes(conn)
    conn.close()
    
    size_mb = DB_PATH.stat().st_size / (1024 * 1024)
    print(f"Database built at {DB_PATH} ({size_mb:.2f} MB)")

if __name__ == "__main__":
    main()

