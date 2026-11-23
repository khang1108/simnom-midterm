import json
import os
import re
import time
import traceback
import zipfile
from pathlib import Path
from typing import Any, Dict, List, Tuple

import cv2
import numpy as np
import torch
from PIL import Image, ImageDraw

# Shim bắt buộc cho Pillow >= 10 khi dùng vietocr
if not hasattr(Image, "ANTIALIAS"):
    Image.ANTIALIAS = Image.Resampling.LANCZOS

BENCH_IMGS_ZIP = Path("/content/bench_imgs.zip")
BENCH_IMGS_DIR = Path("/content/bench_imgs")
OUT_DIR = Path("/content/bench_out")
RESULTS_ZIP = Path("/content/benchmark_results.zip")

CANONICAL_PREFIX = "vi/T1_Sách Dạy Đấng Làm Người Sửa Mình (Tập 1)."
VLM_PROMPT = (
    "Đọc chính xác dòng chữ tiếng Việt trong ảnh. "
    "Giữ nguyên từ cổ, dấu thanh và dấu câu gốc, không tự ý sửa hay giải thích. "
    "Chỉ xuất đúng dòng chữ đó."
)


def detect_vi_lines(img_bgr: np.ndarray) -> List[Dict[str, Any]]:
    """
    Phát hiện bounding box từng dòng Quốc ngữ ở 72 DPI (~1067x1513):
    - Adaptive threshold để triệt tiêu vết ố vàng nền giấy.
    - Valley-splitting khi hai dòng đặc sát nhau.
    - Loại bỏ dòng số trang ở mép trên cùng.
    - Mở rộng ±12px theo chiều ngang để không bao giờ cụt chữ mép phải.
    """
    gray = cv2.cvtColor(img_bgr, cv2.COLOR_BGR2GRAY)
    h, w = gray.shape

    bw = cv2.adaptiveThreshold(
        gray, 255, cv2.ADAPTIVE_THRESH_GAUSSIAN_C, cv2.THRESH_BINARY_INV, 31, 18
    )
    # Xóa nhiễu viền mép giấy 5%
    bw[:, : int(w * 0.05)] = 0
    bw[:, int(w * 0.95) :] = 0
    bw[: int(h * 0.05), :] = 0
    bw[int(h * 0.95) :, :] = 0

    raw_proj = np.sum(bw > 0, axis=1)
    kern = cv2.getStructuringElement(cv2.MORPH_RECT, (25, 1))
    closed = cv2.morphologyEx(bw, cv2.MORPH_CLOSE, kern)
    row_sum = np.sum(closed > 0, axis=1)
    active = row_sum > 22

    diff = np.diff(active.astype(int))
    ys = np.where(diff == 1)[0] + 1
    ye = np.where(diff == -1)[0] + 1
    if active[0]:
        ys = np.r_[0, ys]
    if active[-1]:
        ye = np.r_[ye, len(active)]

    raw_bands = [(int(a), int(b)) for a, b in zip(ys, ye) if b - a >= 10]
    if not raw_bands:
        return []

    hs = sorted(b - a for a, b in raw_bands)
    single_hs = [x for x in hs if x <= 48] or hs
    med_h = float(np.median(single_hs))

    bands: List[Tuple[int, int]] = []
    for a, b in raw_bands:
        bh = b - a
        if bh <= med_h * 1.6:
            bands.append((a, b))
        else:
            k = max(2, int(round(bh / (med_h * 1.1))))
            prev = a
            for s in range(1, k):
                target = int(a + s * bh / k)
                lo = max(prev + 12, target - int(med_h * 0.4))
                hi = min(b - 12, target + int(med_h * 0.4))
                split_y = target if lo >= hi else (lo + int(np.argmin(raw_proj[lo:hi])))
                bands.append((prev, split_y))
                prev = split_y
            bands.append((prev, b))

    # Loại bỏ band tiêu đề số trang ở trên cùng nếu tách biệt rõ với thân văn bản
    if len(bands) >= 2:
        top_a, top_b = bands[0]
        next_a, _ = bands[1]
        top_yc = (top_a + top_b) * 0.5
        if top_yc < 0.16 * h and (next_a - top_b) > 1.5 * med_h:
            bands = bands[1:]

    # Mở rộng nhẹ ±5px theo chiều dọc (không chồng lấn band lân cận) và tìm biên ngang x1..x2 ±12px
    lines_out: List[Dict[str, Any]] = []
    for idx, (a, b) in enumerate(bands):
        prev_end = bands[idx - 1][1] if idx > 0 else 0
        next_start = bands[idx + 1][0] if idx + 1 < len(bands) else h
        y1 = max(prev_end, a - 5)
        y2 = min(next_start, b + 5)

        band_slice = bw[a:b, :]
        col_ink = np.sum(band_slice > 0, axis=0)
        xs = np.where(col_ink > 1)[0]
        if len(xs) == 0:
            continue
        x1 = max(0, int(xs[0]) - 12)
        x2 = min(w, int(xs[-1]) + 13)
        if x2 - x1 < 8 or y2 - y1 < 8:
            continue

        lines_out.append({
            "points": [[x1, y1], [x2, y1], [x2, y2], [x1, y2]],
            "bbox": [x1, y1, x2, y2],
        })
    return lines_out


