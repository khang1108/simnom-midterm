"""Evaluate Colab T4 Quốc ngữ OCR candidates (VietOCR vs Qwen2.5-VL-3B vs Local Tesseract)
on pages 048-050 (`T1_Bao_Cao_Tien_Do`) using official `ocr-nom-align` v2.4 pipeline.
"""

import csv
import json
import re
import shutil
import subprocess
import sys
from pathlib import Path
from typing import Dict, List

ROOT_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT_DIR))

from scripts.run_official_align import DEFAULT_READING_TABLES, run_hybrid_alignment

BASE_BOOK_DIR = ROOT_DIR / "data/processed/T1_Bao_Cao_Tien_Do"
T1_VI_DIR = ROOT_DIR / "data/processed/T1_Sách Dạy Đấng Làm Người Sửa Mình (Tập 1)/vi"
BENCH_DIR = ROOT_DIR / "output/ocr_benchmark"
EXTRA_PUA_TABLE = ROOT_DIR / "configs/extra_pua_readings.csv"

TARGET_PAGES = ("048", "049", "050")
_PAGE_NUM_RE = re.compile(r"\.(\d{3})\.jpe?g$", re.I)


def clean_vietocr_line(text: str, bbox: List[int]) -> str:
    """Apply conservative post-OCR cleanup for edge specks and short-line bleed-through."""
    t = " ".join(text.split()).strip()
    if t.startswith("- "):
        t = t[2:].strip()
    # Short paragraph-ending lines occasionally catch faint bleed-through after '?' / '!' / '.'
    # e.g. "nó, thì có ai nghe được chăng ?nsh Y tinh" -> "nó, thì có ai nghe được chăng ?"
    m_q = re.match(r"^(.+\?)\s*[A-Za-z][A-Za-z\s]{0,16}$", t)
    if m_q and (bbox[2] - bbox[0]) < 650:
        t = m_q.group(1).strip()
    return t


def load_bench_vi_labels(label_path: Path) -> Dict[str, List[dict]]:
    """Load Label.txt from Colab benchmark keyed by 3-digit page number."""
    by_page: Dict[str, List[dict]] = {}
    for line in label_path.read_text(encoding="utf-8-sig").splitlines():
        if not line.strip() or "\t" not in line:
            continue
        img_path, js = line.split("\t", 1)
        m = _PAGE_NUM_RE.search(img_path)
        if m and m.group(1) in TARGET_PAGES:
            by_page[m.group(1)] = json.loads(js)
    return by_page


def prepare_benchmark_book(dest_dir: Path, label_path: Path, apply_clean: bool = False) -> Path:
    """Create a self-contained T1_Bao_Cao_Tien_Do clone with custom vi/Label.txt & 72-DPI vi images."""
    if dest_dir.exists():
        shutil.rmtree(dest_dir)
    dest_dir.mkdir(parents=True, exist_ok=True)

    shutil.copytree(BASE_BOOK_DIR / "ch", dest_dir / "ch")
    shutil.copy2(
        BASE_BOOK_DIR / "T1_Bao_Cao_Tien_Do_image_map.json",
        dest_dir / "T1_Bao_Cao_Tien_Do_image_map.json",
    )

    vi_dir = dest_dir / "vi"
    vi_dir.mkdir(parents=True, exist_ok=True)

    by_page = load_bench_vi_labels(label_path)
    label_lines: List[str] = []
    state_lines: List[str] = []

    for p in TARGET_PAGES:
        src_img = T1_VI_DIR / f"T1_Sách Dạy Đấng Làm Người Sửa Mình (Tập 1).{p}.jpg"
        dst_name = f"T1_Bao_Cao_Tien_Do.{p}.jpg"
        shutil.copy2(src_img, vi_dir / dst_name)

        boxes = by_page[p]
        out_boxes = []
        for b in boxes:
            nb = dict(b)
            txt = str(nb.get("transcription", ""))
            if apply_clean:
                pts = nb.get("points") or []
                xs = [pt[0] for pt in pts]
                ys = [pt[1] for pt in pts]
                bbox = [min(xs), min(ys), max(xs), max(ys)] if xs and ys else [0, 0, 800, 40]
                txt = clean_vietocr_line(txt, bbox)
            nb["transcription"] = txt
            out_boxes.append(nb)

        label_lines.append(f"vi/{dst_name}\t{json.dumps(out_boxes, ensure_ascii=False)}\n")
        state_lines.append(f"{(vi_dir / dst_name).resolve()}\t1\n")

    (vi_dir / "Label.txt").write_text("".join(label_lines), encoding="utf-8")
    (vi_dir / "fileState.txt").write_text("".join(state_lines), encoding="utf-8")
    return dest_dir


