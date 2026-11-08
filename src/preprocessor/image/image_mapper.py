import json
from pathlib import Path
from typing import List, Dict, Any, Optional

class ImageMapper:
    """
    Sinh và kiểm tra file ánh xạ hình ảnh <Tên sách>_image_map.json
    tuân thủ tuyệt đối quy định tại Trang 8-10 của [Rules] - v2.1.pdf.
    """
    @staticmethod
    def create_image_map_t1(
        book_name: str,
        vi_images: List[str],
        ch_images: List[str],
        missing_vi: Optional[List[str]] = None,
        missing_ch: Optional[List[str]] = None,
        ratio: int = 1
    ) -> Dict[str, Any]:
        """
        Tạo mapping cho sách loại T1:
        - Quốc ngữ đọc từ đầu đến cuối (tăng dần).
        - Nôm đọc ngược từ cuối sách về trước (số trang Nôm giảm dần).
        - ratio: số trang Nôm ứng với 1 trang Quốc ngữ (thường là 1 hoặc 2).
        """
        pairs = []
        vi_sorted = sorted(vi_images)
        # Nôm đọc ngược: sắp xếp giảm dần
        ch_sorted = sorted(ch_images, reverse=True)

        ch_idx = 0
        for vi_img in vi_sorted:
            ch_group = []
            for _ in range(ratio):
                if ch_idx < len(ch_sorted):
                    ch_group.append(ch_sorted[ch_idx])
                    ch_idx += 1
            pairs.append({
                "ch": ch_group,
                "vi": [vi_img]
            })

        # Ghi nhận các trang Quốc ngữ bị mất khi scan (Nôm có nhưng vi rỗng)
        if missing_vi:
            for ch_img in missing_vi:
                pairs.append({
                    "ch": [ch_img],
                    "vi": [],
                    "note": "Trang Quốc ngữ tương ứng bị mất khi scan"
                })

        # Ghi nhận các trang Nôm bị mất khi scan (ch rỗng nhưng vi có)
        if missing_ch:
            for vi_img in missing_ch:
                pairs.append({
                    "ch": [],
                    "vi": [vi_img],
                    "note": "Trang Nôm tương ứng bị mất khi scan"
                })

        return {"pairs": pairs}

    @staticmethod
    def save_image_map(data: Dict[str, Any], output_path: Path):
        output_path = Path(output_path)
        with open(output_path, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
        print(f"[ImageMapper] Saved image map to {output_path}")

    @staticmethod
    def validate_image_map(json_path: Path, book_dir: Path) -> List[str]:
        """
        Kiểm tra tính hợp lệ của file <Tên sách>_image_map.json theo Rubric:
        - JSON hợp lệ.
        - Mọi ảnh ở 'ch' phải tồn tại trong ch/ hoặc missing/ch/.
        - Mọi ảnh ở 'vi' phải tồn tại trong vi/ hoặc missing/vi/.
        - Không có tên trùng trong cùng một vế.
        - Không có cặp nào cả 2 vế đều rỗng.
        """
        errors = []
        if not json_path.exists():
            return [f"File {json_path} does not exist"]

        try:
            with open(json_path, "r", encoding="utf-8") as f:
                data = json.load(f)
        except Exception as e:
            return [f"Invalid JSON: {e}"]

        pairs = data.get("pairs")
        if not isinstance(pairs, list):
            return ["Missing or invalid 'pairs' array in image_map"]

        seen_ch = set()
        seen_vi = set()

        ch_dir = book_dir / "ch"
        missing_ch_dir = book_dir / "missing" / "ch"
        vi_dir = book_dir / "vi"
        missing_vi_dir = book_dir / "missing" / "vi"

        for idx, pair in enumerate(pairs):
            ch_list = pair.get("ch", [])
            vi_list = pair.get("vi", [])

            if not ch_list and not vi_list:
                errors.append(f"Pair #{idx} has both 'ch' and 'vi' empty.")

            # Validate ch images
            for img in ch_list:
                if img in seen_ch:
                    errors.append(f"Duplicate image in 'ch': {img}")
                seen_ch.add(img)

                # Kiểm tra tồn tại trên đĩa
                p1 = ch_dir / img
                p2 = missing_ch_dir / img
                if not p1.exists() and not p2.exists():
                    errors.append(f"Image '{img}' in 'ch' not found in ch/ or missing/ch/")

            # Validate vi images
            for img in vi_list:
                if img in seen_vi:
                    errors.append(f"Duplicate image in 'vi': {img}")
                seen_vi.add(img)

                p1 = vi_dir / img
                p2 = missing_vi_dir / img
                if not p1.exists() and not p2.exists():
                    errors.append(f"Image '{img}' in 'vi' not found in vi/ or missing/vi/")

        return errors

