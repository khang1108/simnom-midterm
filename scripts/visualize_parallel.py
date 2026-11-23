import os
import sys
import json
import re
import argparse
from pathlib import Path
from typing import List, Dict, Any, Tuple, Optional
from PIL import Image, ImageDraw, ImageFont
import pandas as pd

DISTINCT_COLORS = [
    "#9C27B0",  # 1: Magenta / Violet
    "#00BCD4",  # 2: Cyan
    "#FB8C00",  # 3: Amber / Orange
    "#1E88E5",  # 4: Blue
    "#43A047",  # 5: Green
    "#E91E63",  # 6: Pink
    "#8D6E63",  # 7: Brown
    "#3949AB",  # 8: Indigo
    "#00897B",  # 9: Teal
    "#D81B60",  # 10: Deep Rose
    "#7E57C2",  # 11: Deep Purple
    "#F4511E",  # 12: Deep Orange
    "#00ACC1",  # 13: Light Blue
    "#7CB342",  # 14: Light Green
    "#C0CA33",  # 15: Lime
]

def hex_to_rgb(hex_code: str) -> Tuple[int, int, int]:
    hex_code = hex_code.lstrip("#")
    return tuple(int(hex_code[i : i + 2], 16) for i in (0, 2, 4))

def get_font(size: int = 24) -> ImageFont.ImageFont:
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

def extract_boxes_from_label(label_file: str, img_name: str) -> List[Dict[str, Any]]:
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

