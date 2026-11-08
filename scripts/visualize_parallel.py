import os
import sys
import json
import argparse
from pathlib import Path
from typing import List, Dict, Any, Tuple, Optional
from PIL import Image, ImageDraw, ImageFont

# Danh sách màu sắc tương phản nổi bật cho các cặp box
DISTINCT_COLORS = [
    "#9C27B0",  # Tím đậm
    "#009688",  # Xanh Teal
    "#FF9800",  # Cam
    "#2196F3",  # Xanh dương
    "#4CAF50",  # Xanh lá
    "#E91E63",  # Hồng đậm
    "#FF5722",  # Cam đỏ
    "#3F51B5",  # Chàm (Indigo)
    "#00BCD4",  # Cyan
    "#795548",  # Nâu
    "#673AB7",  # Deep Purple
    "#8BC34A",  # Light Green
    "#FFC107",  # Vàng hổ phách
    "#F44336",  # Đỏ
    "#607D8B",  # Xám xanh
    "#D81B60",  # Magenta
    "#00ACC1",  # Dark Cyan
    "#FB8C00",  # Dark Orange
    "#43A047",  # Dark Green
    "#1E88E5",  # Medium Blue
]

def hex_to_rgb(hex_code: str) -> Tuple[int, int, int]:
    hex_code = hex_code.lstrip("#")
    return tuple(int(hex_code[i : i + 2], 16) for i in (0, 2, 4))

def get_font(size: int = 20) -> ImageFont.ImageFont:
    """Tải font hệ thống hoặc dùng font mặc định của PIL."""
    candidates = [
        "/usr/share/fonts/liberation/LiberationSans-Bold.ttf",
        "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
        "/usr/share/fonts/gnu-free/FreeSansBold.otf",
        "/usr/share/fonts/truetype/liberation/LiberationSans-Bold.ttf"
    ]
    for font_p in candidates:
        if os.path.exists(font_p):
            try:
                return ImageFont.truetype(font_p, size)
            except Exception:
                pass
    return ImageFont.load_default()

def draw_boxes_on_image(
    image: Image.Image,
    boxes: List[Dict[str, Any]],
    scale_factor: float = 1.0,
    line_thickness: int = 4,
    font_size: int = 24
) -> Image.Image:
    """
    Vẽ các bounding box lên hình ảnh kèm theo badge số thứ tự có màu sắc tương ứng.
    """
    img_draw = image.copy()
    draw = ImageDraw.Draw(img_draw)
    font = get_font(font_size)

    for idx, b in enumerate(boxes, start=1):
        color_hex = DISTINCT_COLORS[(idx - 1) % len(DISTINCT_COLORS)]
        rgb_color = hex_to_rgb(color_hex)
        pts = b.get("points", [])
        if len(pts) < 4:
            continue

        # Scale tọa độ theo kích thước ảnh hiển thị
        scaled_pts = [(int(p[0] * scale_factor), int(p[1] * scale_factor)) for p in pts[:4]]
        
        # 1. Vẽ viền Bounding Box
        polygon = scaled_pts + [scaled_pts[0]]
        draw.line(polygon, fill=rgb_color, width=line_thickness)

        # 2. Tọa độ đặt Badge số (lấy góc trên-trái hoặc điểm cao nhất)
        xs = [p[0] for p in scaled_pts]
        ys = [p[1] for p in scaled_pts]
        min_x, min_y = min(xs), min(ys)

        badge_text = str(idx)
        # Tính kích thước văn bản badge
        bbox_text = font.getbbox(badge_text)
        text_w = bbox_text[2] - bbox_text[0]
        text_h = bbox_text[3] - bbox_text[1]

        pad_x = 6
        pad_y = 3
        badge_w = text_w + pad_x * 2
        badge_h = text_h + pad_y * 2

        # Đặt badge ở góc trên bên trái của box
        badge_x0 = max(0, min_x)
        badge_y0 = max(0, min_y - badge_h + 2)
        badge_x1 = badge_x0 + badge_w
        badge_y1 = badge_y0 + badge_h

        # Vẽ hình chữ nhật nền của badge
        draw.rectangle([badge_x0, badge_y0, badge_x1, badge_y1], fill=rgb_color)
        
        # Vẽ chữ số màu trắng bên trong badge
        text_x = badge_x0 + pad_x - bbox_text[0]
        text_y = badge_y0 + pad_y - bbox_text[1]
        draw.text((text_x, text_y), badge_text, fill=(255, 255, 255), font=font)

    return img_draw

