import cv2
import numpy as np
from pathlib import Path
from typing import List, Optional
from PIL import Image

class ImageEnhancer:
    """
    Tiền xử lý nâng cao chất lượng ảnh scan Hán Nôm:
    - Xoay ảnh (deskew / orientation correction)
    - Tăng độ tương phản (Adaptive Histogram Equalization / CLAHE)
    - Ghép thành file <Tên sách>_updated.pdf khi có chỉnh sửa.
    """
    @staticmethod
    def rotate_image(image_path: Path, angle_deg: int, output_path: Optional[Path] = None) -> Path:
        out = output_path or image_path
        if angle_deg == 0:
            return out
        with Image.open(image_path) as im:
            # expand=True để không bị mất góc ảnh khi xoay
            rotated = im.rotate(-angle_deg, expand=True)
            rotated.save(out, "JPEG", quality=95)
        return out

    @staticmethod
    def enhance_contrast_clahe(image_path: Path, output_path: Optional[Path] = None, clip_limit: float = 2.0) -> Path:
        """Tăng độ tương phản chữ viết tay/khắc in bằng CLAHE mà không làm tăng nhiễu giấy cổ."""
        out = output_path or image_path
        img = cv2.imread(str(image_path), cv2.IMREAD_GRAYSCALE)
        if img is None:
            raise ValueError(f"Cannot read image: {image_path}")

        clahe = cv2.createCLAHE(clipLimit=clip_limit, tileGridSize=(8, 8))
        enhanced = clahe.apply(img)

        cv2.imwrite(str(out), enhanced, [cv2.IMWRITE_JPEG_QUALITY, 95])
        return out

    @staticmethod
    def merge_to_updated_pdf(image_paths: List[Path], output_pdf_path: Path):
        """
        Merge danh sách ảnh đã tiền xử lý thành file <Tên sách>_updated.pdf
        theo đúng quy định Rubric v2.1.
        """
        if not image_paths:
            raise ValueError("No images provided to merge into PDF")

        output_pdf_path = Path(output_pdf_path)
        output_pdf_path.parent.mkdir(parents=True, exist_ok=True)

        pil_images = []
        for p in sorted(image_paths):
            im = Image.open(p)
            if im.mode != "RGB":
                im = im.convert("RGB")
            pil_images.append(im)

        first_img = pil_images[0]
        rest_imgs = pil_images[1:]

        first_img.save(
            str(output_pdf_path),
            save_all=True,
            append_images=rest_imgs,
            resolution=300.0,
            quality=95
        )
        print(f"[ImageEnhancer] Successfully created updated PDF at: {output_pdf_path}")

