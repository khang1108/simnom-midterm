import argparse
import json
import math
import os
import re
import subprocess
import tempfile
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

import cv2
import numpy as np
from PIL import Image, ImageDraw, ImageFont


TYPE_BANNER_COLORS = {
    "vi_like": (21, 101, 192),       # Xanh dương
    "ch_like": (46, 125, 50),        # Xanh lá
    "blank": (183, 28, 28),          # Đỏ đậm
    "sparse": (230, 81, 0),          # Cam đậm
    "cover_or_color": (106, 27, 154),# Tím
    "landscape": (0, 0, 0),          # Đen
}


def get_font(size: int = 16) -> ImageFont.ImageFont:
    for fp in (
        "/usr/share/fonts/liberation/LiberationSans-Bold.ttf",
        "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
        "/usr/share/fonts/gnu-free/FreeSansBold.otf",
    ):
        if os.path.exists(fp):
            try:
                return ImageFont.truetype(fp, size)
            except Exception:
                pass
    return ImageFont.load_default()


def get_pdf_page_count(pdf_path: Path) -> int:
    proc = subprocess.run(["pdfinfo", str(pdf_path)], capture_output=True, text=True, check=True)
    m = re.search(r"Pages:\s+(\d+)", proc.stdout)
    if not m:
        raise RuntimeError(f"Không đọc được số trang từ pdfinfo: {pdf_path}")
    return int(m.group(1))


def classify_page_metrics(img_bgr: np.ndarray) -> Dict[str, Any]:
    h, w = img_bgr.shape[:2]
    is_landscape = w > h

    gray = cv2.cvtColor(img_bgr, cv2.COLOR_BGR2GRAY)
    y8a, y8b = int(h * 0.08), int(h * 0.92)
    x8a, x8b = int(w * 0.08), int(w * 0.92)
    c8_gray = gray[y8a:y8b, x8a:x8b]
    ink_ratio = float(np.mean(c8_gray < 185))

    c8_bgr = img_bgr[y8a:y8b, x8a:x8b].astype(np.int16)
    color_score = float(np.mean(np.max(c8_bgr, axis=2) - np.min(c8_bgr, axis=2)))

    y15a, y15b = int(h * 0.15), int(h * 0.85)
    x15a, x15b = int(w * 0.15), int(w * 0.85)
    c15_ink = (gray[y15a:y15b, x15a:x15b] < 185).astype(np.float32)
    var_row = float(np.var(np.mean(c15_ink, axis=1)))
    var_col = float(np.var(np.mean(c15_ink, axis=0)))
    hv_ratio = var_row / (var_col + 1e-6)

    if color_score > 12.0:
        page_type = "cover_or_color"
    elif ink_ratio < 0.005:
        page_type = "blank"
    elif ink_ratio < 0.025:
        page_type = "sparse"
    elif hv_ratio >= 1.2:
        page_type = "vi_like"
    else:
        page_type = "ch_like"

    return {
        "width": int(w),
        "height": int(h),
        "is_landscape": is_landscape,
        "ink_ratio": round(ink_ratio, 5),
        "color_score": round(color_score, 2),
        "hv_ratio": round(hv_ratio, 3),
        "type": page_type,
    }


