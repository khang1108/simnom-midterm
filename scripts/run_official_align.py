import argparse
import csv
import json
import os
import subprocess
import sys
from pathlib import Path
from typing import Any, Dict, List, Optional

# Đảm bảo root workspace có trong sys.path
ROOT_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT_DIR))

from src.aligner.book_aligner import BookAligner

DEFAULT_READING_TABLES = [
    "data/entries/btcn.jsonl",
    "data/entries/dnqatv_wikisource.jsonl",
    "data/entries/dv.jsonl",
    "data/entries/hannom_rcv.jsonl",
    "data/entries/hvdic.jsonl",
    "data/entries/unihan.jsonl",
]


def _resolve_tables(cli_tables: Optional[List[str]]) -> List[str]:
    """Lấy danh sách nguồn âm đọc an toàn (tránh nạp catusf.jsonl 2.3GB)."""
    if cli_tables:
        return cli_tables
    env_val = os.environ.get("NOM_ALIGN_TABLE", "").strip()
    if env_val:
        return [p for p in env_val.split(os.pathsep) if p]
    if (ROOT_DIR / ".env").exists():
        # .env sẽ tự được python -m ocr_nom_align nạp, không cần truyền thêm --table
        return []
    return [t for t in DEFAULT_READING_TABLES if (ROOT_DIR / t).exists()]


def _run_cli(cmd: List[str], check: bool = True) -> subprocess.CompletedProcess:
    proc = subprocess.run(cmd, cwd=str(ROOT_DIR), capture_output=True, text=True)
    if proc.stdout.strip():
        print(proc.stdout.strip())
    if proc.stderr.strip():
        print(proc.stderr.strip(), file=sys.stderr)
    if check and proc.returncode != 0:
        raise RuntimeError(f"Lệnh thất bại (exit {proc.returncode}): {' '.join(cmd)}")
    return proc


def run_hybrid_alignment(
    book_dir: Path,
    book_name: Optional[str] = None,
    out_dir: Path = Path("output/align_v24"),
    mode: str = "phonetic",
    method: str = "nlp",
    tables: Optional[List[str]] = None,
    offline: bool = True,
    names: Optional[str] = None,
    similar: Optional[str] = None,
    ranges: Optional[str] = None,
    clean_labels_dir: Optional[Path] = None,
    check_final: bool = True,
) -> Dict[str, Any]:
    """
    Pipeline lai (Hybrid Pipeline) chuẩn Quy định v2.4:
    1. BookAligner chiếu ranh giới câu Quốc ngữ -> Hán Nôm (giải quyết Nôm không chấm câu) -> pairs.csv.
    2. ocr-nom-align diff tính Levenshtein text_diff, xuất CSV, XLSX và _align_report.json.
    3. ocr-nom-align check, check-diff --final và score kiểm định chất lượng.
    """
    book_dir = Path(book_dir)
    book_name = book_name or book_dir.name
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)

    # Bước 1: Chiếu ranh giới câu DP và xuất pairs.csv (đảm bảo không có hàng rỗng một vế)
    aligner = BookAligner(method=method)
    clean_dir_str = str(clean_labels_dir) if clean_labels_dir else None
    projected = aligner.project_book_pairs(
        book_dir=str(book_dir),
        book_name=book_name,
        clean_labels_dir=clean_dir_str,
    )
    pairs = projected["pairs"]

    pairs_csv = out_dir / f"{book_name}_pairs.csv"
    with pairs_csv.open("w", encoding="utf-8-sig", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=["img_id", "sentence_id", "ch_txt", "vi_txt"])
        writer.writeheader()
        for row in pairs:
            writer.writerow(row)
    print(f"[Hybrid Align] Đã xuất {len(pairs)} cặp câu tiền dóng hàng tại: {pairs_csv}")

    # Bước 2: Chạy công cụ chuẩn ocr-nom-align diff
    out_csv = out_dir / f"{book_name}.csv"
    out_xlsx = out_dir / f"{book_name}.xlsx"
    out_report = out_dir / f"{book_name}_align_report.json"

    diff_cmd = [
        sys.executable, "-m", "ocr_nom_align", "diff",
        str(pairs_csv),
        "--out", str(out_csv),
        "--xlsx", str(out_xlsx),
        "--report", str(out_report),
        "--mode", mode,
    ]
    if offline:
        diff_cmd.append("--offline")
    for tbl in _resolve_tables(tables):
        diff_cmd.extend(["--table", tbl])
    if names:
        diff_cmd.extend(["--names", names])
    if similar:
        diff_cmd.extend(["--similar", similar])
    if ranges:
        diff_cmd.extend(["--ranges", ranges])

    print(f"[Hybrid Align] Đang chạy ocr-nom-align diff (mode={mode}, offline={offline})...")
    _run_cli(diff_cmd, check=True)

    # Bước 3: Kiểm tra cấu trúc CSV + XLSX (`check`)
    print(f"[Hybrid Align] Đang chạy ocr-nom-align check...")
    _run_cli([sys.executable, "-m", "ocr_nom_align", "check", str(out_csv), "--xlsx", str(out_xlsx)], check=True)

    # Bước 4: Kiểm định đồng bộ & submission gate (`check-diff`)
    clean_paths = projected.get("clean_paths", {})
    ch_label = clean_paths.get("ch_label") or str(book_dir / "ch" / "Label.txt")
    vi_label = clean_paths.get("vi_label") or str(book_dir / "vi" / "Label.txt")
    ch_char = clean_paths.get("ch_char_label") or (
        str(book_dir / "ch" / "Label_char.txt") if (book_dir / "ch" / "Label_char.txt").exists() else None
    )
    image_map = book_dir / f"{book_name}_image_map.json"

    check_diff_cmd = [
        sys.executable, "-m", "ocr_nom_align", "check-diff",
        str(out_csv),
        "--xlsx", str(out_xlsx),
        "--ch", ch_label,
        "--vi", vi_label,
    ]
    if ch_char and Path(ch_char).exists():
        check_diff_cmd.extend(["--ch-char", ch_char])
    if image_map.exists():
        check_diff_cmd.extend(["--image-map", str(image_map)])
    if check_final:
        check_diff_cmd.append("--final")

    print(f"[Hybrid Align] Đang chạy ocr-nom-align check-diff...")
    check_proc = _run_cli(check_diff_cmd, check=False)

    # Bước 5: Tính điểm chuẩn (`score`)
    print(f"[Hybrid Align] Đang chạy ocr-nom-align score...")
    score_proc = _run_cli([sys.executable, "-m", "ocr_nom_align", "score", str(out_csv)], check=True)
    score_stats = json.loads(score_proc.stdout)

    return {
        "pairs_csv": str(pairs_csv),
        "csv_path": str(out_csv),
        "xlsx_path": str(out_xlsx),
        "report_path": str(out_report),
        "clean_paths": clean_paths,
        "check_diff_exit_code": check_proc.returncode,
        "score": score_stats,
        "aligned_rows_count": len(pairs),
    }