def render_side_by_side(
    ch_img_path: str,
    vi_img_path: str,
    ch_boxes: List[Dict[str, Any]],
    vi_boxes: List[Dict[str, Any]],
    output_path: str,
    target_height: int = 1800,
    separator_width: int = 40
):
    """
    Ghép hai trang Hán Nôm (Trái) và Quốc ngữ (Phải) cạnh nhau, 
    vẽ bounding box đồng bộ màu và số thứ tự, xuất ra file ảnh.
    """
    ch_img_raw = Image.open(ch_img_path).convert("RGB")
    vi_img_raw = Image.open(vi_img_path).convert("RGB")

    # Scale cả 2 ảnh về cùng chiều cao target_height để hiển thị cân đối
    ch_scale = target_height / float(ch_img_raw.height)
    ch_target_w = int(ch_img_raw.width * ch_scale)
    ch_resized = ch_img_raw.resize((ch_target_w, target_height), Image.Resampling.LANCZOS)

    vi_scale = target_height / float(vi_img_raw.height)
    vi_target_w = int(vi_img_raw.width * vi_scale)
    vi_resized = vi_img_raw.resize((vi_target_w, target_height), Image.Resampling.LANCZOS)

    # Vẽ box lên từng trang
    line_thickness = max(3, int(target_height / 500))
    font_size = max(18, int(target_height / 85))

    ch_annotated = draw_boxes_on_image(
        ch_resized, ch_boxes, scale_factor=ch_scale, 
        line_thickness=line_thickness, font_size=font_size
    )
    vi_annotated = draw_boxes_on_image(
        vi_resized, vi_boxes, scale_factor=vi_scale, 
        line_thickness=line_thickness, font_size=font_size
    )

    # Ghép 2 ảnh vào canvas chung
    total_w = ch_target_w + separator_width + vi_target_w
    canvas = Image.new("RGB", (total_w, target_height), color=(240, 240, 240)) # Nền ngăn cách xám sáng

    canvas.paste(ch_annotated, (0, 0))
    canvas.paste(vi_annotated, (ch_target_w + separator_width, 0))

    # Lưu ảnh kết quả
    os.makedirs(os.path.dirname(os.path.abspath(output_path)), exist_ok=True)
    canvas.save(output_path, quality=95)
    print(f"[Visualizer] Đã xuất ảnh song ngữ thành công tại: {output_path} ({total_w}x{target_height})")

def extract_boxes_from_label(label_file: str, img_name: str) -> List[Dict[str, Any]]:
    """Trích xuất bounding boxes của một ảnh từ file Label.txt PPOCR."""
    if not os.path.exists(label_file):
        return []
    with open(label_file, "r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line or "\t" not in line:
                continue
            parts = line.split("\t", 1)
            if os.path.basename(parts[0]) == img_name:
                try:
                    return json.loads(parts[1])
                except Exception:
                    return []
    return []

def main():
    parser = argparse.ArgumentParser(description="Side-by-side Dual Page Bounding Box Visualizer.")
    parser.add_argument("--ch-img", type=str, required=True, help="Đường dẫn ảnh trang Hán Nôm")
    parser.add_argument("--vi-img", type=str, required=True, help="Đường dẫn ảnh trang Quốc ngữ")
    parser.add_argument("--ch-label", type=str, default=None, help="File Label.txt chứa box Hán Nôm")
    parser.add_argument("--vi-label", type=str, default=None, help="File Label.txt chứa box Quốc ngữ")
    parser.add_argument("--output", type=str, default="output/visualizations/side_by_side.jpg", help="Đường dẫn ảnh xuất ra")
    parser.add_argument("--height", type=int, default=1800, help="Chiều cao ảnh xuất (mặc định 1800px)")

    args = parser.parse_args()

    # Tải boxes
    ch_img_name = os.path.basename(args.ch_img)
    vi_img_name = os.path.basename(args.vi_img)

    ch_label_path = args.ch_label or os.path.join(os.path.dirname(args.ch_img), "Label.txt")
    vi_label_path = args.vi_label or os.path.join(os.path.dirname(args.vi_img), "Label.txt")

    ch_boxes = extract_boxes_from_label(ch_label_path, ch_img_name)
    vi_boxes = extract_boxes_from_label(vi_label_path, vi_img_name)

    print(f"Trang Hán Nôm: {ch_img_name} ({len(ch_boxes)} boxes)")
    print(f"Trang Quốc ngữ: {vi_img_name} ({len(vi_boxes)} boxes)")

    render_side_by_side(
        ch_img_path=args.ch_img,
        vi_img_path=args.vi_img,
        ch_boxes=ch_boxes,
        vi_boxes=vi_boxes,
        output_path=args.output,
        target_height=args.height
    )

if __name__ == "__main__":
    main()
