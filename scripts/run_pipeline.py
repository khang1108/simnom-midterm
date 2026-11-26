import argparse
import os
import sys
import json
import logging
from pathlib import Path

# Đảm bảo root workspace có trong sys.path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from scripts.prepare_books import prepare_book
from src.ocr.runner import run_ocr_pipeline
from src.aligner.book_aligner import BookAligner
from scripts.package_submission import package_submission
from scripts.run_official_align import run_hybrid_alignment

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger("pipeline")

def main():
    parser = argparse.ArgumentParser(description="End-to-End Automated Sino-Nom Parallel Corpus Pipeline.")
    parser.add_argument("--pdf", type=str, required=True, help="Đường dẫn file PDF sách gốc")
    parser.add_argument("--book-name", type=str, default=None, help="Tên sách (mặc định lấy theo tên file PDF)")
    parser.add_argument("--stage", type=str, default="all", 
                        choices=["all", "slice", "classify", "ocr", "align", "package"],
                        help="Giai đoạn thực thi (mặc định: all)")
    parser.add_argument("--method", type=str, default="nlp",
                        choices=["baseline", "nlp"],
                        help="Phương pháp xử lý: baseline (v0 luật thô) hoặc nlp (v1 mô hình thống kê & hư từ)")
    parser.add_argument("--aligner", type=str, default="hybrid",
                        choices=["hybrid", "internal"],
                        help="Bộ dóng hàng: hybrid (BookAligner DP + ocr-nom-align chuẩn v2.4) hoặc internal")
    parser.add_argument("--mode", type=str, default="phonetic",
                        choices=["phonetic", "meaning"],
                        help="Loại bản dịch theo Quy định v2.4: phonetic (dịch âm 1-1) hoặc meaning (dịch nghĩa)")
    parser.add_argument("--offline", action=argparse.BooleanOptionalAction, default=True,
                        help="Tắt tra từ điển trực tuyến hvdic trong ocr-nom-align (mặc định: bật offline)")
    parser.add_argument("--dpi", type=int, default=72, help="DPI cắt ảnh (72 DPI ~ độ phân giải ảnh gốc trong PDF)")
    parser.add_argument("--config", type=str, default="configs/books_structure.json",
                        help="File cấu hình phân trang / ghép cặp trang của từng tập")

    # OCR Credentials
    parser.add_argument("--token-file", type=str, default="configs/kim_token.txt", help="File chứa token Kim Hán Nôm")
    parser.add_argument("--openai-key", type=str, default=None, help="API Key OpenAI-compatible (tuỳ chọn)")
    parser.add_argument("--openai-base-url", type=str, default=None, help="Base URL OpenAI-compatible")
    parser.add_argument("--openai-model", type=str, default=None, help="Model name OpenAI-compatible")
    parser.add_argument("--dry-run-ocr", action="store_true", help="Chạy OCR giả lập để kiểm thử pipeline")

    args = parser.parse_args()

    pdf_path = Path(args.pdf)
    if not pdf_path.exists():
        logger.error(f"Không tìm thấy file PDF: {pdf_path}")
        sys.exit(1)

    book_name = args.book_name or pdf_path.stem
    processed_dir = Path("data/processed") / book_name

    logger.info("=" * 60)
    logger.info(f"KHỞI ĐỘNG PIPELINE CHO SÁCH: {book_name}")
    logger.info(f"GIAI ĐOẠN: {args.stage.upper()}")
    logger.info("=" * 60)

    if args.stage in ("all", "slice", "classify"):
        logger.info(f"[Giai đoạn 1-2] Cắt ảnh {args.dpi} DPI, phân loại thư mục và sinh image_map...")
        all_cfg = json.loads(Path(args.config).read_text(encoding="utf-8"))
        key = next((k for k, c in all_cfg.items() if c["book_name"] == book_name), None)
        if key is None:
            logger.error(f"Không có cấu hình cho '{book_name}' trong {args.config}")
            sys.exit(1)
        res = prepare_book(key, all_cfg[key], out_root=Path("data/processed"), dpi=args.dpi)
        logger.info(f"  -> Đã chuẩn bị: {res}")

    # Giai đoạn 3: OCR Engine
    if args.stage in ("all", "ocr"):
        logger.info(f"[Giai đoạn 3] Chạy OCR sinh Label.txt và fileState.txt...")
        token = None
        if os.path.exists(args.token_file):
            token = open(args.token_file, "r", encoding="utf-8").read().strip()

        run_ocr_pipeline(
            book_dir=processed_dir,
            token=token,
            openai_key=args.openai_key,
            openai_base_url=args.openai_base_url,
            openai_model=args.openai_model,
            dry_run=args.dry_run_ocr
        )

    # Giai đoạn 4: Ghép câu xuyên trang, Dóng hàng DP & Xuất CSV/Excel
    if args.stage in ("all", "align"):
        logger.info(
            f"[Giai đoạn 4] Ghép câu xuyên trang và dóng hàng (Aligner: {args.aligner.upper()}, Method: {args.method.upper()}, Mode: {args.mode})..."
        )
        if args.aligner == "hybrid":
            res = run_hybrid_alignment(
                book_dir=processed_dir,
                book_name=book_name,
                out_dir=processed_dir,
                mode=args.mode,
                method=args.method,
                offline=args.offline,
            )
            logger.info(f"  -> Dóng hàng hoàn tất: {res['aligned_rows_count']} câu.")
            logger.info(f"  -> Độ tương đồng (ocr-nom-align): {res['score']['similarity']}%")
            if res["check_diff_exit_code"] != 0:
                logger.warning(
                    "  -> check-diff --final trả về mã lỗi != 0: kiểm tra lại box tiêu đề/lề ngoài khung trong Label.txt hoặc các lỗi chưa xử lý."
                )
        else:
            aligner = BookAligner(method=args.method)
            res = aligner.align_book(
                book_dir=str(processed_dir),
                book_name=book_name
            )
            logger.info(f"  -> Dóng hàng hoàn tất: {res['aligned_rows_count']} câu.")
            logger.info(f"  -> Độ tương đồng: {res['metrics']['similarity_percent']}%")

    # Giai đoạn 5: Đóng gói và kiểm tra nộp bài
    if args.stage in ("all", "package"):
        logger.info(f"[Giai đoạn 5] Đóng gói bài nộp...")
        zip_path = package_submission(
            processed_books_dir="data/processed",
            output_zip_dir="output",
            report_pdf_path="output/24120068_24120414_report.pdf"
        )
        logger.info(f"  -> Đã tạo gói nộp bài thành công: {zip_path}")

    logger.info("=" * 60)
    logger.info("HOÀN THÀNH TOÀN BỘ TIẾN TRÌNH PIPELINE THÀNH CÔNG!")
    logger.info("=" * 60)

if __name__ == "__main__":
    main()