def render_sentence_aligned_pair(
    ch_img_path: str,
    vi_img_path: str,
    csv_path: str,
    ch_label_path: str,
    vi_label_path: str,
    output_path: str,
    target_height: int = 2000,
    separator_width: int = 40
):
    """
    Tạo ảnh trực quan hóa dóng hàng song ngữ (Sentence-Aligned Bounding Box Visualization):
    - Đóng box từng chữ Hán Nôm và từng từ Quốc ngữ.
    - Tô màu đồng bộ theo từng câu (cùng câu = cùng màu viền).
    - Gắn badge số thứ tự câu ([1], [2], [3]...) ở từ/chữ bắt đầu của câu tương ứng.
    """
    ch_filename = os.path.basename(ch_img_path)
    vi_filename = os.path.basename(vi_img_path)

    df = pd.read_csv(csv_path)
    page_df = df[df["img_id"] == ch_filename].copy()
    if page_df.empty:
        # Thử tìm theo img_id không có tiền tố
        page_df = df[df["img_id"].str.contains(Path(ch_filename).stem)].copy()

    ch_boxes = extract_boxes_from_label(ch_label_path, ch_filename)
    vi_boxes = extract_boxes_from_label(vi_label_path, vi_filename)

    # 1. Tách dòng Quốc ngữ thành từng từ
    vi_words = []
    for b in vi_boxes:
        txt = b.get("transcription", "").strip()
        pts = b.get("points", [])
        if not txt or txt.startswith("-") or len(pts) < 4:
            continue
        words = txt.split()
        if not words:
            continue
        x1, x2 = min(p[0] for p in pts), max(p[0] for p in pts)
        y1, y2 = min(p[1] for p in pts), max(p[1] for p in pts)
        total_w = sum(len(w) for w in words) + (len(words) - 1) * 0.4
        curr_x = x1
        for w in words:
            w_len = int((x2 - x1) * (len(w) + 0.3) / total_w)
            wx1 = curr_x
            wx2 = min(x2, curr_x + w_len)
            vi_words.append({
                "word": w,
                "box": [wx1, y1, wx2, y2]
            })
            curr_x = wx2 + int((x2 - x1) * 0.15 / total_w)

    # 2. Tách cột Hán Nôm thành từng chữ (từ phải sang trái)
    ch_cols = []
    for b in ch_boxes:
        txt = b.get("transcription", "").strip()
        pts = b.get("points", [])
        if len(txt) <= 2 or len(pts) < 4:
            continue
        x_center = sum(p[0] for p in pts) / 4.0
        ch_cols.append((x_center, txt, pts))
    ch_cols.sort(key=lambda c: -c[0])  # Phải sang trái

    ch_chars = []
    for xc, txt, pts in ch_cols:
        x1, x2 = min(p[0] for p in pts), max(p[0] for p in pts)
        y1, y2 = min(p[1] for p in pts), max(p[1] for p in pts)
        k = len(txt)
        char_h = (y2 - y1) / float(k)
        for j, ch in enumerate(txt):
            cy1 = int(y1 + j * char_h)
            cy2 = int(y1 + (j + 1) * char_h)
            ch_chars.append({
                "char": ch,
                "box": [x1, cy1, x2, cy2]
            })

    # 3. Ánh xạ các câu song ngữ vào words/chars
    sent_list = []
    for _, row in page_df.iterrows():
        sid = row["sentence_id"]
        num_match = re.search(r"\.(\d+)$", str(sid))
        sent_num = int(num_match.group(1)) if num_match else len(sent_list) + 1
        v_words = row["vi_txt"].split()
        c_chars = [c for c in row["ch_txt"] if not re.match(r"[\s\d.,;!?()]+", c)]
        sent_list.append({
            "num": sent_num,
            "vi_word_count": len(v_words),
            "ch_char_count": len(c_chars)
        })

    # Gán từ Quốc ngữ theo câu
    curr_s_idx = 0
    words_in_curr_sent = 0
    for i, w_obj in enumerate(vi_words):
        if curr_s_idx < len(sent_list):
            s_target = sent_list[curr_s_idx]
            w_obj["sent_num"] = s_target["num"]
            w_obj["color_idx"] = curr_s_idx
            w_obj["is_start"] = (words_in_curr_sent == 0)
            words_in_curr_sent += 1
            if words_in_curr_sent >= s_target["vi_word_count"] and curr_s_idx < len(sent_list) - 1:
                curr_s_idx += 1
                words_in_curr_sent = 0
        else:
            w_obj["sent_num"] = sent_list[-1]["num"] if sent_list else 1
            w_obj["color_idx"] = max(0, len(sent_list) - 1)
            w_obj["is_start"] = False

    # Gán chữ Hán Nôm theo câu
    curr_s_idx = 0
    chars_in_curr_sent = 0
    for i, c_obj in enumerate(ch_chars):
        if curr_s_idx < len(sent_list):
            s_target = sent_list[curr_s_idx]
            c_obj["sent_num"] = s_target["num"]
            c_obj["color_idx"] = curr_s_idx
            c_obj["is_start"] = (chars_in_curr_sent == 0)
            chars_in_curr_sent += 1
            if chars_in_curr_sent >= s_target["ch_char_count"] and curr_s_idx < len(sent_list) - 1:
                curr_s_idx += 1
                chars_in_curr_sent = 0
        else:
            c_obj["sent_num"] = sent_list[-1]["num"] if sent_list else 1
            c_obj["color_idx"] = max(0, len(sent_list) - 1)
            c_obj["is_start"] = False

    # 4. Vẽ ảnh
    ch_raw = Image.open(ch_img_path).convert("RGB")
    vi_raw = Image.open(vi_img_path).convert("RGB")

    ch_scale = target_height / float(ch_raw.height)
    ch_w = int(ch_raw.width * ch_scale)
    ch_img = ch_raw.resize((ch_w, target_height), Image.Resampling.LANCZOS)

    vi_scale = target_height / float(vi_raw.height)
    vi_w = int(vi_raw.width * vi_scale)
    vi_img = vi_raw.resize((vi_w, target_height), Image.Resampling.LANCZOS)

    ch_draw = ImageDraw.Draw(ch_img)
    vi_draw = ImageDraw.Draw(vi_img)
    font = get_font(int(target_height / 85))

    # Vẽ chữ Hán Nôm
    for c_obj in ch_chars:
        b = c_obj["box"]
        c_idx = c_obj["color_idx"]
        rgb = hex_to_rgb(DISTINCT_COLORS[c_idx % len(DISTINCT_COLORS)])
        sx1, sy1 = int(b[0] * ch_scale), int(b[1] * ch_scale)
        sx2, sy2 = int(b[2] * ch_scale), int(b[3] * ch_scale)
        ch_draw.rectangle([sx1, sy1, sx2, sy2], outline=rgb, width=2)
        if c_obj["is_start"]:
            badge = str(c_obj["sent_num"])
            bbox = font.getbbox(badge)
            bw = (bbox[2] - bbox[0]) + 8
            bh = (bbox[3] - bbox[1]) + 4
            bx0 = max(0, sx1)
            by0 = max(0, sy1 - bh)
            ch_draw.rectangle([bx0, by0, bx0 + bw, by0 + bh], fill=rgb)
            ch_draw.text((bx0 + 4 - bbox[0], by0 + 2 - bbox[1]), badge, fill=(255, 255, 255), font=font)

    # Vẽ từ Quốc ngữ
    for w_obj in vi_words:
        b = w_obj["box"]
        c_idx = w_obj["color_idx"]
        rgb = hex_to_rgb(DISTINCT_COLORS[c_idx % len(DISTINCT_COLORS)])
        sx1, sy1 = int(b[0] * vi_scale), int(b[1] * vi_scale)
        sx2, sy2 = int(b[2] * vi_scale), int(b[3] * vi_scale)
        vi_draw.rectangle([sx1, sy1, sx2, sy2], outline=rgb, width=2)
        if w_obj["is_start"]:
            badge = str(w_obj["sent_num"])
            bbox = font.getbbox(badge)
            bw = (bbox[2] - bbox[0]) + 8
            bh = (bbox[3] - bbox[1]) + 4
            bx0 = max(0, sx1)
            by0 = max(0, sy1 - bh)
            vi_draw.rectangle([bx0, by0, bx0 + bw, by0 + bh], fill=rgb)
            vi_draw.text((bx0 + 4 - bbox[0], by0 + 2 - bbox[1]), badge, fill=(255, 255, 255), font=font)

    # Ghép 2 trang thành ảnh lớn
    total_w = ch_w + separator_width + vi_w
    canvas = Image.new("RGB", (total_w, target_height), color=(245, 245, 245))
    canvas.paste(ch_img, (0, 0))
    canvas.paste(vi_img, (ch_w + separator_width, 0))

    os.makedirs(os.path.dirname(os.path.abspath(output_path)), exist_ok=True)
    canvas.save(output_path, quality=95)
    print(f"[Visualizer] Đã xuất ảnh dóng hàng song ngữ thành công: {output_path} ({total_w}x{target_height})")

