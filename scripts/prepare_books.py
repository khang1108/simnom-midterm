import argparse
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path
from typing import Any, Dict, List, Optional, Set, Tuple

from PIL import Image
from ocr_nom_align.pages import read_image_map

PRIMARY_FOLDERS = ("vi", "ch", "intro", "ref", "toc", "blank", "misc")
ALL_MANAGED_SUBDIRS = (*PRIMARY_FOLDERS, "missing", "_raw_slices")


def parse_page_ranges(expr: Optional[str]) -> List[int]:
    """Parse biểu thức dải trang dạng '11-17,19-314' thành danh sách số nguyên tăng dần không trùng."""
    if not expr or not str(expr).strip():
        return []
    pages: Set[int] = set()
    for raw_tok in str(expr).split(","):
        tok = raw_tok.strip()
        if not tok:
            continue
        if "-" in tok:
            parts = tok.split("-")
            if len(parts) != 2 or not parts[0].strip().isdigit() or not parts[1].strip().isdigit():
                raise ValueError(f"Dải trang không hợp lệ: {tok!r}")
            start, end = int(parts[0].strip()), int(parts[1].strip())
            if start <= 0 or end < start:
                raise ValueError(f"Khoảng trang không hợp lệ: {tok!r}")
            pages.update(range(start, end + 1))
        else:
            if not tok.isdigit() or int(tok) <= 0:
                raise ValueError(f"Số trang không hợp lệ: {tok!r}")
            pages.add(int(tok))
    return sorted(pages)


def format_page_filename(book_name: str, page_no: int, total_pages: int) -> str:
    """Định dạng tên file ảnh theo Rules v2.4: 3 chữ số (<=999) hoặc không pad (>999)."""
    page_str = f"{page_no:03d}" if total_pages <= 999 else str(page_no)
    return f"{book_name}.{page_str}.jpg"


def get_pdf_page_count(pdf_path: Path) -> int:
    proc = subprocess.run(["pdfinfo", str(pdf_path)], capture_output=True, text=True, check=True)
    m = re.search(r"Pages:\s+(\d+)", proc.stdout)
    if not m:
        raise RuntimeError(f"Không đọc được tổng số trang từ pdfinfo: {pdf_path}")
    return int(m.group(1))


def build_image_map_pairs(
    book_name: str, pair_segments: List[Dict[str, Any]], total_pages: int
) -> List[Dict[str, Any]]:
    """Sinh mảng pairs cho <Tên sách>_image_map.json theo đúng thứ tự đọc."""
    pairs: List[Dict[str, Any]] = []
    for seg in pair_segments:
        stype = seg.get("type")
        if stype == "range":
            vi_start, vi_end = int(seg["vi_start"]), int(seg["vi_end"])
            ch_start, ch_end = int(seg["ch_start"]), int(seg["ch_end"])
            vi_step = 1 if vi_end >= vi_start else -1
            ch_step = 1 if ch_end >= ch_start else -1
            vi_seq = list(range(vi_start, vi_end + vi_step, vi_step))
            ch_seq = list(range(ch_start, ch_end + ch_step, ch_step))
            if len(vi_seq) != len(ch_seq):
                raise ValueError(
                    f"Độ dài vế VI ({len(vi_seq)}) != CH ({len(ch_seq)}) trong segment {seg!r}"
                )
            for vp, cp in zip(vi_seq, ch_seq):
                pairs.append({
                    "ch": [format_page_filename(book_name, cp, total_pages)],
                    "vi": [format_page_filename(book_name, vp, total_pages)],
                })
        elif stype == "missing_vi":
            ch_files = [format_page_filename(book_name, int(p), total_pages) for p in seg["ch"]]
            entry: Dict[str, Any] = {"ch": ch_files, "vi": []}
            if seg.get("note"):
                entry["note"] = seg["note"]
            pairs.append(entry)
        elif stype == "missing_ch":
            vi_files = [format_page_filename(book_name, int(p), total_pages) for p in seg["vi"]]
            entry = {"ch": [], "vi": vi_files}
            if seg.get("note"):
                entry["note"] = seg["note"]
            pairs.append(entry)
        else:
            raise ValueError(f"pair_segment type không hợp lệ: {stype!r}")
    return pairs