def extract_page_num_from_pdf(
    pdf_path: Path, page_no: int, cache: Dict[int, Dict[str, Any]], tmp_dir: Path
) -> Dict[str, Any]:
    if page_no in cache:
        return cache[page_no]

    prefix = tmp_dir / f"hdr_{page_no:04d}"
    subprocess.run(
        ["pdftoppm", "-jpeg", "-r", "120", "-f", str(page_no), "-l", str(page_no), str(pdf_path), str(prefix)],
        check=True,
        capture_output=True,
    )
    rendered = sorted(tmp_dir.glob(f"hdr_{page_no:04d}*.jpg"))
    if not rendered:
        res = {"page": page_no, "raw_header": "", "vi_num": None, "ch_hint": None}
        cache[page_no] = res
        return res

    img = cv2.imread(str(rendered[0]), cv2.IMREAD_GRAYSCALE)
    rendered[0].unlink(missing_ok=True)
    h, w = img.shape
    crop = img[0 : int(h * 0.17), int(w * 0.08) : int(w * 0.92)]
    crop_path = tmp_dir / f"crop_{page_no:04d}.png"
    cv2.imwrite(str(crop_path), crop)

    env = {**os.environ, "TESSDATA_PREFIX": "data/tessdata"}
    proc = subprocess.run(
        ["tesseract", str(crop_path), "stdout", "-l", "vie", "--psm", "6"],
        capture_output=True,
        text=True,
        env=env,
    )
    crop_path.unlink(missing_ok=True)
    raw = " ".join(proc.stdout.strip().split())

    # Phân tích số trang Quốc ngữ kiểu "- 48 - ( 589 )" hoặc "- 48 -"
    vi_num = None
    ch_hint = None
    m = re.search(r"[-–—=]\s*(\d{1,4})\s*[-–—=]", raw)
    if m:
        vi_num = int(m.group(1))
    else:
        # Thử bắt số trước dấu ngoặc (589) nếu thiếu gạch nối
        m2 = re.search(r"\b(\d{1,4})\b\s*[\(\[]\s*(\d{1,4})\s*[\)\]]", raw)
        if m2:
            vi_num = int(m2.group(1))
            ch_hint = int(m2.group(2))
        else:
            # Nếu chỉ có số ở dòng tiêu đề ngắn (vd mục lục "III" / "48")
            m3 = re.fullmatch(r"[-–—\s]*(\d{1,4})[-–—\s]*", raw)
            if m3:
                vi_num = int(m3.group(1))

    if ch_hint is None:
        mc = re.search(r"[\(\[]\s*(\d{1,4})\s*[\)\]]", raw)
        if mc:
            ch_hint = int(mc.group(1))

    res = {"page": page_no, "raw_header": raw, "vi_num": vi_num, "ch_hint": ch_hint}
    cache[page_no] = res
    return res


