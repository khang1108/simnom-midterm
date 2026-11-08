import argparse
import os
import sys
import json
import logging
from pathlib import Path

# Đảm bảo root workspace có trong sys.path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from typing import Dict, List
from src.preprocessor.pdf_slicer import PDFSlicer
from src.preprocessor.image.image_classifier import ImageClassifier
from src.preprocessor.image.image_mapper import ImageMapper
from src.ocr.runner import run_ocr_pipeline
from src.aligner.book_aligner import BookAligner
from scripts.package_submission import package_submission

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger("pipeline")

def parse_range(range_str: str) -> List[int]:
    """Parse chuỗi '1-5,7,10-12' thành list các số nguyên."""
    result = []
    if not range_str:
        return result
    for p in range_str.split(","):
        p = p.strip()
        if "-" in p:
            start, end = map(int, p.split("-"))
            result.extend(range(start, end + 1))
        elif p.isdigit():
            result.append(int(p))
    return sorted(list(set(result)))

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
    parser.add_argument("--dpi", type=int, default=300, help="DPI trích xuất ảnh từ PDF (chuẩn 300)")
    parser.add_argument("--first-page", type=int, default=None, help="Trang bắt đầu trích xuất")
    parser.add_argument("--last-page", type=int, default=None, help="Trang kết thúc trích xuất")
    
    # Cấu hình phân trang cho T1 Sách Dạy Đấng Làm Người Sửa Mình (Tập 1): 1-318 vi, 319-636 ch
    parser.add_argument("--vi-pages", type=str, default="1-318", help="Dải trang Quốc ngữ")
    parser.add_argument("--ch-pages", type=str, default="319-634", help="Dải trang Hán Nôm")
    parser.add_argument("--blank-pages", type=str, default="635-636", help="Dải trang trắng")
    parser.add_argument("--layout", type=str, default="T1", choices=["T1", "T2", "T2b"], help="Layout quy định")
    
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
    raw_slice_dir = processed_dir / "_raw_slices"
    processed_dir.mkdir(parents=True, exist_ok=True)

    logger.info("=" * 60)
    logger.info(f"KHỞI ĐỘNG PIPELINE CHO SÁCH: {book_name}")
    logger.info(f"GIAI ĐOẠN: {args.stage.upper()}")
    logger.info("=" * 60)

    # Giai đoạn 1: Slicing PDF
    if args.stage in ("all", "slice"):
        logger.info(f"[Giai đoạn 1] Cắt PDF sang ảnh 300 DPI...")
        slicer = PDFSlicer(dpi=args.dpi)
        images = slicer.slice_pdf(
            pdf_path=pdf_path,
            output_dir=raw_slice_dir,
            book_name=book_name,
            first_page=args.first_page,
            last_page=args.last_page
        )
        logger.info(f"  -> Đã cắt {len(images)} trang ảnh.")

    # Giai đoạn 2: Phân loại thư mục & Sinh image_map.json
    if args.stage in ("all", "classify", "slice"):
        logger.info(f"[Giai đoạn 2] Phân loại thư mục ch/, vi/, blank/ và sinh image_map...")
        rules = {
            "vi": parse_range(args.vi_pages),
            "ch": parse_range(args.ch_pages),
            "blank": parse_range(args.blank_pages)
        }
        classifier = ImageClassifier(rules=rules)
        counts = classifier.classify(source_dir=raw_slice_dir, target_root=processed_dir)
        logger.info(f"  -> Kết quả phân loại: {counts}")

        # Sinh image_map
        mapper = ImageMapper(layout=args.layout)
        map_path = mapper.generate_map(target_root=processed_dir, book_name=book_name)
        logger.info(f"  -> Đã lưu image_map tại: {map_path}")

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
        logger.info(f"[Giai đoạn 4] Ghép câu xuyên trang và dóng hàng Phonetic DP (Method: {args.method.upper()})...")
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
            report_pdf_path="24120068_24120151_24120103_report.pdf"
        )
        logger.info(f"  -> Đã tạo gói nộp bài thành công: {zip_path}")

    logger.info("=" * 60)
    logger.info("HOÀN THÀNH TOÀN BỘ TIẾN TRÌNH PIPELINE THÀNH CÔNG!")
    logger.info("=" * 60)

if __name__ == "__main__":
    main()