def main():
    parser = argparse.ArgumentParser(description="Side-by-side Dual Page Bounding Box Visualizer.")
    parser.add_argument("--ch-img", type=str, required=True, help="Đường dẫn ảnh trang Hán Nôm")
    parser.add_argument("--vi-img", type=str, required=True, help="Đường dẫn ảnh trang Quốc ngữ")
    parser.add_argument("--csv", type=str, default=None, help="File dóng hàng .csv (nếu có để trực quan hóa theo từng câu)")
    parser.add_argument("--ch-label", type=str, default=None, help="File Label.txt chứa box Hán Nôm")
    parser.add_argument("--vi-label", type=str, default=None, help="File Label.txt chứa box Quốc ngữ")
    parser.add_argument("--output", type=str, default="output/visualizations/side_by_side.jpg", help="Đường dẫn ảnh xuất ra")
    parser.add_argument("--height", type=int, default=2000, help="Chiều cao ảnh xuất (mặc định 2000px)")

    args = parser.parse_args()

    ch_label_path = args.ch_label or os.path.join(os.path.dirname(args.ch_img), "Label.txt")
    vi_label_path = args.vi_label or os.path.join(os.path.dirname(args.vi_img), "Label.txt")

    # Tự động dò file CSV nếu không truyền
    csv_file = args.csv
    if not csv_file:
        candidate_csv = os.path.join(os.path.dirname(os.path.dirname(args.ch_img)), "T1_Bao_Cao_Tien_Do.csv")
        if os.path.exists(candidate_csv):
            csv_file = candidate_csv

    if csv_file and os.path.exists(csv_file):
        render_sentence_aligned_pair(
            ch_img_path=args.ch_img,
            vi_img_path=args.vi_img,
            csv_path=csv_file,
            ch_label_path=ch_label_path,
            vi_label_path=vi_label_path,
            output_path=args.output,
            target_height=args.height
        )
    else:
        print("[Visualizer] Không tìm thấy CSV, vui lòng truyền --csv để xuất ảnh dóng hàng theo câu.")

if __name__ == "__main__":
    main()