def validate_book_config(cfg: Dict[str, Any]) -> Dict[str, List[int]]:
    """
    Kiểm tra tính nhất quán tuyệt đối của cấu hình một tập sách:
    - Các thư mục chính (vi, ch, intro, ref, toc, blank, misc) không trùng và phủ kín 1..expected_pages.
    - missing/ch là tập con của ch; missing/vi (nếu có) rời nhau với vi.
    - pair_segments phủ khớp chính xác 100% các trang trong vi, ch và missing/ch.
    """
    expected = int(cfg["expected_pages"])
    book_name = cfg["book_name"]
    folders_cfg = cfg["folders"]

    folder_pages: Dict[str, List[int]] = {}
    seen_primary: Dict[int, str] = {}

    for fname in PRIMARY_FOLDERS:
        pages = parse_page_ranges(folders_cfg.get(fname, ""))
        folder_pages[fname] = pages
        for p in pages:
            if p < 1 or p > expected:
                raise ValueError(f"[{book_name}] Trang {p} trong '{fname}' vượt khỏi 1..{expected}")
            if p in seen_primary:
                raise ValueError(
                    f"[{book_name}] Trang {p} bị trùng giữa '{seen_primary[p]}' và '{fname}'"
                )
            seen_primary[p] = fname

    missing_pages = set(range(1, expected + 1)) - set(seen_primary.keys())
    if missing_pages:
        raise ValueError(
            f"[{book_name}] Thiếu {len(missing_pages)} trang chưa phân thư mục: {sorted(missing_pages)[:20]}"
        )

    missing_ch = parse_page_ranges(folders_cfg.get("missing/ch", ""))
    missing_vi = parse_page_ranges(folders_cfg.get("missing/vi", ""))
    folder_pages["missing/ch"] = missing_ch
    folder_pages["missing/vi"] = missing_vi

    if not set(missing_ch) <= set(folder_pages["ch"]):
        raise ValueError(
            f"[{book_name}] missing/ch phải nằm trong ch: ngoài ch = {sorted(set(missing_ch) - set(folder_pages['ch']))}"
        )
    if set(missing_vi) & set(folder_pages["vi"]):
        raise ValueError(
            f"[{book_name}] missing/vi bị trùng với vi: {sorted(set(missing_vi) & set(folder_pages['vi']))}"
        )

    # Kiểm tra đối chiếu pair_segments với folders
    pairs = build_image_map_pairs(book_name, cfg["pair_segments"], expected)
    seen_ch: Set[str] = set()
    seen_vi: Set[str] = set()
    paired_missing_ch: Set[str] = set()

    for idx, pair in enumerate(pairs):
        if not pair["ch"] and not pair["vi"]:
            raise ValueError(f"[{book_name}] pair #{idx} rỗng cả hai vế")
        for f in pair["ch"]:
            if f in seen_ch:
                raise ValueError(f"[{book_name}] Ảnh CH trùng lặp trong image_map: {f}")
            seen_ch.add(f)
        for f in pair["vi"]:
            if f in seen_vi:
                raise ValueError(f"[{book_name}] Ảnh VI trùng lặp trong image_map: {f}")
            seen_vi.add(f)
        if not pair["vi"]:
            paired_missing_ch.update(pair["ch"])

    expected_ch_files = {format_page_filename(book_name, p, expected) for p in folder_pages["ch"]}
    expected_vi_files = {format_page_filename(book_name, p, expected) for p in folder_pages["vi"]}
    expected_missing_ch_files = {format_page_filename(book_name, p, expected) for p in missing_ch}

    if seen_ch != expected_ch_files:
        raise ValueError(
            f"[{book_name}] image_map CH ({len(seen_ch)}) != thư mục ch/ ({len(expected_ch_files)})"
        )
    if seen_vi != expected_vi_files:
        raise ValueError(
            f"[{book_name}] image_map VI ({len(seen_vi)}) != thư mục vi/ ({len(expected_vi_files)})"
        )
    if paired_missing_ch != expected_missing_ch_files:
        raise ValueError(
            f"[{book_name}] image_map (vi=[]) != thư mục missing/ch/"
        )

    return folder_pages


def clean_book_dir(book_dir: Path) -> None:
    """Dọn các thư mục phân trang và file map/updated cũ bên trong book_dir trước khi cắt mới."""
    if not book_dir.exists():
        return
    for sub in ALL_MANAGED_SUBDIRS:
        sub_path = book_dir / sub
        if sub_path.exists():
            shutil.rmtree(sub_path)
    for pattern in ("*_image_map.json", "*_updated.pdf"):
        for f in book_dir.glob(pattern):
            f.unlink()


