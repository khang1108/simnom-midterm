import os
import sys
from pathlib import Path

# Đảm bảo root workspace có trong sys.path
ROOT_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT_DIR))

import json
import zipfile
import logging
import tempfile
from typing import Optional, Set

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger("packager")

# Cấu hình danh sách MSSV của nhóm thực hiện
TEAM_MSSV = ["24120068", "24120414"]
ZIP_NAME = "_".join(TEAM_MSSV) + ".zip"
REPORT_PDF_NAME = "_".join(TEAM_MSSV) + "_report.pdf"

ALREADY_COMPRESSED_EXTS = {".jpg", ".jpeg", ".png", ".pdf", ".xlsx", ".zip", ".gz"}


def validate_ppocr_folder(folder_path: str) -> bool:
    """Kiểm tra tính hợp lệ của thư mục PPOCR (Label.txt và fileState.txt)."""
    label_file = os.path.join(folder_path, "Label.txt")
    state_file = os.path.join(folder_path, "fileState.txt")

    if not os.path.exists(label_file) or not os.path.exists(state_file):
        logger.warning(f"Chưa có Label.txt hoặc fileState.txt trong {folder_path}")
        return False

    with open(state_file, "r", encoding="utf-8") as f:
        for idx, line in enumerate(f, 1):
            line = line.strip()
            if not line:
                continue
            parts = line.split("\t")
            if len(parts) != 2 or parts[1] != "1":
                logger.error(f"{state_file} dòng {idx}: State '{parts[-1]}' khác '1'")
                return False

    with open(label_file, "r", encoding="utf-8") as f:
        for idx, line in enumerate(f, 1):
            line = line.strip()
            if not line or "\t" not in line:
                continue
            parts = line.split("\t", 1)
            try:
                boxes = json.loads(parts[1])
                for b_idx, b in enumerate(boxes):
                    pts = b.get("points", [])
                    if len(pts) != 4 or not all(len(p) == 2 for p in pts):
                        logger.error(f"{label_file} dòng {idx} box {b_idx}: Box không đúng 4 điểm ({pts})")
                        return False
            except Exception as e:
                logger.error(f"{label_file} dòng {idx}: JSON không hợp lệ ({e})")
                return False

    return True


def create_source_zip(source_zip_path: str, root_dir: str) -> None:
    """Tạo source.zip chứa toàn bộ mã nguồn sạch sẽ và pinned dependencies."""
    logger.info(f"Đang đóng gói source.zip tại {source_zip_path}...")
    exclude_dirs = {
        ".git", ".gemini", "__pycache__", ".pytest_cache", ".venv", "venv",
        "data", "output", "build", "dist", ".idea", ".vscode"
    }
    exclude_extensions = {".pyc", ".pyo", ".pyd", ".pdf", ".zip", ".tar.gz", ".db"}

    with zipfile.ZipFile(source_zip_path, "w", zipfile.ZIP_DEFLATED) as zf:
        for dirpath, dirnames, filenames in os.walk(root_dir):
            dirnames[:] = sorted(d for d in dirnames if d not in exclude_dirs)
            for file in sorted(filenames):
                _, ext = os.path.splitext(file)
                if ext in exclude_extensions:
                    continue
                if file in ("kim_token.txt", "openai_config.json", ".env"):
                    continue
                abs_path = os.path.join(dirpath, file)
                rel_path = os.path.relpath(abs_path, root_dir)
                zf.write(abs_path, rel_path)
    logger.info("Đã tạo source.zip thành công.")


def create_extras_zip(extras_zip_path: str, processed_books_dir: str, root_dir: str) -> None:
    """Tạo extras.zip chứa bảng từ điển/tự hình tự xây dựng, sơ đồ và báo cáo kiểm định trung gian."""
    logger.info(f"Đang đóng gói extras.zip tại {extras_zip_path}...")
    with zipfile.ZipFile(extras_zip_path, "w", zipfile.ZIP_DEFLATED) as zf:
        configs_dir = Path(root_dir) / "configs"
        if configs_dir.is_dir():
            for p in sorted(configs_dir.iterdir()):
                if p.is_file() and p.suffix in (".csv", ".json") and p.name != "openai_config.json":
                    zf.write(p, f"configs/{p.name}")

        diagrams_dir = Path(root_dir) / "output" / "report_diagrams"
        if diagrams_dir.is_dir():
            for p in sorted(diagrams_dir.iterdir()):
                if p.is_file() and p.suffix in (".svg", ".html"):
                    zf.write(p, f"diagrams/{p.name}")

        extras_dir = Path(processed_books_dir) / "_extras"
        if extras_dir.is_dir():
            for p in sorted(extras_dir.rglob("*")):
                if p.is_file():
                    zf.write(p, f"align_reports/{p.relative_to(extras_dir)}")
    logger.info("Đã tạo extras.zip thành công.")


def _allowed_book_names(root_dir: str) -> Optional[Set[str]]:
    cfg_path = Path(root_dir) / "configs" / "books_structure.json"
    if not cfg_path.is_file():
        return None
    data = json.loads(cfg_path.read_text(encoding="utf-8"))
    return {v["book_name"] for v in data.values() if isinstance(v, dict) and "book_name" in v}


