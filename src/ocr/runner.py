import argparse
import sys
from pathlib import Path
from tqdm import tqdm

from src.ocr.engine import OCREngine
from src.ocr.ppocr_adapter import PPOCRAdapter

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
    if not folder.exists():
        return

    images = sorted(list(folder.glob("*.jpg")))
    print(f"\n[OCR Runner] Processing {len(images)} images in '{folder.name}' (script={script_type})...")

    label_lines = []
    state_lines = []

    for img_path in tqdm(images, desc=f"OCR {folder.name}/"):
        if dry_run:
            boxes = [{
                "transcription": "承天" if script_type == "ch" else "Kinh Thân",
                "points": [[100, 100], [200, 100], [200, 200], [100, 200]],
                "difficult": False
            }]
        else:
            boxes = ocr_engine.recognize(img_path, script=script_type)

        label_line = PPOCRAdapter.format_label_entry(
            folder_name=folder.name,
            image_name=img_path.name,
            boxes=boxes,
            script_type=script_type
        )
        state_line = PPOCRAdapter.format_state_entry(folder.name, img_path.name)

        label_lines.append(label_line)
        state_lines.append(state_line)

    # Ghi file
    with open(folder / "Label.txt", "w", encoding="utf-8") as f:
        f.writelines(label_lines)
    with open(folder / "fileState.txt", "w", encoding="utf-8") as f:
        f.writelines(state_lines)

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

if __name__ == "__main__":
    main()
