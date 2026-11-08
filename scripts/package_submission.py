import os
import sys
from pathlib import Path

# Đảm bảo root workspace có trong sys.path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import glob
import json
import zipfile
import shutil
import logging
from typing import List, Dict, Any

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger("packager")

# Cấu hình danh sách MSSV của nhóm
TEAM_MSSV = ["24120068", "24120151", "24120103"]
ZIP_NAME = "_".join(TEAM_MSSV) + ".zip"
REPORT_PDF_NAME = "_".join(TEAM_MSSV) + "_report.pdf"

def validate_ppocr_folder(folder_path: str) -> bool:
    """Kiểm tra tính hợp lệ của thư mục PPOCR (Label.txt và fileState.txt)."""
    label_file = os.path.join(folder_path, "Label.txt")
    state_file = os.path.join(folder_path, "fileState.txt")

    if not os.path.exists(label_file) or not os.path.exists(state_file):
        logger.error(f"Thiếu Label.txt hoặc fileState.txt trong {folder_path}")
        return False

    # Kiểm tra fileState.txt: mọi dòng phải có state == 1
    with open(state_file, "r", encoding="utf-8") as f:
        for idx, line in enumerate(f, 1):
            line = line.strip()
            if not line:
                continue
            parts = line.split("\t")
            if len(parts) != 2 or parts[1] != "1":
                logger.error(f"{state_file} dòng {idx}: State '{parts[-1]}' khác '1'")
                return False

    # Kiểm tra Label.txt: mỗi box phải đúng 4 điểm
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

def create_source_zip(source_zip_path: str, root_dir: str):
    """Tạo source.zip chứa toàn bộ mã nguồn sạch sẽ và pinned dependencies."""
    logger.info(f"Đang đóng gói source.zip tại {source_zip_path}...")
    exclude_dirs = {
        ".git", ".gemini", "__pycache__", ".pytest_cache", ".venv", "venv", 
        "data", "output", "build", "dist", ".idea", ".vscode"
    }
    exclude_extensions = {".pyc", ".pyo", ".pyd", ".pdf", ".zip", ".tar.gz", ".db"}

    with zipfile.ZipFile(source_zip_path, "w", zipfile.ZIP_DEFLATED) as zf:
        for dirpath, dirnames, filenames in os.walk(root_dir):
            # Lọc bỏ thư mục không cần thiết
            dirnames[:] = [d for d in dirnames if d not in exclude_dirs]
            
            for file in filenames:
                _, ext = os.path.splitext(file)
                if ext in exclude_extensions:
                    continue
                # Bỏ qua token và credentials bí mật
                if file in ("kim_token.txt", "openai_config.json"):
                    continue

                abs_path = os.path.join(dirpath, file)
                rel_path = os.path.relpath(abs_path, root_dir)
                zf.write(abs_path, rel_path)
    logger.info("Đã tạo source.zip thành công.")

