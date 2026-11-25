import argparse
import difflib
import re
import csv
import sys
from pathlib import Path
from tqdm import tqdm

from src.ocr.engine import OCREngine
from src.ocr.ppocr_adapter import PPOCRAdapter

PUA_MAP_FILE = Path("configs/pua_to_unicode.csv")
GLYPH_FIX_FILE = Path("configs/kim_glyph_fix.csv")


def load_pua_map(path: Path = PUA_MAP_FILE) -> dict:
    """Bảng str.translate: ký tự riêng (PUA) của Kim Hán Nôm -> mã Unicode chuẩn (đã đối chiếu hình chữ/IDS)."""
    if not path.exists():
        return {}
    with open(path, encoding="utf-8") as f:
        return {int((r.get("pua") or r["kim"])[2:], 16): chr(int(r["unicode"][2:], 16)) for r in csv.DictReader(f)}

def check_ppocr_status(folder: Path) -> bool:
    """Kiểm tra nhanh xem Label.txt và fileState.txt đã tạo đủ và chuẩn hay chưa."""
    label_file = folder / "Label.txt"
    state_file = folder / "fileState.txt"
    if not label_file.exists() or not state_file.exists():
        return False
    state_lines = [l.strip() for l in state_file.read_text(encoding="utf-8").splitlines() if l.strip()]
    return len(state_lines) > 0 and all(l.endswith("\t1") for l in state_lines)

def process_folder(folder: Path, script_type: str, ocr_engine: OCREngine, dry_run: bool = False):
    """Xử lý OCR và sinh Label.txt, fileState.txt cho một thư mục (ch hoặc vi)."""
    from src.aligner.book_aligner import BookAligner
    from src.segmenter.core.cleaner import TextCleaner

    if not folder.exists():
        return

    images = sorted(list(folder.glob("*.jpg")))
    print(f"\n[OCR Runner] Processing {len(images)} images in '{folder.name}' (script={script_type})...")

    label_lines = []
    state_lines = []
    char_label_lines = []
    char_state_lines = []
    pua_map = {**load_pua_map(), **load_pua_map(GLYPH_FIX_FILE)} if script_type == "ch" else {}

    for img_path in tqdm(images, desc=f"OCR {folder.name}/"):
        if dry_run:
            boxes = [{
                "transcription": "承天" if script_type == "ch" else "Kinh Thân",
                "points": [[100, 100], [200, 100], [200, 200], [100, 200]],
                "difficult": False
            }]
        else:
            boxes = ocr_engine.recognize(img_path, script=script_type)
            if not boxes or not any(b.get("transcription", "").strip() for b in boxes):
                raise RuntimeError(f"OCR returned no text for {img_path.name}; labels were not written.")
        if pua_map:
            boxes = [{**b, "transcription": b.get("transcription", "").translate(pua_map)} for b in boxes]
        if not dry_run:
            boxes = BookAligner.filter_body_boxes(boxes, script_type)
            if script_type == "vi":
                boxes = [{**b, "transcription": TextCleaner.fix_vi_ocr(b.get("transcription", ""))} for b in boxes]

        state_line = PPOCRAdapter.format_state_entry(folder.name, img_path.name)

        if script_type == "ch":
            # Sắp xếp trước theo thứ tự đọc chuẩn rồi mới tách từng chữ để Label.txt và Label_char.txt khớp hoàn toàn
            sorted_boxes = PPOCRAdapter.sort_boxes_reading_order(boxes, script_type=script_type)
            label_line = PPOCRAdapter.format_label_entry(
                folder_name=folder.name,
                image_name=img_path.name,
                boxes=sorted_boxes,
                script_type=script_type,
                preserve_order=True,
            )
            char_boxes = PPOCRAdapter.split_boxes_to_chars(sorted_boxes)
            char_label_line = PPOCRAdapter.format_label_entry(
                folder_name=folder.name,
                image_name=img_path.name,
                boxes=char_boxes,
                script_type=script_type,
                preserve_order=True,
            )
            char_label_lines.append(char_label_line)
            char_state_lines.append(state_line)
        else:
            label_line = PPOCRAdapter.format_label_entry(
                folder_name=folder.name,
                image_name=img_path.name,
                boxes=boxes,
                script_type=script_type,
            )

        label_lines.append(label_line)
        state_lines.append(state_line)

    # Ghi file chuẩn cột / dòng
    with open(folder / "Label.txt", "w", encoding="utf-8") as f:
        f.writelines(label_lines)
    with open(folder / "fileState.txt", "w", encoding="utf-8") as f:
        f.writelines(state_lines)

    # Ghi file chuẩn từng chữ cho ch/ (nếu có)
    if script_type == "ch" and char_label_lines:
        with open(folder / "Label_char.txt", "w", encoding="utf-8") as f:
            f.writelines(char_label_lines)
        with open(folder / "fileState_char.txt", "w", encoding="utf-8") as f:
            f.writelines(char_state_lines)
        print(f"  [Success] ch/Label_char.txt & fileState_char.txt generated ({len(char_label_lines)} images)")

    if check_ppocr_status(folder):
        print(f"  [Success] {folder.name}/Label.txt & fileState.txt generated (All state = 1)")
    else:
        print(f"  [Warning] Issues detected in {folder.name}/ PPOCRLabel files")

