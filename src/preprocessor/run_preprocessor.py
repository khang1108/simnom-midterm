import argparse
import sys
from pathlib import Path
from typing import List, Dict

from src.preprocessor.pdf_slicer import PDFSlicer
from src.preprocessor.image import ImageClassifier, ImageMapper

def parse_range(range_str: str) -> List[int]:
    """Parse string dạng '1-5,7,10-12' thành [1, 2, 3, 4, 5, 7, 10, 11, 12]"""
    result = []
    if not range_str:
        return result
    parts = range_str.split(",")
    for p in parts:
        p = p.strip()
        if "-" in p:
            start, end = map(int, p.split("-"))
            result.extend(range(start, end + 1))
        elif p.isdigit():
            result.append(int(p))
    return sorted(list(set(result)))

def main():
    parser = argparse.ArgumentParser(description="Baseline Preprocessor for Sino-Nom Dataset Pipeline.")
    parser.add_argument("--pdf", type=str, required=True, help="Path to input PDF file")
    parser.add_argument("--book-name", type=str, default=None, help="Book name (defaults to PDF filename)")
    parser.add_argument("--output-dir", type=str, default=None, help="Root folder for output")
    parser.add_argument("--dpi", type=int, default=300, help="DPI for extraction (default 300)")
    parser.add_argument("--first-page", type=int, default=None, help="First page to extract")
    parser.add_argument("--last-page", type=int, default=None, help="Last page to extract")
    parser.add_argument("--split-double-pages", action="store_true", help="Split 2-page scan into 2 separate images")
    
    # Các khoảng trang cấu hình trực tiếp từ mục lục sách
    parser.add_argument("--vi-pages", type=str, default="", help="Page numbers for Quoc Ngu (e.g. '1-20')")
    parser.add_argument("--ch-pages", type=str, default="", help="Page numbers for Nom (e.g. '21-80')")
    parser.add_argument("--blank-pages", type=str, default="", help="Page numbers for blank pages (e.g. '81,82')")
    parser.add_argument("--misc-pages", type=str, default="", help="Page numbers for cover/misc pages (e.g. '0,83')")
    parser.add_argument("--intro-pages", type=str, default="", help="Page numbers for intro pages")
    parser.add_argument("--layout", type=str, default="T1", choices=["T1", "T2", "T2b"], help="Layout type")
    parser.add_argument("--auto-detect-blank", action="store_true", help="Enable heuristic blank detection")
    
    args = parser.parse_args()
    pdf_path = Path(args.pdf)
    if not pdf_path.exists():
        print(f"Error: PDF file {pdf_path} does not exist.")
        sys.exit(1)

    book_name = args.book_name or pdf_path.stem
    target_root = Path(args.output_dir or f"./data/processed/{book_name}")
    raw_slice_dir = target_root / "_raw_slices"

    print(f"=== Baseline Preprocessor: {book_name} ===")
    print(f"1. Slicing PDF pages at {args.dpi} DPI...")
    slicer = PDFSlicer(dpi=args.dpi)
    images = slicer.slice_pdf(
        pdf_path=pdf_path,
        output_dir=raw_slice_dir,
        book_name=book_name,
        first_page=args.first_page,
        last_page=args.last_page,
        split_double_pages=args.split_double_pages
    )

    print(f"2. Organizing into ch/, vi/, blank/, misc/ according to page specification...")
    rules: Dict[str, List[int]] = {}
    if args.vi_pages:
        rules["vi"] = parse_range(args.vi_pages)
    if args.ch_pages:
        rules["ch"] = parse_range(args.ch_pages)
    if args.blank_pages:
        rules["blank"] = parse_range(args.blank_pages)
    if args.misc_pages:
        rules["misc"] = parse_range(args.misc_pages)
    if args.intro_pages:
        rules["intro"] = parse_range(args.intro_pages)

    ImageClassifier.organize_directory(
        source_dir=raw_slice_dir,
        target_book_dir=target_root,
        mapping_rules=rules,
        auto_detect_blank=args.auto_detect_blank
    )

    # 3. Sinh file image_map.json
    print(f"3. Generating {book_name}_image_map.json...")
    ch_files = [p.name for p in (target_root / "ch").glob("*.jpg")]
    vi_files = [p.name for p in (target_root / "vi").glob("*.jpg")]

    if ch_files and vi_files:
        if args.layout == "T1":
            map_data = ImageMapper.create_image_map_t1(
                book_name=book_name,
                vi_images=vi_files,
                ch_images=ch_files
            )
        else:
            pairs = []
            for c, v in zip(sorted(ch_files), sorted(vi_files)):
                pairs.append({"ch": [c], "vi": [v]})
            map_data = {"pairs": pairs}

        map_path = target_root / f"{book_name}_image_map.json"
        ImageMapper.save_image_map(map_data, map_path)

        # Validate
        errors = ImageMapper.validate_image_map(map_path, target_root)
        if errors:
            print(f"[Warning] Image map validation notes:")
            for e in errors:
                print(f"  - {e}")
        else:
            print(f"[Success] {map_path.name} is 100% compliant with Rubric v2.1!")

    print(f"=== Baseline Preprocessing complete! Output saved to: {target_root} ===")

if __name__ == "__main__":
    main()