def package_submission(
    processed_books_dir: str,
    output_zip_dir: str,
    report_pdf_path: str = None
):
    """
    Tạo file submission nộp bài chuẩn theo đúng định dạng Rubric v2.1:
    <MSSV1_MSSV2_MSSV3>.zip
    """
    os.makedirs(output_zip_dir, exist_ok=True)
    final_zip_path = os.path.join(output_zip_dir, ZIP_NAME)
    temp_dir = os.path.join(output_zip_dir, "_temp_package")
    
    if os.path.exists(temp_dir):
        shutil.rmtree(temp_dir)
    os.makedirs(temp_dir)

    try:
        # 1. Tìm các thư mục sách đã xử lý
        book_folders = [
            f for f in glob.glob(os.path.join(processed_books_dir, "*"))
            if os.path.isdir(f) and not os.path.basename(f).startswith("_")
        ]

        if not book_folders:
            logger.warning(f"Không tìm thấy thư mục sách nào trong {processed_books_dir}")

        for book_f in book_folders:
            book_name = os.path.basename(book_f)
            logger.info(f"Đang kiểm tra và đóng gói sách: {book_name}")
            dest_book_dir = os.path.join(temp_dir, book_name)
            
            # Copy thư mục sách vào temp_dir (bỏ qua _raw_slices)
            shutil.copytree(
                book_f, 
                dest_book_dir, 
                ignore=shutil.ignore_patterns("_raw_slices", "*.tmp")
            )

            # Xoá các thư mục con rỗng không sử dụng (intro, ref, toc, missing nếu rỗng)
            for sub in ("intro", "ref", "toc", "misc", "missing", "blank"):
                sub_p = os.path.join(dest_book_dir, sub)
                if os.path.exists(sub_p):
                    # Nếu không có file con nào bên trong, xoá thư mục rỗng
                    has_files = any(files for _, _, files in os.walk(sub_p))
                    if not has_files:
                        shutil.rmtree(sub_p)

            # Kiểm tra validation PPOCR cho các thư mục bắt buộc hoặc có dữ liệu
            for sub in ("ch", "vi", "intro", "ref", "toc"):
                sub_p = os.path.join(dest_book_dir, sub)
                if os.path.exists(sub_p):
                    is_valid = validate_ppocr_folder(sub_p)
                    if not is_valid:
                        logger.error(f"[THẤT BẠI] Thư mục {sub_p} không đạt chuẩn PPOCRLabel!")
                    else:
                        logger.info(f"[ĐẠT CHUẨN] {sub_p} đạt 100% chuẩn PPOCRLabel.")

            # Kiểm tra sự tồn tại của .csv và .xlsx
            csv_file = os.path.join(dest_book_dir, f"{book_name}.csv")
            xlsx_file = os.path.join(dest_book_dir, f"{book_name}.xlsx")
            if not os.path.exists(csv_file):
                logger.warning(f"Chưa có file CSV: {csv_file}")
            if not os.path.exists(xlsx_file):
                logger.warning(f"Chưa có file XLSX: {xlsx_file}")

        # 2. Tạo source.zip
        source_zip_path = os.path.join(temp_dir, "source.zip")
        create_source_zip(source_zip_path, root_dir=".")

        # 3. Copy file báo cáo PDF nếu có
        dest_report_path = os.path.join(temp_dir, REPORT_PDF_NAME)
        if report_pdf_path and os.path.exists(report_pdf_path):
            shutil.copy(report_pdf_path, dest_report_path)
            logger.info(f"Đã đính kèm báo cáo PDF: {REPORT_PDF_NAME}")
        else:
            # Tạo placeholder PDF nếu chưa xuất
            logger.warning(f"Không tìm thấy báo cáo PDF tại {report_pdf_path}, vui lòng bổ sung trước khi nộp chính thức.")

        # 4. Nén toàn bộ temp_dir thành file submission ZIP cuối cùng
        logger.info(f"Đang tạo gói nộp bài cuối cùng: {final_zip_path}...")
        with zipfile.ZipFile(final_zip_path, "w", zipfile.ZIP_DEFLATED) as final_zip:
            for root, _, files in os.walk(temp_dir):
                for f in files:
                    abs_p = os.path.join(root, f)
                    rel_p = os.path.relpath(abs_p, temp_dir)
                    final_zip.write(abs_p, rel_p)

        logger.info(f"[HOÀN THÀNH] Đã đóng gói thành công file nộp bài: {final_zip_path}")
        logger.info(f"Kích thước file: {os.path.getsize(final_zip_path) / (1024*1024):.2f} MB")
        return final_zip_path

    finally:
        if os.path.exists(temp_dir):
            shutil.rmtree(temp_dir)

if __name__ == "__main__":
    package_submission(
        processed_books_dir="data/processed",
        output_zip_dir="output",
        report_pdf_path="24120068_24120151_24120103_report.pdf"
    )