def check_vi_numbering_continuity(
    pdf_path: Path, vi_pages: List[int], all_pages_info: List[Dict[str, Any]]
) -> Dict[str, Any]:
    if not vi_pages:
        return {"checkpoints": [], "jumps": []}

    sample_set = set(vi_pages[:3] + vi_pages[-3:] + vi_pages[::20])
    sample_pages = sorted(sample_set)
    cache: Dict[int, Dict[str, Any]] = {}
    jumps: List[Dict[str, Any]] = []

    with tempfile.TemporaryDirectory() as tmp:
        tmp_dir = Path(tmp)
        resolved = []
        for p in sample_pages:
            info = extract_page_num_from_pdf(pdf_path, p, cache, tmp_dir)
            if info["vi_num"] is not None:
                resolved.append(info)

        def bisect_jump(left: Dict[str, Any], right: Dict[str, Any]) -> None:
            p1, n1 = left["page"], left["vi_num"]
            p2, n2 = right["page"], right["vi_num"]
            if (n2 - n1) == (p2 - p1):
                return
            if p2 - p1 <= 1:
                jumps.append({
                    "from_pdf_page": p1,
                    "from_printed_num": n1,
                    "to_pdf_page": p2,
                    "to_printed_num": n2,
                    "pdf_delta": p2 - p1,
                    "printed_delta": n2 - n1,
                    "between_types": [all_pages_info[p - 1]["type"] for p in range(p1, p2 + 1)],
                })
                return

            # Tìm trang vi_like gần trung điểm nhất; nếu không có thì bisect toàn đoạn p1..p2
            mid_candidates = [p for p in range(p1 + 1, p2) if all_pages_info[p - 1]["type"] == "vi_like"]
            mid_p = mid_candidates[len(mid_candidates) // 2] if mid_candidates else (p1 + p2) // 2
            mid_info = extract_page_num_from_pdf(pdf_path, mid_p, cache, tmp_dir)
            if mid_info["vi_num"] is None:
                # Nếu OCR hụt ở mid, dò xung quanh trong đoạn
                found = None
                for delta in (1, -1, 2, -2):
                    cand = mid_p + delta
                    if p1 < cand < p2:
                        probe = extract_page_num_from_pdf(pdf_path, cand, cache, tmp_dir)
                        if probe["vi_num"] is not None:
                            found = probe
                            break
                if found is None:
                    jumps.append({
                        "from_pdf_page": p1,
                        "from_printed_num": n1,
                        "to_pdf_page": p2,
                        "to_printed_num": n2,
                        "pdf_delta": p2 - p1,
                        "printed_delta": n2 - n1,
                        "note": f"unparsed_mid_{mid_p}",
                        "between_types": [all_pages_info[p - 1]["type"] for p in range(p1, p2 + 1)],
                    })
                    return
                mid_info = found
            bisect_jump(left, mid_info)
            bisect_jump(mid_info, right)

        for i in range(len(resolved) - 1):
            a, b = resolved[i], resolved[i + 1]
            if (b["vi_num"] - a["vi_num"]) != (b["page"] - a["page"]):
                bisect_jump(a, b)

    all_checked = sorted(cache.values(), key=lambda x: x["page"])
    return {
        "checkpoints": [r for r in all_checked if r["vi_num"] is not None],
        "jumps": jumps,
    }


def render_contact_sheet(
    page_items: List[Tuple[int, Path, Dict[str, Any]]],
    out_path: Path,
    cols: int = 5,
    tile_w: int = 300,
    tile_h: int = 425,
) -> None:
    if not page_items:
        return
    banner_h = 34
    cell_h = tile_h + banner_h
    pad = 12
    rows = math.ceil(len(page_items) / cols)
    canvas_w = cols * tile_w + (cols + 1) * pad
    canvas_h = rows * cell_h + (rows + 1) * pad
    canvas = Image.new("RGB", (canvas_w, canvas_h), (235, 235, 235))
    draw = ImageDraw.Draw(canvas)
    font = get_font(15)

    for idx, (page_no, img_path, meta) in enumerate(page_items):
        r = idx // cols
        c = idx % cols
        x0 = pad + c * (tile_w + pad)
        y0 = pad + r * (cell_h + pad)

        ptype = meta["type"]
        banner_color = TYPE_BANNER_COLORS["landscape"] if meta["is_landscape"] else TYPE_BANNER_COLORS.get(ptype, (80, 80, 80))
        draw.rectangle([x0, y0, x0 + tile_w, y0 + banner_h], fill=banner_color)
        ink_pct = meta["ink_ratio"] * 100.0
        tag = f"p.{page_no:03d} | {ptype} | ink={ink_pct:.1f}%"
        if meta["is_landscape"]:
            tag = f"p.{page_no:03d} | LANDSCAPE | {ptype}"
        draw.text((x0 + 8, y0 + 8), tag, fill=(255, 255, 255), font=font)

        with Image.open(img_path) as im:
            thumb = im.convert("RGB").resize((tile_w, tile_h), Image.Resampling.LANCZOS)
            canvas.paste(thumb, (x0, y0 + banner_h))
        draw.rectangle([x0, y0, x0 + tile_w, y0 + cell_h], outline=(140, 140, 140), width=1)

    out_path.parent.mkdir(parents=True, exist_ok=True)
    canvas.save(out_path, quality=90)


def render_sample_pairs_sheet(
    pdf_path: Path,
    vi_pages: List[int],
    ch_pages_desc: List[int],
    out_path: Path,
) -> List[Dict[str, int]]:
    if not vi_pages or not ch_pages_desc:
        return []

    n_pairs = min(len(vi_pages), len(ch_pages_desc))
    if n_pairs <= 5:
        idxs = list(range(n_pairs))
    else:
        idxs = [0, n_pairs // 4, n_pairs // 2, (3 * n_pairs) // 4, n_pairs - 1]
        idxs = list(dict.fromkeys(idxs))

    selected = [(vi_pages[i], ch_pages_desc[i]) for i in idxs]
    row_h = 850
    sep = 24
    hdr_h = 36

    rows_imgs = []
    font = get_font(20)
    with tempfile.TemporaryDirectory() as tmp:
        tmp_dir = Path(tmp)
        for vi_p, ch_p in selected:
            imgs = {}
            for key, pno in (("ch", ch_p), ("vi", vi_p)):
                pref = tmp_dir / f"pair_{key}_{pno:04d}"
                subprocess.run(
                    ["pdftoppm", "-jpeg", "-r", "100", "-f", str(pno), "-l", str(pno), str(pdf_path), str(pref)],
                    check=True,
                    capture_output=True,
                )
                f = sorted(tmp_dir.glob(f"pair_{key}_{pno:04d}*.jpg"))[0]
                with Image.open(f) as im:
                    scale = row_h / float(im.height)
                    imgs[key] = im.convert("RGB").resize((int(im.width * scale), row_h), Image.Resampling.LANCZOS)

            pair_w = imgs["ch"].width + sep + imgs["vi"].width
            strip = Image.new("RGB", (pair_w, row_h + hdr_h), (240, 240, 240))
            d = ImageDraw.Draw(strip)
            d.rectangle([0, 0, pair_w, hdr_h], fill=(33, 37, 41))
            d.text((14, 7), f"CH PDF p.{ch_p:03d}  <--->  VI PDF p.{vi_p:03d}", fill=(255, 255, 255), font=font)
            strip.paste(imgs["ch"], (0, hdr_h))
            strip.paste(imgs["vi"], (imgs["ch"].width + sep, hdr_h))
            rows_imgs.append(strip)

    total_w = max(s.width for s in rows_imgs)
    total_h = sum(s.height + 16 for s in rows_imgs) + 16
    canvas = Image.new("RGB", (total_w, total_h), (215, 215, 215))
    y = 16
    for s in rows_imgs:
        canvas.paste(s, (0, y))
        y += s.height + 16

    out_path.parent.mkdir(parents=True, exist_ok=True)
    canvas.save(out_path, quality=88)
    return [{"vi_pdf_page": vp, "ch_pdf_page": cp} for vp, cp in selected]


def detect_transition_and_anomalies(pages_info: List[Dict[str, Any]]) -> Dict[str, Any]:
    n = len(pages_info)
    # Tìm ranh giới T (1-indexed) tối ưu hóa vi_like trước T và ch_like từ T trở đi
    vi_prefix = [0] * (n + 2)
    ch_suffix = [0] * (n + 2)
    for i in range(1, n + 1):
        vi_prefix[i] = vi_prefix[i - 1] + (1 if pages_info[i - 1]["type"] == "vi_like" else 0)
    for i in range(n, 0, -1):
        ch_suffix[i] = ch_suffix[i + 1] + (1 if pages_info[i - 1]["type"] == "ch_like" else 0)

    best_t = max(range(1, n + 2), key=lambda t: vi_prefix[t - 1] + ch_suffix[t])

    vi_pages = [p["page"] for p in pages_info if p["page"] < best_t and p["type"] == "vi_like"]
    ch_pages = [p["page"] for p in pages_info if p["page"] >= best_t and p["type"] == "ch_like"]

    anomalies = []
    for p in pages_info:
        t = p["type"]
        pno = p["page"]
        if t in ("blank", "sparse", "cover_or_color") or p["is_landscape"]:
            anomalies.append(pno)
        elif pno >= best_t and t == "vi_like":
            anomalies.append(pno)
        elif pno < best_t and t == "ch_like":
            anomalies.append(pno)

    return {
        "transition_page": best_t,
        "vi_count": len(vi_pages),
        "vi_first": vi_pages[0] if vi_pages else None,
        "vi_last": vi_pages[-1] if vi_pages else None,
        "ch_count": len(ch_pages),
        "ch_first": ch_pages[0] if ch_pages else None,
        "ch_last": ch_pages[-1] if ch_pages else None,
        "vi_pages": vi_pages,
        "ch_pages": ch_pages,
        "anomaly_pages": anomalies,
    }


def inspect_book(pdf_path: Path, out_dir: Path, tag: str) -> Dict[str, Any]:
    out_dir.mkdir(parents=True, exist_ok=True)
    n_pages = get_pdf_page_count(pdf_path)
    print(f"[Audit:{tag}] {pdf_path.name}: {n_pages} pages -> rendering 30 DPI scan...")

    with tempfile.TemporaryDirectory() as tmp:
        tmp_dir = Path(tmp)
        subprocess.run(
            ["pdftoppm", "-jpeg", "-r", "30", str(pdf_path), str(tmp_dir / "p")],
            check=True,
            capture_output=True,
        )
        rendered = sorted(tmp_dir.glob("p-*.jpg"))
        if len(rendered) != n_pages:
            raise RuntimeError(f"Expected {n_pages} rendered pages, got {len(rendered)}")

        pages_info: List[Dict[str, Any]] = []
        img_by_page: Dict[int, Path] = {}
        for idx, img_p in enumerate(rendered, 1):
            bgr = cv2.imread(str(img_p))
            if bgr is None:
                raise RuntimeError(f"Cannot read rendered image: {img_p}")
            metrics = classify_page_metrics(bgr)
            metrics["page"] = idx
            pages_info.append(metrics)
            img_by_page[idx] = img_p

        summary = detect_transition_and_anomalies(pages_info)
        print(
            f"[Audit:{tag}] transition=p.{summary['transition_page']} | "
            f"vi={summary['vi_count']} ({summary['vi_first']}..{summary['vi_last']}) | "
            f"ch={summary['ch_count']} ({summary['ch_first']}..{summary['ch_last']}) | "
            f"anomalies={summary['anomaly_pages']}"
        )

        # Kiểm tra liên tục số trang in sẵn trong vùng VI
        numbering = check_vi_numbering_continuity(pdf_path, summary["vi_pages"], pages_info)
        print(f"[Audit:{tag}] VI numbering checkpoints={len(numbering['checkpoints'])}, jumps={len(numbering['jumps'])}")

        # Render các contact sheets
        start_pages = list(range(1, min(n_pages, 20) + 1))
        render_contact_sheet(
            [(p, img_by_page[p], pages_info[p - 1]) for p in start_pages],
            out_dir / f"{tag}_start.jpg",
        )

        t_mid = summary["transition_page"]
        t_start = max(1, t_mid - 10)
        t_end = min(n_pages, t_start + 19)
        t_start = max(1, t_end - 19)
        render_contact_sheet(
            [(p, img_by_page[p], pages_info[p - 1]) for p in range(t_start, t_end + 1)],
            out_dir / f"{tag}_transition.jpg",
        )

        end_start = max(1, n_pages - 19)
        render_contact_sheet(
            [(p, img_by_page[p], pages_info[p - 1]) for p in range(end_start, n_pages + 1)],
            out_dir / f"{tag}_end.jpg",
        )

        anom_list = summary["anomaly_pages"]
        anomaly_files: List[str] = []
        if anom_list:
            chunk_size = 40
            for ci in range(0, len(anom_list), chunk_size):
                chunk = anom_list[ci : ci + chunk_size]
                suffix = "" if len(anom_list) <= chunk_size else f"_{ci // chunk_size + 1}"
                fname = f"{tag}_anomalies{suffix}.jpg"
                render_contact_sheet(
                    [(p, img_by_page[p], pages_info[p - 1]) for p in chunk],
                    out_dir / fname,
                )
                anomaly_files.append(fname)

    sample_pairs = render_sample_pairs_sheet(
        pdf_path,
        summary["vi_pages"],
        list(reversed(summary["ch_pages"])),
        out_dir / f"{tag}_sample_pairs.jpg",
    )

    type_counts: Dict[str, int] = {}
    for p in pages_info:
        type_counts[p["type"]] = type_counts.get(p["type"], 0) + 1

    result = {
        "pdf": str(pdf_path),
        "tag": tag,
        "total_pages": n_pages,
        "type_counts": type_counts,
        "transition_page": summary["transition_page"],
        "vi_count": summary["vi_count"],
        "vi_first": summary["vi_first"],
        "vi_last": summary["vi_last"],
        "ch_count": summary["ch_count"],
        "ch_first": summary["ch_first"],
        "ch_last": summary["ch_last"],
        "anomaly_pages": [pages_info[p - 1] for p in summary["anomaly_pages"]],
        "vi_numbering": numbering,
        "sample_pairs": sample_pairs,
        "contact_sheets": {
            "start": f"{tag}_start.jpg",
            "transition": f"{tag}_transition.jpg",
            "end": f"{tag}_end.jpg",
            "anomalies": anomaly_files,
            "sample_pairs": f"{tag}_sample_pairs.jpg",
        },
        "pages": pages_info,
    }
    json_path = out_dir / f"{tag}_structure.json"
    json_path.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"[Audit:{tag}] Saved report -> {json_path}")
    return result


def main():
    parser = argparse.ArgumentParser(description="Inspect and visually audit full Sino-Nom PDF book structure.")
    parser.add_argument("--pdf", type=str, required=True, help="Đường dẫn file PDF")
    parser.add_argument("--out-dir", type=str, required=True, help="Thư mục xuất JSON và contact sheets")
    parser.add_argument("--tag", type=str, required=True, help="Tiền tố tên file output (vd tap1, tap2)")
    args = parser.parse_args()
    inspect_book(Path(args.pdf), Path(args.out_dir), args.tag)


if __name__ == "__main__":
    main()