def run_ocr_pipeline(
    book_dir: Path,
    token: str = None,
    openai_key: str = None,
    openai_base_url: str = None,
    openai_model: str = None,
    dry_run: bool = False
):
    book_dir = Path(book_dir)
    vi_dir = book_dir / "vi"
    ch_dir = book_dir / "ch"

    if not vi_dir.exists() and not ch_dir.exists():
        print(f"Error: Neither {vi_dir} nor {ch_dir} exists.")
        sys.exit(1)

    ocr_kwargs = {}
    if token:
        ocr_kwargs["kim_token"] = token
    if openai_key:
        ocr_kwargs["openai_key"] = openai_key
    if openai_base_url:
        ocr_kwargs["openai_base_url"] = openai_base_url
    if openai_model:
        ocr_kwargs["openai_model"] = openai_model

    engine = OCREngine(**ocr_kwargs)

    # 1. Chạy vi/ (Quốc ngữ)
    process_folder(vi_dir, script_type="vi", ocr_engine=engine, dry_run=dry_run)

    # 2. Chạy ch/ (Hán Nôm)
    process_folder(ch_dir, script_type="ch", ocr_engine=engine, dry_run=dry_run)

    if not dry_run and engine.openai_key and vi_dir.exists() and ch_dir.exists():
        reconcile_vi_with_nom(book_dir, engine)

def main():
    parser = argparse.ArgumentParser(description="Unified OCR Runner for Sino-Nom Dataset Pipeline.")
    parser.add_argument("--book-dir", type=str, required=True, help="Path to book directory (containing ch/ and vi/)")
    parser.add_argument("--token", type=str, default=None, help="Bearer token for Kim Han Nom API")
    parser.add_argument("--openai-key", type=str, default=None, help="API key for OpenAI-compatible Vision API")
    parser.add_argument("--openai-base-url", type=str, default=None, help="Base URL for OpenAI-compatible API")
    parser.add_argument("--openai-model", type=str, default=None, help="Model name for Vision OCR (e.g. gpt-4o-mini)")
    parser.add_argument("--dry-run", action="store_true", help="Dry run without calling APIs")
    args = parser.parse_args()

    run_ocr_pipeline(
        book_dir=Path(args.book_dir),
        token=args.token,
        openai_key=args.openai_key,
        openai_base_url=args.openai_base_url,
        openai_model=args.openai_model,
        dry_run=args.dry_run
    )



_WORD_RE = re.compile(r"[^\W\d_]+")


def merge_vi_hypotheses(qwen: str, tess: str, page_keys: set) -> str:
    """ROVER 2 bản OCR một dòng Quốc ngữ: với từ mà hai bản chỉ khác dấu / d-đ, lấy bản Tesseract khi đó là âm
    đọc của một chữ Nôm trên trang đối ứng còn bản Qwen thì không. Không sinh chữ mới ngoài hai bản OCR."""
    from ocr_nom_align.tokens import syllable_key
    from src.segmenter.core.cleaner import _match_case, _vi_base

    qw, tw = list(_WORD_RE.finditer(qwen)), list(_WORD_RE.finditer(tess))
    base = lambda w: "".join(_vi_base(c) for c in w)
    sm = difflib.SequenceMatcher(a=[base(m.group()) for m in qw], b=[base(m.group()) for m in tw], autojunk=False)
    out, last = [], 0
    for a, b, n in sm.get_matching_blocks():
        for k in range(n):
            q, t = qw[a + k], tw[b + k]
            if (q.group().lower() != t.group().lower() and syllable_key(t.group()) in page_keys
                    and syllable_key(q.group()) not in page_keys):
                out += [qwen[last:q.start()], _match_case(q.group(), t.group().lower())]
                last = q.end()
    return "".join(out) + qwen[last:]