def draw_preview_boxes(img_bgr: np.ndarray, boxes: List[Dict[str, Any]], out_path: Path) -> None:
    vis = img_bgr.copy()
    for i, item in enumerate(boxes, 1):
        x1, y1, x2, y2 = item["bbox"]
        cv2.rectangle(vis, (x1, y1), (x2, y2), (0, 175, 0), 2)
        cv2.putText(vis, str(i), (max(2, x1 - 28), y1 + 20), cv2.FONT_HERSHEY_SIMPLEX, 0.55, (200, 0, 0), 2)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    cv2.imwrite(str(out_path), vis)


def save_ppocr_label(per_image_results: Dict[str, List[Dict[str, Any]]], out_path: Path) -> None:
    lines = []
    for img_name in sorted(per_image_results.keys()):
        items = [
            {"transcription": x["transcription"], "points": x["points"]}
            for x in per_image_results[img_name]
            if x.get("transcription", "").strip()
        ]
        # Giữ đúng tên file theo chuẩn <Tên sách>.<NNN>.jpg trong vi/
        m = re.search(r"(\d{3})\.jpg$", img_name)
        rel_key = f"{CANONICAL_PREFIX}{m.group(1)}.jpg" if m else f"vi/{img_name}"
        lines.append(f"{rel_key}\t{json.dumps(items, ensure_ascii=False)}\n")
    out_path.write_text("".join(lines), encoding="utf-8")


def run_vietocr(page_crops: Dict[str, Tuple[np.ndarray, List[Dict[str, Any]]]]) -> Tuple[Dict[str, Any], float]:
    from vietocr.tool.config import Cfg
    from vietocr.tool.predictor import Predictor

    t_load0 = time.time()
    config = Cfg.load_config_from_name("vgg_transformer")
    config["device"] = "cuda:0" if torch.cuda.is_available() else "cpu"
    config["cnn"]["pretrained"] = False
    config["predictor"]["beamsearch"] = False
    predictor = Predictor(config)
    load_sec = time.time() - t_load0
    print(f"[VietOCR] Model loaded in {load_sec:.2f}s (device={config['device']})")

    t0 = time.time()
    results: Dict[str, List[Dict[str, Any]]] = {}
    for img_name, (img_bgr, lines) in sorted(page_crops.items()):
        pil_crops = []
        for item in lines:
            x1, y1, x2, y2 = item["bbox"]
            crop_rgb = cv2.cvtColor(img_bgr[y1:y2, x1:x2], cv2.COLOR_BGR2RGB)
            pil_crops.append(Image.fromarray(crop_rgb))

        texts = predictor.predict_batch(pil_crops) if pil_crops else []
        results[img_name] = [
            {"transcription": t.strip(), "points": item["points"], "bbox": item["bbox"]}
            for item, t in zip(lines, texts)
        ]
    infer_sec = time.time() - t0
    return {"model": "vietocr_vgg_transformer", "load_sec": load_sec, "infer_sec": infer_sec, "pages": results}, infer_sec


def _vintern_build_transform(input_size: int = 448):
    import torchvision.transforms as T
    from torchvision.transforms.functional import InterpolationMode

    mean = (0.485, 0.456, 0.406)
    std = (0.229, 0.224, 0.225)
    return T.Compose([
        T.Lambda(lambda img: img.convert("RGB") if img.mode != "RGB" else img),
        T.Resize((input_size, input_size), interpolation=InterpolationMode.BICUBIC),
        T.ToTensor(),
        T.Normalize(mean=mean, std=std),
    ])