def main():
    parser = argparse.ArgumentParser(
        description="Hybrid Sino-Nom Alignment (BookAligner DP Boundary Projection + Official ocr-nom-align)."
    )
    parser.add_argument("--book-dir", type=str, required=True, help="Thư mục sách (chứa ch/, vi/, image_map.json)")
    parser.add_argument("--book-name", type=str, default=None, help="Tên sách (mặc định theo tên thư mục)")
    parser.add_argument("--out-dir", type=str, default="output/align_v24", help="Thư mục xuất kết quả")
    parser.add_argument("--mode", type=str, default="phonetic", choices=["phonetic", "meaning"], help="Loại bản dịch")
    parser.add_argument("--method", type=str, default="nlp", choices=["nlp", "baseline"], help="Phương pháp tách/chiếu câu")
    parser.add_argument("--table", action="append", default=None, help="Nguồn bảng âm đọc (có thể lặp)")
    parser.add_argument("--online", action="store_true", help="Cho phép tra hvdic trực tuyến các chữ chưa biết")
    parser.add_argument("--names", type=str, default=None, help="File danh sách tên riêng")
    parser.add_argument("--similar", type=str, default=None, help="File bảng chữ tương tự SinoNom_Similar_Dic_v2.csv")
    parser.add_argument("--ranges", type=str, default=None, help="File JSON khai báo các đoạn dịch nghĩa")
    parser.add_argument(
        "--clean-labels-out",
        nargs="?",
        const="AUTO",
        default=None,
        help="Xuất bản sao Label.txt / Label_char.txt đã lọc box rác ngoài khung (mặc định: <out-dir>/clean_book)",
    )
    args = parser.parse_args()

    out_dir = Path(args.out_dir)
    clean_dir = None
    if args.clean_labels_out is not None:
        clean_dir = (out_dir / "clean_book") if args.clean_labels_out == "AUTO" else Path(args.clean_labels_out)

    res = run_hybrid_alignment(
        book_dir=Path(args.book_dir),
        book_name=args.book_name,
        out_dir=out_dir,
        mode=args.mode,
        method=args.method,
        tables=args.table,
        offline=not args.online,
        names=args.names,
        similar=args.similar,
        ranges=args.ranges,
        clean_labels_dir=clean_dir,
    )
    if res["check_diff_exit_code"] != 0:
        sys.exit(res["check_diff_exit_code"])


if __name__ == "__main__":
    main()