def validate_prepared_book(book_dir: Path, cfg: Dict[str, Any]) -> List[str]:
    """Kiểm định đầu ra trên đĩa theo đúng quy định hình ảnh & image_map của Rules v2.4."""
    errors: List[str] = []
    book_name = cfg["book_name"]
    expected = int(cfg["expected_pages"])
    folder_pages = validate_book_config(cfg)

    seen_primary_files: Dict[str, str] = {}
    for fname in PRIMARY_FOLDERS:
        fdir = book_dir / fname
        expected_names = {format_page_filename(book_name, p, expected) for p in folder_pages[fname]}
        if not expected_names:
            continue
        if not fdir.is_dir():
            errors.append(f"Thiếu thư mục {fdir}")
            continue
        actual_files = {p.name for p in fdir.glob("*.jpg")}
        non_jpg = [p.name for p in fdir.iterdir() if p.is_file() and p.suffix.lower() != ".jpg"]
        if non_jpg:
            errors.append(f"Thư mục {fname}/ chứa file không phải .jpg: {non_jpg[:5]}")
        if actual_files != expected_names:
            missing = sorted(expected_names - actual_files)
            extra = sorted(actual_files - expected_names)
            errors.append(f"Thư mục {fname}/ sai tập ảnh (thiếu={missing[:5]}, dư={extra[:5]})")

        for name in sorted(actual_files):
            if name in seen_primary_files:
                errors.append(f"Ảnh {name} bị trùng giữa {seen_primary_files[name]}/ và {fname}/")
            seen_primary_files[name] = fname
            img_path = fdir / name
            try:
                with Image.open(img_path) as im:
                    w, h = im.size
                    if w >= h:
                        errors.append(f"Ảnh {fname}/{name} có hướng ngang ({w}x{h})")
            except Exception as exc:
                errors.append(f"Không đọc được ảnh {fname}/{name}: {exc}")

    # Kiểm tra missing/ch
    mch_expected = {format_page_filename(book_name, p, expected) for p in folder_pages["missing/ch"]}
    mch_dir = book_dir / "missing" / "ch"
    if mch_expected:
        if not mch_dir.is_dir():
            errors.append(f"Thiếu thư mục {mch_dir}")
        else:
            mch_actual = {p.name for p in mch_dir.glob("*.jpg")}
            if mch_actual != mch_expected:
                errors.append(f"Thư mục missing/ch/ không khớp: actual={sorted(mch_actual)} vs expected={sorted(mch_expected)}")

    # Kiểm tra image_map.json qua hàm chính thức của ocr_nom_align
    map_path = book_dir / f"{book_name}_image_map.json"
    if not map_path.is_file():
        errors.append(f"Thiếu file {map_path}")
    else:
        pairs = read_image_map(map_path)
        ch_dir = book_dir / "ch"
        vi_dir = book_dir / "vi"
        map_missing_ch: Set[str] = set()
        for p in pairs:
            for ch_name in p.ch:
                if not (ch_dir / ch_name).is_file():
                    errors.append(f"image_map tham chiếu CH không tồn tại: {ch_name}")
            for vi_name in p.vi:
                if not (vi_dir / vi_name).is_file():
                    errors.append(f"image_map tham chiếu VI không tồn tại: {vi_name}")
            if not p.vi:
                map_missing_ch.update(p.ch)
        if map_missing_ch != mch_expected:
            errors.append(f"missing/ch/ ({sorted(mch_expected)}) != cặp vi=[] trong image_map ({sorted(map_missing_ch)})")

    return errors


