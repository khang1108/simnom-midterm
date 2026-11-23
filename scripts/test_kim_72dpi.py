import difflib
import json
import sys
from pathlib import Path
from PIL import Image, ImageDraw, ImageFont

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from src.aligner.book_aligner import BookAligner
from src.ocr.engine import OCREngine
from src.ocr.ppocr_adapter import PPOCRAdapter


def make_pua_crops_sheet(
    img_path: Path,
    sorted_boxes,
    target_codepoints=(0xF047C, 0xF082E),
    max_per_cp: int = 3,
    out_path: Path = Path("output/ocr_benchmark/pua_crops_587.jpg"),
) -> None:
    """Cắt ảnh quanh các chữ PUA trên trang 587 để kiểm chứng trực quan tự hình."""
    img = Image.open(img_path).convert("RGB")
    w, h = img.size
    crops = []

    for cp in target_codepoints:
        ch_target = chr(cp)
        found = 0
        for col_idx, b in enumerate(sorted_boxes, 1):
            trans = b.get("transcription", "")
            if ch_target not in trans:
                continue
            pts = b["points"]
            x1, x2 = min(p[0] for p in pts), max(p[0] for p in pts)
            y1, y2 = min(p[1] for p in pts), max(p[1] for p in pts)
            k = max(1, len(trans))
            char_h = (y2 - y1) / float(k)

            for pos_idx, c in enumerate(trans):
                if c != ch_target:
                    continue
                cy1 = y1 + pos_idx * char_h
                cy2 = y1 + (pos_idx + 1) * char_h
                # Cắt kèm +/- 1 chữ trên dưới làm ngữ cảnh
                pad_x = max(18, int((x2 - x1) * 0.45))
                pad_y = max(35, int(char_h * 1.1))
                cx1 = max(0, int(x1 - pad_x))
                cx2 = min(w, int(x2 + pad_x))
                py1 = max(0, int(cy1 - pad_y))
                py2 = min(h, int(cy2 + pad_y))

                patch = img.crop((cx1, py1, cx2, py2)).copy()
                # Vẽ khung đỏ đánh dấu chữ PUA ở giữa patch
                pdraw = ImageDraw.Draw(patch)
                pdraw.rectangle(
                    [int(x1 - cx1), int(cy1 - py1), int(x2 - cx1), int(cy2 - py1)],
                    outline=(220, 20, 20),
                    width=2,
                )
                ctx_left = max(0, pos_idx - 2)
                ctx_right = min(len(trans), pos_idx + 3)
                ctx_str = trans[ctx_left:ctx_right].replace(ch_target, "[?]")
                crops.append((f"U+{cp:05X} col={col_idx} pos={pos_idx} ctx={ctx_str}", patch))
                found += 1
                if found >= max_per_cp:
                    break
            if found >= max_per_cp:
                break

    if not crops:
        print("No PUA crops found on", img_path)
        return

    tile_w, tile_h, hdr_h, pad = 220, 320, 34, 12
    cols = len(crops)
    canvas = Image.new("RGB", (cols * tile_w + (cols + 1) * pad, tile_h + hdr_h + 2 * pad), (240, 240, 240))
    draw = ImageDraw.Draw(canvas)
    for i, (label, patch) in enumerate(crops):
        x0 = pad + i * (tile_w + pad)
        y0 = pad
        draw.rectangle([x0, y0, x0 + tile_w, y0 + hdr_h], fill=(33, 37, 41))
        draw.text((x0 + 6, y0 + 10), label[:30], fill=(255, 255, 255))
        scale = min(tile_w / float(patch.width), tile_h / float(patch.height))
        rw, rh = max(1, int(patch.width * scale)), max(1, int(patch.height * scale))
        resized = patch.resize((rw, rh), Image.Resampling.LANCZOS)
        canvas.paste(resized, (x0 + (tile_w - rw) // 2, y0 + hdr_h + (tile_h - rh) // 2))

    out_path.parent.mkdir(parents=True, exist_ok=True)
    canvas.save(out_path, quality=92)
    print(f"Saved PUA inspection crops -> {out_path}")


def main():
    img_72 = Path(
        "data/processed/T1_Sách Dạy Đấng Làm Người Sửa Mình (Tập 1)/ch/"
        "T1_Sách Dạy Đấng Làm Người Sửa Mình (Tập 1).587.jpg"
    )
    ref_label_path = Path("output/align_v24/clean_book/ch/Label.txt")

    engine = OCREngine()
    raw_boxes_72 = engine.recognize(img_72, script="ch")
    body_72 = PPOCRAdapter.sort_boxes_reading_order(
        BookAligner.filter_body_boxes(raw_boxes_72, script_type="ch"),
        script_type="ch",
    )
    text_72 = "".join(
        PPOCRAdapter.clean_transcription(b.get("transcription", "")) for b in body_72
    )

    ref_boxes = []
    for line in ref_label_path.read_text(encoding="utf-8").splitlines():
        if "587.jpg" in line:
            _, raw_json = line.split("\t", 1)
            ref_boxes = json.loads(raw_json)
            break
    text_300 = "".join(
        PPOCRAdapter.clean_transcription(b.get("transcription", "")) for b in ref_boxes
    )

    ratio = difflib.SequenceMatcher(None, text_300, text_72).ratio()
    print(f"Kim 72 DPI boxes: raw={len(raw_boxes_72)}, body={len(body_72)}, chars={len(text_72)}")
    print(f"Kim 300 DPI ref : body={len(ref_boxes)}, chars={len(text_300)}")
    print(f"Character agreement ratio (300 DPI vs 72 DPI): {ratio * 100:.2f}%")

    # In các khác biệt cụ thể nếu có
    sm = difflib.SequenceMatcher(None, text_300, text_72)
    diffs = []
    for tag, i1, i2, j1, j2 in sm.get_opcodes():
        if tag != "equal":
            diffs.append((tag, text_300[i1:i2], text_72[j1:j2]))
    print(f"Exact diffs count: {len(diffs)} -> {diffs}")

    out_dir = Path("output/ocr_benchmark")
    out_dir.mkdir(parents=True, exist_ok=True)
    (out_dir / "kim_72dpi_587.json").write_text(
        json.dumps(
            {
                "raw_boxes": raw_boxes_72,
                "body_boxes": body_72,
                "text_72": text_72,
                "text_300": text_300,
                "ratio": ratio,
                "diffs": diffs,
            },
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )

    make_pua_crops_sheet(img_72, body_72, out_path=out_dir / "pua_crops_587.jpg")


if __name__ == "__main__":
    main()