def inspect_red_errors(csv_path: Path) -> List[dict]:
    """Extract remaining red (`error`) elements from exported CSV `text_diff`."""
    errors: List[dict] = []
    with csv_path.open("r", encoding="utf-8-sig", newline="") as f:
        for row in csv.DictReader(f):
            diff = json.loads(row["text_diff"])
            for el in diff:
                if el.get("type") == "error":
                    errors.append(
                        {
                            "sentence_id": row["sentence_id"],
                            "nom_sub_text": el.get("nom_sub_text", ""),
                            "vi_sub_text": el.get("vi_sub_text", ""),
                            "nom_pos": el.get("nom_pos", []),
                            "vi_pos": el.get("vi_pos", []),
                        }
                    )
    return errors


def check_cmd_exit(cmd: List[str]) -> str:
    proc = subprocess.run(cmd, cwd=str(ROOT_DIR), capture_output=True, text=True)
    return "ok" if proc.returncode == 0 else f"FAIL({proc.returncode})"


def main() -> None:
    book_vietocr_raw = prepare_benchmark_book(
        BENCH_DIR / "book_vietocr_raw", BENCH_DIR / "vietocr_vi_Label.txt", apply_clean=False
    )
    book_vietocr_clean = prepare_benchmark_book(
        BENCH_DIR / "book_vietocr", BENCH_DIR / "vietocr_vi_Label.txt", apply_clean=True
    )
    book_vlm = prepare_benchmark_book(
        BENCH_DIR / "book_vlm", BENCH_DIR / "vlm_vi_Label.txt", apply_clean=False
    )

    candidates = [
        ("tesseract_baseline", BASE_BOOK_DIR),
        ("vietocr_raw", book_vietocr_raw),
        ("vietocr_clean", book_vietocr_clean),
        ("qwen25vl_3b", book_vlm),
    ]
    table_configs = [
        ("std6", list(DEFAULT_READING_TABLES)),
        ("std6_plus_pua", list(DEFAULT_READING_TABLES) + [str(EXTRA_PUA_TABLE.relative_to(ROOT_DIR))]),
    ]

    results = []
    for cand_name, book_dir in candidates:
        for tbl_name, tables in table_configs:
            out_dir = BENCH_DIR / f"eval_{cand_name}_{tbl_name}"
            print(f"\n>>> Running {cand_name} [{tbl_name}] -> {out_dir.relative_to(ROOT_DIR)}")
            res = run_hybrid_alignment(
                book_dir=book_dir,
                book_name="T1_Bao_Cao_Tien_Do",
                out_dir=out_dir,
                mode="phonetic",
                method="nlp",
                tables=tables,
                offline=True,
                clean_labels_dir=out_dir / "clean_book",
                check_final=True,
            )
            chk_status = check_cmd_exit(
                [sys.executable, "-m", "ocr_nom_align", "check", res["csv_path"], "--xlsx", res["xlsx_path"]]
            )
            red_errors = inspect_red_errors(Path(res["csv_path"]))
            sc = res["score"]
            results.append(
                {
                    "candidate": cand_name,
                    "tables": tbl_name,
                    "similarity": sc.get("similarity"),
                    "red_chars": sc.get("red_chars"),
                    "yellow_chars": sc.get("yellow_chars"),
                    "scored_chars": sc.get("scored_chars"),
                    "null_rows": sc.get("null_rows"),
                    "total_rows": sc.get("rows"),
                    "check": chk_status,
                    "check_diff_final": "ok" if res["check_diff_exit_code"] == 0 else f"FAIL({res['check_diff_exit_code']})",
                    "red_details": red_errors,
                }
            )

    summary_path = BENCH_DIR / "eval_summary.json"
    summary_path.write_text(json.dumps(results, ensure_ascii=False, indent=2), encoding="utf-8")

    print("\n" + "=" * 96)
    print(f"{'Candidate':<20} {'Tables':<15} {'Sim%':>7} {'Red':>5} {'Yellow':>7} {'Scored':>7} {'Rows':>5} {'Check':>7} {'Final':>7}")
    print("-" * 96)
    for r in results:
        print(
            f"{r['candidate']:<20} {r['tables']:<15} {r['similarity']:>7.2f} {r['red_chars']:>5} "
            f"{r['yellow_chars']:>7} {r['scored_chars']:>7} {r['total_rows']:>5} "
            f"{r['check']:>7} {r['check_diff_final']:>7}"
        )
    print("=" * 96)
    print("\nRemaining red pairs for std6_plus_pua:")
    for r in results:
        if r["tables"] == "std6_plus_pua" and r["candidate"] in ("vietocr_clean", "qwen25vl_3b"):
            print(f"\n--- {r['candidate']} ({len(r['red_details'])} red elements / {r['red_chars']} red chars) ---")
            for e in r["red_details"]:
                print(f"  [{e['sentence_id']}] ch={e['nom_sub_text']!r} <-> vi={e['vi_sub_text']!r}")


if __name__ == "__main__":
    main()