def package_submission(
    processed_books_dir: str = "data/processed",
    output_zip_dir: str = "output",
    report_pdf_path: Optional[str] = None,
) -> str:
    """
    Tạo file submission nộp bài chuẩn theo đúng định dạng Quy định v2.6:
    24120068_24120414.zip
    """
    os.makedirs(output_zip_dir, exist_ok=True)
    final_zip_path = os.path.join(output_zip_dir, ZIP_NAME)
    if report_pdf_path is None:
        candidate_out = os.path.join(output_zip_dir, REPORT_PDF_NAME)
        report_pdf_path = candidate_out if os.path.exists(candidate_out) else REPORT_PDF_NAME

    allowed_names = _allowed_book_names(str(ROOT_DIR))
    proc_root = Path(processed_books_dir)
    book_folders = sorted(
        p for p in proc_root.iterdir()
        if p.is_dir() and not p.name.startswith("_") and (allowed_names is None or p.name in allowed_names)
    ) if proc_root.is_dir() else []

    if not book_folders:
        logger.warning(f"Không tìm thấy thư mục sách nào hợp lệ trong {processed_books_dir}")

    with tempfile.TemporaryDirectory(dir=output_zip_dir) as temp_dir:
        source_zip_path = os.path.join(temp_dir, "source.zip")
        extras_zip_path = os.path.join(temp_dir, "extras.zip")
        create_source_zip(source_zip_path, root_dir=str(ROOT_DIR))
        create_extras_zip(extras_zip_path, processed_books_dir=processed_books_dir, root_dir=str(ROOT_DIR))

        logger.info(f"Đang tạo gói nộp bài cuối cùng: {final_zip_path}...")
        with zipfile.ZipFile(final_zip_path, "w") as final_zip:
            for book_f in book_folders:
                book_name = book_f.name
                logger.info(f"Đang kiểm tra và đóng gói sách: {book_name}")

                # Kiểm tra PPOCR cho các thư mục có văn bản (nếu đã chạy OCR)
                for sub in ("ch", "vi", "intro", "ref", "toc"):
                    sub_p = book_f / sub
                    if sub_p.is_dir() and any(sub_p.iterdir()):
                        if (sub_p / "Label.txt").is_file() or (sub_p / "fileState.txt").is_file():
                            is_valid = validate_ppocr_folder(str(sub_p))
                            if is_valid:
                                logger.info(f"[ĐẠT CHUẨN] {book_name}/{sub} đạt 100% chuẩn PPOCRLabel.")
                            else:
                                logger.error(f"[CHƯA ĐẠT] {book_name}/{sub} chưa đạt chuẩn PPOCRLabel!")
                        else:
                            logger.warning(f"[LƯU Ý] {book_name}/{sub} chưa có Label.txt / fileState.txt trên máy này.")

                for req_name in (f"{book_name}.pdf", f"{book_name}.csv", f"{book_name}.xlsx"):
                    if not (book_f / req_name).is_file():
                        logger.warning(f"[LƯU Ý] Chưa có file {book_name}/{req_name}")

                ph_map = book_f / f"{book_name}_placeholder_map.json"
                if ph_map.is_file():
                    from scripts.build_placeholder_map import check as check_ph
                    items = json.loads(ph_map.read_text(encoding="utf-8")).get("placeholders", [])
                    errs = check_ph(book_f, book_name, items)
                    if errs:
                        logger.error(f"[LỖI PLACEHOLDER MAP] {book_name}: {errs[:5]}")
                    else:
                        logger.info(f"[ĐẠT CHUẨN] {ph_map.name} hợp lệ ({len(items)} ký tự 〓).")

                # Đưa toàn bộ file hợp lệ của sách vào ZIP (bỏ qua _raw_slices, file tạm và thư mục rỗng)
                for p in sorted(book_f.rglob("*")):
                    if not p.is_file():
                        continue
                    rel_inside_book = p.relative_to(book_f)
                    if "_raw_slices" in rel_inside_book.parts or p.name.endswith(".tmp") or p.name.endswith(".bak"):
                        continue
                    arcname = f"{book_name}/{rel_inside_book.as_posix()}"
                    compress = (
                        zipfile.ZIP_STORED
                        if p.suffix.lower() in ALREADY_COMPRESSED_EXTS
                        else zipfile.ZIP_DEFLATED
                    )
                    final_zip.write(p, arcname, compress_type=compress)

            # Đính kèm source.zip và extras.zip
            final_zip.write(source_zip_path, "source.zip", compress_type=zipfile.ZIP_STORED)
            final_zip.write(extras_zip_path, "extras.zip", compress_type=zipfile.ZIP_STORED)

            # Đính kèm báo cáo PDF
            if report_pdf_path and os.path.exists(report_pdf_path):
                final_zip.write(report_pdf_path, REPORT_PDF_NAME, compress_type=zipfile.ZIP_STORED)
                logger.info(f"Đã đính kèm báo cáo PDF: {REPORT_PDF_NAME}")
            else:
                logger.warning(f"Không tìm thấy báo cáo PDF tại {report_pdf_path}!")

    size_mb = os.path.getsize(final_zip_path) / (1024 * 1024)
    logger.info(f"[HOÀN THÀNH] Đã đóng gói thành công: {final_zip_path} ({size_mb:.2f} MB)")
    return final_zip_path


if __name__ == "__main__":
    package_submission()