def prepare_book(
    key: str, cfg: Dict[str, Any], out_root: Path, dpi: int = 72
) -> Dict[str, Any]:
    """Chuẩn bị toàn bộ thư mục ảnh, _updated.pdf (nếu có) và _image_map.json cho một tập sách."""
    book_name = cfg["book_name"]
    source_pdf = Path(cfg["source_pdf"])
    expected_pages = int(cfg["expected_pages"])
    if not source_pdf.is_file():
        raise FileNotFoundError(f"Không tìm thấy PDF gốc: {source_pdf}")

    folder_pages = validate_book_config(cfg)

    book_dir = out_root / book_name
    clean_book_dir(book_dir)
    book_dir.mkdir(parents=True, exist_ok=True)

    # Nếu cần loại trang trùng -> tạo <Tên sách>_updated.pdf bằng qpdf (không nén lại mất chất lượng)
    effective_pdf = source_pdf
    updated_pdf_path: Optional[Path] = None
    qpdf_spec = cfg.get("updated_pdf_qpdf_pages")
    if qpdf_spec:
        updated_pdf_path = book_dir / f"{book_name}_updated.pdf"
        print(f"[{key}] Tạo {updated_pdf_path.name} từ {source_pdf.name} (pages={qpdf_spec})...")
        subprocess.run(
            ["qpdf", str(source_pdf), "--pages", ".", str(qpdf_spec), "--", str(updated_pdf_path)],
            check=True,
            capture_output=True,
        )
        effective_pdf = updated_pdf_path

    actual_pages = get_pdf_page_count(effective_pdf)
    if actual_pages != expected_pages:
        raise RuntimeError(
            f"[{key}] Số trang PDF hiệu lực ({actual_pages}) != expected_pages ({expected_pages})"
        )

    # Tạo ánh xạ page_no -> danh sách thư mục đích
    page_to_primary: Dict[int, str] = {}
    for fname in PRIMARY_FOLDERS:
        for p in folder_pages[fname]:
            page_to_primary[p] = fname
        if folder_pages[fname]:
            (book_dir / fname).mkdir(parents=True, exist_ok=True)

    missing_ch_set = set(folder_pages["missing/ch"])
    if missing_ch_set:
        (book_dir / "missing" / "ch").mkdir(parents=True, exist_ok=True)

    # Cắt ảnh trong thư mục tạm rồi di chuyển trực tiếp vào thư mục đích (tránh nhân đôi dung lượng đĩa)
    print(f"[{key}] Đang cắt {actual_pages} trang từ {effective_pdf.name} ở {dpi} DPI...")
    with tempfile.TemporaryDirectory() as tmp:
        tmp_dir = Path(tmp)
        subprocess.run(
            ["pdftoppm", "-jpeg", "-r", str(dpi), str(effective_pdf), str(tmp_dir / "p")],
            check=True,
            capture_output=True,
        )
        rendered = sorted(tmp_dir.glob("p-*.jpg"))
        if len(rendered) != actual_pages:
            raise RuntimeError(
                f"[{key}] pdftoppm xuất {len(rendered)} ảnh, kỳ vọng {actual_pages}"
            )

        for idx, src_img in enumerate(rendered, 1):
            target_folder = page_to_primary[idx]
            dest_name = format_page_filename(book_name, idx, actual_pages)
            dest_path = book_dir / target_folder / dest_name
            shutil.move(str(src_img), str(dest_path))
            if idx in missing_ch_set:
                shutil.copy2(str(dest_path), str(book_dir / "missing" / "ch" / dest_name))

    # Xuất <Tên sách>_image_map.json
    pairs = build_image_map_pairs(book_name, cfg["pair_segments"], actual_pages)
    map_path = book_dir / f"{book_name}_image_map.json"
    map_path.write_text(json.dumps({"pairs": pairs}, ensure_ascii=False, indent=2), encoding="utf-8")

    # Kiểm định tự động toàn bộ kết quả vừa tạo
    val_errors = validate_prepared_book(book_dir, cfg)
    if val_errors:
        raise RuntimeError(f"[{key}] Kiểm định thất bại với {len(val_errors)} lỗi: {val_errors[:5]}")

    counts = {fname: len(folder_pages[fname]) for fname in (*PRIMARY_FOLDERS, "missing/ch") if folder_pages[fname]}
    print(f"[{key}] Hoàn tất & kiểm định OK: tổng={actual_pages} trang | {counts} | pairs={len(pairs)}")
    return {
        "key": key,
        "book_name": book_name,
        "book_dir": str(book_dir),
        "updated_pdf": str(updated_pdf_path) if updated_pdf_path else None,
        "image_map": str(map_path),
        "total_pages": actual_pages,
        "pairs_count": len(pairs),
        "folder_counts": counts,
    }


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Chuẩn bị đầy đủ ảnh 72 DPI, thư mục chuẩn Rules v2.4, _updated.pdf và _image_map.json cho Tập 1 & Tập 2."
    )
    parser.add_argument("--config", type=str, default="configs/books_structure.json", help="File cấu hình phân trang")
    parser.add_argument("--book", type=str, default="all", choices=["tap1", "tap2", "all"], help="Tập cần chạy")
    parser.add_argument("--dpi", type=int, default=72, help="Độ phân giải cắt ảnh (mặc định 72 DPI ~ 1067x1513)")
    parser.add_argument("--out-root", type=str, default="data/processed", help="Thư mục gốc xuất dữ liệu")
    parser.add_argument("--validate-only", action="store_true", help="Chỉ kiểm tra config và dữ liệu đã cắt trên đĩa")
    args = parser.parse_args()

    all_cfg = json.loads(Path(args.config).read_text(encoding="utf-8"))
    keys = ["tap1", "tap2"] if args.book == "all" else [args.book]
    out_root = Path(args.out_root)

    for k in keys:
        cfg = all_cfg[k]
        validate_book_config(cfg)
        if args.validate_only:
            book_dir = out_root / cfg["book_name"]
            if book_dir.exists():
                errs = validate_prepared_book(book_dir, cfg)
                if errs:
                    raise SystemExit(f"[{k}] Validation errors: {errs}")
                print(f"[{k}] Config & existing directory OK ({book_dir})")
            else:
                print(f"[{k}] Config OK (chưa cắt ảnh tại {book_dir})")
        else:
            prepare_book(k, cfg, out_root=out_root, dpi=args.dpi)


if __name__ == "__main__":
    main()
