import shutil
import cv2
import numpy as np
from pathlib import Path
from typing import Dict, List, Set

class ImageClassifier:
    """
    Module phân loại hình ảnh vào các thư mục theo chuẩn Rubric v2.1.
    Phiên bản Baseline: Ưu tiên phân loại dựa trên khai báo trang thực tế của sách,
    tránh can thiệp các bộ lọc giả định (ghost numbers) khi chưa có dữ liệu đo đạc thực nghiệm.
    """

    @staticmethod
    def is_blank_page_baseline(image_path: Path, threshold_white_ratio: float = 0.98) -> bool:
        """
        Baseline đơn giản để kiểm tra trang trắng:
        Tính tỷ lệ điểm ảnh sáng (> 240/255). Nếu gần như toàn bộ trang (> 98%) là màu trắng/sáng
        thì coi là trang trắng.
        """
        img = cv2.imread(str(image_path), cv2.IMREAD_GRAYSCALE)
        if img is None:
            return False
        white_pixels = np.count_nonzero(img > 240)
        total_pixels = img.size
        return (white_pixels / total_pixels) >= threshold_white_ratio

    @staticmethod
    def organize_directory(
        source_dir: Path,
        target_book_dir: Path,
        mapping_rules: Dict[str, List[int]],
        auto_detect_blank: bool = False
    ):
        """
        Sắp xếp ảnh từ source_dir vào cây thư mục nộp bài chuẩn Rubric v2.1:
        - ch/       : Trang Hán Nôm
        - vi/       : Trang Quốc ngữ
        - intro/    : Trang giới thiệu (nếu có)
        - ref/      : Trang chú thích (nếu có)
        - toc/      : Trang mục lục (nếu có)
        - blank/    : Trang trắng
        - misc/     : Trang bìa, trang không liên quan
        - missing/  : Trang mất do scan
        """
        target_book_dir = Path(target_book_dir)
        source_dir = Path(source_dir)

        # 1. Tạo sẵn đầy đủ các thư mục theo cấu trúc nộp bài
        standard_folders = [
            "ch", "vi", "intro", "ref", "toc", "blank", "misc",
            "missing/ch", "missing/vi"
        ]
        for f in standard_folders:
            (target_book_dir / f).mkdir(parents=True, exist_ok=True)

        assigned_files: Set[str] = set()

        # 2. Phân loại dứt khoát theo khai báo phạm vi trang của người dùng
        for folder, page_list in mapping_rules.items():
            dest_dir = target_book_dir / folder
            dest_dir.mkdir(parents=True, exist_ok=True)
            for page_num in page_list:
                matches = list(source_dir.glob(f"*.{page_num:03d}*.jpg"))
                for p in matches:
                    shutil.copy(str(p), str(dest_dir / p.name))
                    assigned_files.add(p.name)

        # 3. Với các trang còn lại (chưa được khai báo cụ thể)
        for img_path in sorted(source_dir.glob("*.jpg")):
            if img_path.name in assigned_files:
                continue

            if auto_detect_blank and ImageClassifier.is_blank_page_baseline(img_path):
                dest = target_book_dir / "blank" / img_path.name
                shutil.copy(str(img_path), str(dest))
                print(f"[ImageClassifier] Baseline detected BLANK: {img_path.name}")
            else:
                dest = target_book_dir / "misc" / img_path.name
                shutil.copy(str(img_path), str(dest))
                print(f"[ImageClassifier] Unassigned page moved to misc/: {img_path.name}")
