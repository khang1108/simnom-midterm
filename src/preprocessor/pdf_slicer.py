import os
import subprocess
import shutil
from pathlib import Path
from typing import List, Optional
from PIL import Image

class PDFSlicer:
    """
    Trích xuất từng trang PDF thành các file ảnh .jpg chuẩn 300 DPI theo cú pháp:
    <Tên sách>.<Số thứ tự trang>[_<Số thứ tự hình ảnh>].jpg
    """
    def __init__(self, dpi: int = 300):
        self.dpi = dpi

    def slice_pdf(
        self,
        pdf_path: Path,
        output_dir: Path,
        book_name: Optional[str] = None,
        first_page: Optional[int] = None,
        last_page: Optional[int] = None,
        split_double_pages: bool = False
    ) -> List[Path]:
        pdf_path = Path(pdf_path)
        if not pdf_path.exists():
            raise FileNotFoundError(f"PDF not found: {pdf_path}")

        if not book_name:
            book_name = pdf_path.stem

        output_dir = Path(output_dir)
        output_dir.mkdir(parents=True, exist_ok=True)

        # Thư mục tạm để pdftoppm kết xuất
        temp_dir = output_dir / "_temp_raw_pages"
        temp_dir.mkdir(parents=True, exist_ok=True)

        cmd = [
            "pdftoppm",
            "-jpeg",
            "-r", str(self.dpi)
        ]
        if first_page is not None:
            cmd.extend(["-f", str(first_page)])
        if last_page is not None:
            cmd.extend(["-l", str(last_page)])

        prefix = "raw_page"
        cmd.extend([str(pdf_path), str(temp_dir / prefix)])

        print(f"[PDFSlicer] Executing: {' '.join(cmd)}")
        res = subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
        if res.returncode != 0:
            shutil.rmtree(temp_dir, ignore_errors=True)
            raise RuntimeError(f"pdftoppm failed: {res.stderr}")

        # Lấy danh sách ảnh đã trích xuất, sắp xếp theo số trang
        raw_files = sorted(
            temp_dir.glob(f"{prefix}-*.jpg"),
            key=lambda p: int(p.stem.split("-")[-1])
        )

        final_images: List[Path] = []

        start_offset = (first_page or 1) - 1
        for idx, raw_path in enumerate(raw_files, start=1):
            page_num = (first_page or 1) + idx - 1 if first_page else idx

            if split_double_pages:
                # Cắt đôi ảnh scan 2 trang thành trang phải (_1) và trang trái (_2) hoặc ngược lại
                with Image.open(raw_path) as im:
                    w, h = im.size
                    mid = w // 2
                    # Nửa trái
                    left_crop = im.crop((0, 0, mid, h))
                    # Nửa phải
                    right_crop = im.crop((mid, 0, w, h))

                    out_path_1 = output_dir / f"{book_name}.{page_num:03d}_1.jpg"
                    out_path_2 = output_dir / f"{book_name}.{page_num:03d}_2.jpg"

                    left_crop.save(out_path_1, "JPEG", quality=95)
                    right_crop.save(out_path_2, "JPEG", quality=95)

                    final_images.extend([out_path_1, out_path_2])
            else:
                out_path = output_dir / f"{book_name}.{page_num:03d}.jpg"
                shutil.move(str(raw_path), str(out_path))
                final_images.append(out_path)

        # Dọn dẹp thư mục tạm
        shutil.rmtree(temp_dir, ignore_errors=True)
        print(f"[PDFSlicer] Successfully generated {len(final_images)} images in {output_dir}")
        return final_images