def reconcile_vi_with_nom(book_dir: Path, ocr_engine: OCREngine) -> int:
    """Sửa vi/Label.txt bằng merge_vi_hypotheses, đối chiếu âm đọc các chữ Nôm của cặp trang (và cặp kề bên).
    Bản Tesseract của mỗi trang được cache dưới script 'vi_tess'. Trả về số từ đã đổi."""
    import json
    from ocr_nom_align.readings import ReadingTable
    from src.aligner.book_aligner import BookAligner
    from src.segmenter.core.cleaner import TextCleaner
    from scripts.run_official_align import DEFAULT_READING_TABLES

    book_dir = Path(book_dir)
    maps = list(book_dir.glob("*_image_map.json"))
    vi_label = book_dir / "vi" / "Label.txt"
    if not maps or not vi_label.exists():
        return 0
    pairs = [p for p in json.loads(maps[0].read_text(encoding="utf-8"))["pairs"] if p.get("vi") and p.get("ch")]
    ch_pages = BookAligner.load_label_file(str(book_dir / "ch" / "Label.txt"))
    vi_pages = BookAligner.load_label_file(str(vi_label))
    table = ReadingTable.from_paths(DEFAULT_READING_TABLES)
    keys_of = lambda imgs: {k for i in imgs for b in ch_pages.get(i, []) for c in b["transcription"] for k in table.readings(c)}

    page_keys = {}
    for i, p in enumerate(pairs):
        near = [x for q in pairs[max(0, i - 1):i + 2] for x in q["ch"]]
        for v in p["vi"]:
            page_keys[v] = keys_of(near)

    changed = 0
    for name, boxes in vi_pages.items():
        img = book_dir / "vi" / name
        h = ocr_engine._get_file_hash(img)
        tess = ocr_engine._get_cached_result(h, "vi_tess")
        if tess is None:
            tess = [{**b, "transcription": TextCleaner.fix_vi_ocr(b["transcription"])} for b in ocr_engine._ocr_tesseract(img)]
            ocr_engine._save_cached_result(h, name, "vi_tess", "tesseract:vie", tess)
        alts = [{json.dumps(b["points"]): b["transcription"] for b in tess}]
        vlm96 = ocr_engine._get_cached_result(h, "vi_vlm96")
        if vlm96 is None and ocr_engine.openai_key:
            import cv2
            im = cv2.imread(str(img))
            vlm96 = [{"transcription": ocr_engine._vlm_read_crop(im, b["points"], "vi", min_h=96,
                                                                 prompt=ocr_engine.VLM_PROMPTS["vi_strict"]),
                      "points": b["points"]} for b in boxes]
            ocr_engine._save_cached_result(h, name, "vi_vlm96", f"openai:{ocr_engine.openai_model}:x96", vlm96)
        if vlm96:
            alts.append({json.dumps(b["points"]): b["transcription"] for b in vlm96})
        for b in boxes:
            old = b["transcription"]
            for alt in alts:
                t = alt.get(json.dumps(b["points"]))
                if t:
                    b["transcription"] = merge_vi_hypotheses(b["transcription"], t, page_keys.get(name, set()))
            changed += sum(x != y for x, y in zip(_WORD_RE.findall(b["transcription"]), _WORD_RE.findall(old)))
    with open(vi_label, "w", encoding="utf-8") as f:
        f.writelines(PPOCRAdapter.format_label_entry("vi", n, bs, script_type="vi") for n, bs in vi_pages.items())
    print(f"  [ROVER] vi/Label.txt: {changed} từ lấy theo bản OCR phụ (khớp âm Nôm của trang đối ứng)")
    return changed


if __name__ == "__main__":
    main()
