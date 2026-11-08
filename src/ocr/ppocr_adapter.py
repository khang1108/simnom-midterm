import json
from typing import List, Dict, Any, Tuple

class PPOCRAdapter:
    """
    Adapter chuẩn hóa dữ liệu Bounding Box và Transcription theo chuẩn PPOCRLabel:
    - Đảm bảo mỗi Box có đúng 4 điểm tọa độ [[x1,y1], [x2,y2], [x3,y3], [x4,y4]].
    - Sắp xếp thứ tự Bounding Box theo chuẩn đọc:
      * Chữ Nôm (ch): Từ PHẢI sang TRÁI, từ TRÊN xuống DƯỚI (theo cột dọc).
      * Quốc ngữ (vi): Từ TRÊN xuống DƯỚI, từ TRÁI sang PHẢI (theo hàng ngang).
    - Tạo dòng cho Label.txt và fileState.txt.
    """

    @staticmethod
    def ensure_4_points(box_points: Any) -> List[List[int]]:
        """
        Quy đổi bất kỳ dạng bbox nào (rect [x,y,w,h] hoặc polygon) về đúng 4 điểm [4, 2].
        """
        if not box_points:
            return [[0, 0], [0, 0], [0, 0], [0, 0]]

        # Trường hợp dạng [x, y, w, h]
        if len(box_points) == 4 and isinstance(box_points[0], (int, float)):
            x, y, w, h = map(int, box_points)
            return [[x, y], [x + w, y], [x + w, y + h], [x, y + h]]

        # Trường hợp đã là danh sách các điểm [[x,y], ...]
        if isinstance(box_points, list) and len(box_points) >= 4:
            # Lấy đúng 4 điểm đầu tiên và ép kiểu int
            return [[int(pt[0]), int(pt[1])] for pt in box_points[:4]]

        return [[0, 0], [0, 0], [0, 0], [0, 0]]

    @staticmethod
    def sort_boxes_reading_order(boxes: List[Dict[str, Any]], script_type: str = "ch") -> List[Dict[str, Any]]:
        """
        Sắp xếp bounding boxes theo thứ tự đọc tự nhiên:
        - script_type == 'ch' (Hán Nôm): Cột từ Phải qua Trái (x giảm dần), trong cột từ Trên xuống Dưới (y tăng dần).
        - script_type == 'vi' (Quốc ngữ): Dòng từ Trên xuống Dưới (y tăng dần), trong dòng từ Trái qua Phải (x tăng dần).
        """
        if not boxes:
            return []

        def get_center(box):
            pts = box.get("points", [])
            if len(pts) >= 4:
                cx = sum(p[0] for p in pts) / 4.0
                cy = sum(p[1] for p in pts) / 4.0
                return cx, cy
            return 0.0, 0.0

        if script_type == "ch":
            # Chữ Nôm: Cột dọc (phải sang trái)
            # Gom các box có tọa độ x gần nhau thành 1 cột
            boxes_with_coord = [(b, get_center(b)) for b in boxes]
            
            # Ước lượng độ rộng trung bình của một cột
            widths = []
            for b in boxes:
                pts = b.get("points", [])
                if len(pts) >= 4:
                    widths.append(abs(pts[1][0] - pts[0][0]))
            col_thresh = (sum(widths) / len(widths) * 0.75) if widths else 30.0

            # Sắp xếp thô theo x giảm dần (phải sang trái)
            boxes_with_coord.sort(key=lambda item: item[1][0], reverse=True)

            columns: List[List[Tuple[Dict, Tuple[float, float]]]] = []
            for item in boxes_with_coord:
                b, (cx, cy) = item
                placed = False
                for col in columns:
                    col_avg_x = sum(c_item[1][0] for c_item in col) / len(col)
                    if abs(cx - col_avg_x) < col_thresh:
                        col.append(item)
                        placed = True
                        break
                if not placed:
                    columns.append([item])

            # Trong mỗi cột, sắp xếp từ trên xuống dưới (y tăng dần)
            sorted_boxes = []
            for col in columns:
                col.sort(key=lambda item: item[1][1]) # y tăng dần
                sorted_boxes.extend([item[0] for item in col])

            return sorted_boxes

        else:
            # Quốc ngữ: Hàng ngang (trên xuống dưới, trái sang phải)
            boxes_with_coord = [(b, get_center(b)) for b in boxes]

            heights = []
            for b in boxes:
                pts = b.get("points", [])
                if len(pts) >= 4:
                    heights.append(abs(pts[2][1] - pts[1][1]))
            line_thresh = (sum(heights) / len(heights) * 0.6) if heights else 20.0

            # Sắp xếp thô theo y tăng dần (trên xuống dưới)
            boxes_with_coord.sort(key=lambda item: item[1][1])

            lines: List[List[Tuple[Dict, Tuple[float, float]]]] = []
            for item in boxes_with_coord:
                b, (cx, cy) = item
                placed = False
                for line in lines:
                    line_avg_y = sum(l_item[1][1] for l_item in line) / len(line)
                    if abs(cy - line_avg_y) < line_thresh:
                        line.append(item)
                        placed = True
                        break
                if not placed:
                    lines.append([item])

            # Trong mỗi dòng, sắp xếp từ trái sang phải (x tăng dần)
            sorted_boxes = []
            for line in lines:
                line.sort(key=lambda item: item[1][0]) # x tăng dần
                sorted_boxes.extend([item[0] for item in line])

            return sorted_boxes

    @staticmethod
    def format_label_entry(folder_name: str, image_name: str, boxes: List[Dict[str, Any]], script_type: str = "ch") -> str:
        """
        Sinh một dòng dữ liệu cho Label.txt:
        <folderName>/<imageName>\t[{"transcription":"...", "points":[[x1,y1],[x2,y2],[x3,y3],[x4,y4]]}]
        """
        rel_path = f"{folder_name}/{image_name}"
        normalized_boxes = []

        for b in boxes:
            trans = str(b.get("transcription", "")).strip()
            pts = PPOCRAdapter.ensure_4_points(b.get("points", []))
            
            box_dict: Dict[str, Any] = {
                "transcription": trans,
                "points": pts
            }
            if "difficult" in b:
                box_dict["difficult"] = bool(b["difficult"])

            normalized_boxes.append(box_dict)

        # Sắp xếp theo thứ tự đọc
        sorted_boxes = PPOCRAdapter.sort_boxes_reading_order(normalized_boxes, script_type=script_type)
        json_str = json.dumps(sorted_boxes, ensure_ascii=False)
        return f"{rel_path}\t{json_str}\n"

    @staticmethod
    def format_state_entry(folder_name: str, image_name: str) -> str:
        """
        Sinh một dòng dữ liệu cho fileState.txt:
        <folderName>/<imageName>\t1
        """
        rel_path = f"{folder_name}/{image_name}"
        return f"{rel_path}\t1\n"