def _vintern_dynamic_preprocess(image: Image.Image, min_num: int = 1, max_num: int = 6, image_size: int = 448) -> List[Image.Image]:
    orig_width, orig_height = image.size
    aspect_ratio = orig_width / float(max(1, orig_height))
    target_ratios = sorted(
        {
            (i, j)
            for n in range(min_num, max_num + 1)
            for i in range(1, n + 1)
            for j in range(1, n + 1)
            if min_num <= i * j <= max_num
        },
        key=lambda x: x[0] * x[1],
    )
    best_diff = float("inf")
    best_ratio = (1, 1)
    area = orig_width * orig_height
    for ratio in target_ratios:
        tar_ar = ratio[0] / ratio[1]
        diff = abs(aspect_ratio - tar_ar)
        if diff < best_diff or (diff == best_diff and area > 0.5 * image_size * image_size * ratio[0] * ratio[1]):
            best_diff = diff
            best_ratio = ratio

    tw = image_size * best_ratio[0]
    th = image_size * best_ratio[1]
    blocks = best_ratio[0] * best_ratio[1]
    resized = image.resize((tw, th))
    out = []
    for i in range(blocks):
        box = (
            (i % (tw // image_size)) * image_size,
            (i // (tw // image_size)) * image_size,
            ((i % (tw // image_size)) + 1) * image_size,
            ((i // (tw // image_size)) + 1) * image_size,
        )
        out.append(resized.crop(box))
    if len(out) != 1:
        out.append(image.resize((image_size, image_size)))
    return out


def run_vlm(page_crops: Dict[str, Tuple[np.ndarray, List[Dict[str, Any]]]]) -> Dict[str, Any]:
    from transformers import AutoModel, AutoTokenizer

    # Thử Vintern-1B-v2 (float16 cho Tesla T4)
    try:
        t_load0 = time.time()
        model_id = "5CD-AI/Vintern-1B-v2"
        model = AutoModel.from_pretrained(
            model_id,
            torch_dtype=torch.float16,
            low_cpu_mem_usage=True,
            trust_remote_code=True,
        ).eval().cuda()
        tokenizer = AutoTokenizer.from_pretrained(model_id, trust_remote_code=True, use_fast=False)
        transform = _vintern_build_transform(448)
        load_sec = time.time() - t_load0
        print(f"[Vintern-1B-v2] Loaded in {load_sec:.2f}s (float16)")

        t0 = time.time()
        results: Dict[str, List[Dict[str, Any]]] = {}
        gen_cfg = {"max_new_tokens": 128, "do_sample": False, "num_beams": 1, "repetition_penalty": 1.05}
        question = f"<image>\n{VLM_PROMPT}"
        with torch.inference_mode():
            for img_name, (img_bgr, lines) in sorted(page_crops.items()):
                page_res = []
                for item in lines:
                    x1, y1, x2, y2 = item["bbox"]
                    crop_rgb = cv2.cvtColor(img_bgr[y1:y2, x1:x2], cv2.COLOR_BGR2RGB)
                    pil_img = Image.fromarray(crop_rgb)
                    tiles = _vintern_dynamic_preprocess(pil_img, min_num=1, max_num=4, image_size=448)
                    pv = torch.stack([transform(t) for t in tiles]).to(dtype=torch.float16, device="cuda")
                    resp = model.chat(tokenizer, pv, question, gen_cfg)
                    text = " ".join(str(resp).strip().splitlines()).strip()
                    page_res.append({"transcription": text, "points": item["points"], "bbox": item["bbox"]})
                results[img_name] = page_res
        infer_sec = time.time() - t0
        del model
        torch.cuda.empty_cache()
        return {
            "model": model_id,
            "tag": "vintern",
            "load_sec": load_sec,
            "infer_sec": infer_sec,
            "pages": results,
        }
    except Exception as exc:
        vintern_err = traceback.format_exc()
        print(f"[VLM] Vintern-1B-v2 failed ({exc}); falling back to Qwen/Qwen2.5-VL-3B-Instruct...")
        torch.cuda.empty_cache()

    # Fallback: Qwen/Qwen2.5-VL-3B-Instruct
    from transformers import AutoProcessor, Qwen2_5_VLForConditionalGeneration

    t_load0 = time.time()
    model_id = "Qwen/Qwen2.5-VL-3B-Instruct"
    processor = AutoProcessor.from_pretrained(model_id)
    model = Qwen2_5_VLForConditionalGeneration.from_pretrained(
        model_id, torch_dtype=torch.float16, device_map="cuda"
    ).eval()
    load_sec = time.time() - t_load0
    print(f"[Qwen2.5-VL-3B] Loaded in {load_sec:.2f}s")

    t0 = time.time()
    results = {}
    with torch.inference_mode():
        for img_name, (img_bgr, lines) in sorted(page_crops.items()):
            page_res = []
            for item in lines:
                x1, y1, x2, y2 = item["bbox"]
                crop_rgb = cv2.cvtColor(img_bgr[y1:y2, x1:x2], cv2.COLOR_BGR2RGB)
                pil_img = Image.fromarray(crop_rgb)
                messages = [{"role": "user", "content": [{"type": "image", "image": pil_img}, {"type": "text", "text": VLM_PROMPT}]}]
                txt = processor.apply_chat_template(messages, tokenize=False, add_generation_prompt=True)
                inputs = processor(text=[txt], images=[pil_img], padding=True, return_tensors="pt").to("cuda")
                gen_ids = model.generate(**inputs, max_new_tokens=128, do_sample=False)
                trimmed = [o[len(i) :] for i, o in zip(inputs.input_ids, gen_ids)]
                out_txt = processor.batch_decode(trimmed, skip_special_tokens=True)[0]
                page_res.append({"transcription": " ".join(out_txt.split()), "points": item["points"], "bbox": item["bbox"]})
            results[img_name] = page_res
    infer_sec = time.time() - t0
    return {
        "model": model_id,
        "tag": "vlm",
        "vintern_error": vintern_err,
        "load_sec": load_sec,
        "infer_sec": infer_sec,
        "pages": results,
    }


def main() -> None:
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    BENCH_IMGS_DIR.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(BENCH_IMGS_ZIP, "r") as zf:
        zf.extractall(BENCH_IMGS_DIR)

    img_paths = sorted(BENCH_IMGS_DIR.glob("*.jpg"))
    print(f"Loaded {len(img_paths)} images from {BENCH_IMGS_ZIP}")

    gpu_name = torch.cuda.get_device_name(0) if torch.cuda.is_available() else "CPU"
    vram_gb = (torch.cuda.get_device_properties(0).total_memory / (1024**3)) if torch.cuda.is_available() else 0.0
    print(f"Hardware: {gpu_name} ({vram_gb:.2f} GB VRAM)")

    page_crops: Dict[str, Tuple[np.ndarray, List[Dict[str, Any]]]] = {}
    line_counts: Dict[str, int] = {}
    for p in img_paths:
        bgr = cv2.imread(str(p))
        lines = detect_vi_lines(bgr)
        page_crops[p.name] = (bgr, lines)
        line_counts[p.name] = len(lines)
        if p.name.endswith("048.jpg"):
            draw_preview_boxes(bgr, lines, OUT_DIR / "preview_048_boxes.jpg")
        if p.name.endswith("275.jpg"):
            draw_preview_boxes(bgr, lines, OUT_DIR / "preview_275_boxes.jpg")
    print("Detected line counts:", line_counts)

    # Candidate A: VietOCR
    vietocr_res, _ = run_vietocr(page_crops)
    save_ppocr_label(vietocr_res["pages"], OUT_DIR / "vietocr_vi_Label.txt")
    (OUT_DIR / "vietocr_results.json").write_text(json.dumps(vietocr_res, ensure_ascii=False, indent=2), encoding="utf-8")

    # Candidate B: VLM (Vintern-1B-v2 hoặc fallback Qwen2.5-VL-3B)
    vlm_res = run_vlm(page_crops)
    tag = vlm_res.get("tag", "vlm")
    save_ppocr_label(vlm_res["pages"], OUT_DIR / f"{tag}_vi_Label.txt")
    (OUT_DIR / f"{tag}_results.json").write_text(json.dumps(vlm_res, ensure_ascii=False, indent=2), encoding="utf-8")

    n_pages = max(1, len(img_paths))
    summary = {
        "gpu_name": gpu_name,
        "vram_gb": round(vram_gb, 2),
        "line_counts": line_counts,
        "vietocr": {
            "model": vietocr_res["model"],
            "load_sec": round(vietocr_res["load_sec"], 2),
            "infer_sec_total": round(vietocr_res["infer_sec"], 2),
            "sec_per_page": round(vietocr_res["infer_sec"] / n_pages, 3),
        },
        "vlm": {
            "model": vlm_res["model"],
            "tag": tag,
            "load_sec": round(vlm_res["load_sec"], 2),
            "infer_sec_total": round(vlm_res["infer_sec"], 2),
            "sec_per_page": round(vlm_res["infer_sec"] / n_pages, 3),
            "vintern_error": vlm_res.get("vintern_error"),
        },
        "page_275_sample": {
            "vietocr_first_9": [
                x["transcription"]
                for k, v in vietocr_res["pages"].items()
                if k.endswith("275.jpg")
                for x in v[:9]
            ],
            f"{tag}_first_9": [
                x["transcription"]
                for k, v in vlm_res["pages"].items()
                if k.endswith("275.jpg")
                for x in v[:9]
            ],
        },
    }
    (OUT_DIR / "benchmark_summary.json").write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")

    with zipfile.ZipFile(RESULTS_ZIP, "w", compression=zipfile.ZIP_DEFLATED) as zf:
        for f in sorted(OUT_DIR.iterdir()):
            if f.is_file():
                zf.write(f, arcname=f.name)
    print(f"Done! Zipped results -> {RESULTS_ZIP}")
    print(json.dumps(summary, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
