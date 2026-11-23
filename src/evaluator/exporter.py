import csv
import json
import re
import unicodedata
from typing import List, Dict, Any, Tuple, Optional
from openpyxl import Workbook
from openpyxl.styles import Font, PatternFill, Alignment, Border, Side
from openpyxl.cell.rich_text import CellRichText, TextBlock
from openpyxl.cell.text import InlineFont
from openpyxl.styles.colors import Color

PUNCT_CHARS = set("。，、！？：；「」『』（）()[].,!?:;\"' \t\n\r")
VARIATION_SELECTOR_RE = re.compile(r"[\uFE00-\uFE0F\U000E0100-\U000E01EF]")
ERROR_REQUIRED_KEYS = frozenset({"nom_pos", "nom_sub_text", "vi_pos", "vi_sub_text", "type"})
WARN_ALLOWED_KEYS = ERROR_REQUIRED_KEYS | frozenset({"reviewed", "suggest", "suggest_by"})

class AlignmentExporter:
    @staticmethod
    def count_nom_chars(text: str) -> int:
        """Đếm số chữ Hán/Nôm (bỏ qua [MASK], dấu câu và khoảng trắng)."""
        if not text:
            return 0
        cleaned = text.replace("[MASK]", "")
        return sum(
            1 for c in cleaned 
            if c not in PUNCT_CHARS and not unicodedata.category(c).startswith(('P', 'Z', 'C'))
        )

    @staticmethod
    def count_vi_syllables(text: str) -> int:
        """Đếm số âm tiết Quốc ngữ (tách bởi khoảng trắng hoặc gạch nối, chứa ít nhất 1 chữ cái)."""
        if not text:
            return 0
        tokens = re.split(r"[\s\-–—]+", text)
        return sum(1 for tok in tokens if any(c.isalpha() for c in tok))

    @classmethod
    def _validate_side_pos(
        cls,
        text: str,
        pos_list: Any,
        sub_text: Any,
        side_label: str,
        elem_idx: int,
        all_intervals: List[Tuple[int, int]],
        errors: List[str],
    ) -> None:
        """Kiểm tra một vế (nom hoặc vi) của một phần tử text_diff."""
        pos_key = f"{side_label}_pos"
        sub_key = f"{side_label}_sub_text"
        if not isinstance(pos_list, list) or not isinstance(sub_text, str):
            errors.append(f"diff element {elem_idx}: {pos_key} phải là list và {sub_key} phải là str")
            return

        mask_spans = [(m.start(), m.end()) for m in re.finditer(r"\[MASK\]", text)]
        actual_parts = []
        last_end = -1
        for rng in pos_list:
            if not (isinstance(rng, list) and len(rng) == 2 and all(type(x) is int for x in rng)):
                errors.append(f"diff element {elem_idx}: {pos_key} khoảng {rng!r} không hợp lệ")
                return
            s, e = rng
            if not (0 <= s < e <= len(text)):
                errors.append(
                    f"diff element {elem_idx}: {pos_key} [{s}, {e}] vượt giới hạn chuỗi (len={len(text)})"
                )
                return
            if s < last_end:
                errors.append(
                    f"diff element {elem_idx}: {pos_key} các khoảng không tăng dần/chồng lấn"
                )
                return
            last_end = e
            if text[s] in PUNCT_CHARS or text[s].isspace():
                errors.append(
                    f"diff element {elem_idx}: {pos_key} [{s}, {e}] bắt đầu bằng dấu câu/khoảng trắng: '{text[s]}'"
                )
            if text[e - 1] in PUNCT_CHARS or text[e - 1].isspace():
                errors.append(
                    f"diff element {elem_idx}: {pos_key} [{s}, {e}] kết thúc bằng dấu câu/khoảng trắng: '{text[e - 1]}'"
                )
            if "[MASK]" in text[s:e] or any(s < me and e > ms for ms, me in mask_spans):
                errors.append(
                    f"diff element {elem_idx}: {pos_key} [{s}, {e}] không được chứa hoặc chồng lên [MASK]"
                )
            all_intervals.append((s, e))
            actual_parts.append(text[s:e])

        actual_sub = "".join(actual_parts)
        if actual_sub != sub_text:
            errors.append(
                f"diff element {elem_idx}: {sub_key} '{sub_text}' không khớp substring '{actual_sub}'"
            )

    @classmethod
    def validate_row(cls, row: Dict[str, Any]) -> List[str]:
        """
        Kiểm tra tính hợp lệ của một hàng dữ liệu theo Quy định v2.4.
        Trả về danh sách các lỗi nếu có (rỗng nếu hoàn toàn hợp lệ).
        """
        errors = []
        img_id = row.get("img_id", "")
        sentence_id = row.get("sentence_id", "")
        ch_raw = row.get("ch_txt", "")
        vi_raw = row.get("vi_txt", "")
        ch_txt = unicodedata.normalize("NFC", ch_raw)
        vi_txt = unicodedata.normalize("NFC", vi_raw)
        text_diff = row.get("text_diff")

        # 1. Không cho phép hàng rỗng một vế hoặc chứa variation selector
        if not ch_txt.strip() or not vi_txt.strip():
            errors.append("ch_txt và vi_txt đều phải khác rỗng (v2.4 cấm hàng khuyết một vế)")
        if VARIATION_SELECTOR_RE.search(ch_raw):
            errors.append("ch_txt chứa ký tự chọn dạng Unicode (variation selector U+FE00..U+FE0F/E0100..)")

        # 2. Kiểm tra format sentence_id
        base_img = img_id.replace(".jpg", "").replace(".png", "")
        if not sentence_id.startswith(f"{base_img}."):
            errors.append(f"sentence_id '{sentence_id}' không bắt đầu bằng '{base_img}.'")

        # 3. Kiểm tra text_diff nếu khác None
        if text_diff is not None:
            if not isinstance(text_diff, list):
                errors.append(f"text_diff phải là list hoặc None (cho null), nhận được {type(text_diff)}")
                return errors

            all_nom_intervals: List[Tuple[int, int]] = []
            all_vi_intervals: List[Tuple[int, int]] = []

            for idx, item in enumerate(text_diff):
                if not isinstance(item, dict):
                    errors.append(f"diff element {idx} không phải là dict")
                    continue

                dtype = item.get("type")
                if dtype not in ("error", "warn"):
                    errors.append(f"diff element {idx} type '{dtype}' không hợp lệ (phải là 'error' hoặc 'warn')")
                    continue

                keys = set(item.keys())
                if dtype == "error":
                    if keys != ERROR_REQUIRED_KEYS:
                        errors.append(
                            f"diff element {idx}: phần tử 'error' phải có đúng các khoá {sorted(ERROR_REQUIRED_KEYS)}, nhận được {sorted(keys)}"
                        )
                        if not ERROR_REQUIRED_KEYS <= keys:
                            continue
                else:
                    if not ERROR_REQUIRED_KEYS <= keys or (keys - WARN_ALLOWED_KEYS):
                        errors.append(
                            f"diff element {idx}: phần tử 'warn' chứa khoá không hợp lệ: {sorted(keys)}"
                        )
                        if not ERROR_REQUIRED_KEYS <= keys:
                            continue
                    if "reviewed" in item and (type(item["reviewed"]) is not int or item["reviewed"] not in (0, 1)):
                        errors.append(
                            f"diff element {idx}: 'reviewed' phải là số nguyên 0 hoặc 1, nhận được {item['reviewed']!r}"
                        )
                    if ("suggest" in item) != ("suggest_by" in item):
                        errors.append(f"diff element {idx}: 'suggest' và 'suggest_by' phải đi cùng nhau")
                    if "suggest" in item:
                        sg = item["suggest"]
                        if not (isinstance(sg, str) and len(sg) == 1):
                            errors.append(f"diff element {idx}: 'suggest' phải dài đúng 1 ký tự, nhận được {sg!r}")
                        if item.get("suggest_by") not in ("fallback", "similar"):
                            errors.append(
                                f"diff element {idx}: 'suggest_by' phải là 'fallback' hoặc 'similar', nhận được {item.get('suggest_by')!r}"
                            )
                        npos = item.get("nom_pos")
                        if not (
                            isinstance(npos, list) and len(npos) == 1
                            and isinstance(npos[0], list) and len(npos[0]) == 2
                            and all(type(x) is int for x in npos[0])
                            and npos[0][1] - npos[0][0] == 1
                        ):
                            errors.append(
                                f"diff element {idx}: phần tử có 'suggest' phải có nom_pos gồm đúng 1 khoảng dài 1"
                            )

                nom_pos = item.get("nom_pos", [])
                nom_sub = unicodedata.normalize("NFC", item.get("nom_sub_text", ""))
                vi_pos = item.get("vi_pos", [])
                vi_sub = unicodedata.normalize("NFC", item.get("vi_sub_text", ""))

                if not nom_pos and not vi_pos:
                    errors.append(f"diff element {idx}: cả nom_pos và vi_pos đều rỗng")

                cls._validate_side_pos(ch_txt, nom_pos, nom_sub, "nom", idx, all_nom_intervals, errors)
                cls._validate_side_pos(vi_txt, vi_pos, vi_sub, "vi", idx, all_vi_intervals, errors)

            # Kiểm tra chồng lấn khoảng pos giữa các phần tử
            all_nom_intervals.sort()
            for i in range(len(all_nom_intervals) - 1):
                if all_nom_intervals[i][1] > all_nom_intervals[i + 1][0]:
                    errors.append(f"Chồng lấn khoảng nom_pos: {all_nom_intervals[i]} và {all_nom_intervals[i + 1]}")

            all_vi_intervals.sort()
            for i in range(len(all_vi_intervals) - 1):
                if all_vi_intervals[i][1] > all_vi_intervals[i + 1][0]:
                    errors.append(f"Chồng lấn khoảng vi_pos: {all_vi_intervals[i]} và {all_vi_intervals[i + 1]}")

        return errors

    @classmethod
    def evaluate_dataset(cls, rows: List[Dict[str, Any]]) -> Dict[str, Any]:
        """
        Tính toán các chỉ số đánh giá chính thức theo Rubric v2.1:
        - Độ tương đồng (%)
        - Tỷ lệ chữ vàng (warn ratio)
        - Tỷ lệ dòng null (null ratio)
        """
        total_rows = len(rows)
        null_rows = 0
        total_nom_chars_all = 0
        total_yellow_nom_chars = 0
        total_scored_nom_chars = 0
        total_unmatched_error_chars = 0

        for row in rows:
            ch_txt = unicodedata.normalize("NFC", row.get("ch_txt", ""))
            vi_txt = unicodedata.normalize("NFC", row.get("vi_txt", ""))
            text_diff = row.get("text_diff")

            row_nom_chars = cls.count_nom_chars(ch_txt)
            total_nom_chars_all += row_nom_chars

            if text_diff is None:
                null_rows += 1
                continue

            # Hàng có text_diff (dịch âm 1-1)
            row_yellow_chars = 0
            row_error_chars = 0

            for diff in text_diff:
                dtype = diff.get("type", "error")
                nom_pos = diff.get("nom_pos", [])
                vi_pos = diff.get("vi_pos", [])

                nom_sub = "".join(ch_txt[s:e] for s, e in nom_pos)
                vi_sub = "".join(vi_txt[s:e] for s, e in vi_pos)

                nom_sub_count = cls.count_nom_chars(nom_sub)
                vi_sub_count = cls.count_vi_syllables(vi_sub)

                if dtype == "warn":
                    row_yellow_chars += nom_sub_count
                elif dtype == "error":
                    # Rubric: Lấy giá trị lớn hơn giữa số chữ Nôm và số âm tiết Quốc ngữ
                    diff_unmatched = max(nom_sub_count, vi_sub_count)
                    row_error_chars += diff_unmatched

            total_yellow_nom_chars += row_yellow_chars
            total_unmatched_error_chars += row_error_chars

            # Mẫu số: Tổng số chữ Nôm trừ đi chữ vàng và MASK
            scored_nom_in_row = max(0, row_nom_chars - row_yellow_chars)
            total_scored_nom_chars += scored_nom_in_row

        # Tính toán phần trăm
        null_ratio = (null_rows / max(1, total_rows)) * 100.0
        yellow_ratio = (total_yellow_nom_chars / max(1, total_nom_chars_all)) * 100.0
        
        if total_scored_nom_chars > 0:
            similarity = max(0.0, (1.0 - (total_unmatched_error_chars / total_scored_nom_chars)) * 100.0)
        else:
            similarity = None

        return {
            "total_rows": total_rows,
            "transliterated_rows": total_rows - null_rows,
            "null_rows": null_rows,
            "null_ratio_percent": round(null_ratio, 2),
            "total_nom_chars": total_nom_chars_all,
            "yellow_nom_chars": total_yellow_nom_chars,
            "yellow_ratio_percent": round(yellow_ratio, 2),
            "total_scored_nom_chars": total_scored_nom_chars,
            "unmatched_error_chars": total_unmatched_error_chars,
            "similarity_percent": round(similarity, 2) if similarity is not None else None,
            "evaluation_applicable": total_scored_nom_chars > 0,
            "is_passing": similarity is not None and similarity >= 95.0
        }

    @classmethod
    def export_csv(cls, rows: List[Dict[str, Any]], output_path: str):
        """
        Xuất file <Tên sách>.csv theo đúng chuẩn Rubric:
        - UTF-8 with BOM (utf-8-sig)
        - 5 cột: img_id, sentence_id, ch_txt, vi_txt, text_diff
        - text_diff là JSON string hoặc chuỗi 'null'
        """
        fieldnames = ["img_id", "sentence_id", "ch_txt", "vi_txt", "text_diff"]
        with open(output_path, "w", encoding="utf-8-sig", newline="") as f:
            writer = csv.DictWriter(f, fieldnames=fieldnames, quoting=csv.QUOTE_MINIMAL)
            writer.writeheader()
            for r in rows:
                diff = r.get("text_diff")
                diff_str = "null" if diff is None else json.dumps(diff, ensure_ascii=False)
                writer.writerow({
                    "img_id": r.get("img_id", ""),
                    "sentence_id": r.get("sentence_id", ""),
                    "ch_txt": unicodedata.normalize("NFC", r.get("ch_txt", "")),
                    "vi_txt": unicodedata.normalize("NFC", r.get("vi_txt", "")),
                    "text_diff": diff_str
                })

    @classmethod
    def _build_rich_text(cls, text: str, diffs: Optional[List[Dict[str, Any]]], pos_key: str) -> Any:
        """Tạo CellRichText đa màu theo chuẩn mở rộng của openpyxl."""
        if not text or not diffs:
            return text

        intervals = []
        for diff in diffs:
            dtype = diff.get("type", "error")
            for s, e in diff.get(pos_key, []):
                intervals.append((s, e, dtype))

        if not intervals:
            return text

        intervals.sort(key=lambda x: x[0])
        font_black = InlineFont(color=Color(rgb="00000000"))
        font_red = InlineFont(color=Color(rgb="00FF0000"))
        font_yellow = InlineFont(color=Color(rgb="00D99A00")) # Chuẩn màu vàng v2.4

        blocks = []
        curr = 0
        for s, e, dtype in intervals:
            if s > curr:
                blocks.append(TextBlock(font_black, text[curr:s]))
            f = font_yellow if dtype == "warn" else font_red
            blocks.append(TextBlock(f, text[s:e]))
            curr = e

        if curr < len(text):
            blocks.append(TextBlock(font_black, text[curr:]))

        return CellRichText(blocks)

    @classmethod
    def export_xlsx(cls, rows: List[Dict[str, Any]], output_path: str):
        """
        Xuất file <Tên sách>.xlsx với định dạng 3 màu theo Quy định v2.4:
        - Đen (000000): Khớp nghĩa
        - Đỏ (FF0000): Sai (error)
        - Vàng (D99A00): Cảnh báo / Tên riêng (warn)
        """
        wb = Workbook()
        ws = wb.active
        ws.title = "align"

        # Định dạng Header
        headers = ["img_id", "sentence_id", "ch_txt", "vi_txt", "text_diff"]
        ws.append(headers)

        header_font = Font(name="Arial", size=11, bold=True, color="FFFFFF")
        header_fill = PatternFill(start_color="1F497D", end_color="1F497D", fill_type="solid")
        header_align = Alignment(horizontal="center", vertical="center", wrap_text=True)

        for col_idx in range(1, 6):
            cell = ws.cell(row=1, column=col_idx)
            cell.font = header_font
            cell.fill = header_fill
            cell.alignment = header_align

        # Thêm dữ liệu
        for row_idx, r in enumerate(rows, start=2):
            img_id = r.get("img_id", "")
            sent_id = r.get("sentence_id", "")
            ch_txt = unicodedata.normalize("NFC", r.get("ch_txt", ""))
            vi_txt = unicodedata.normalize("NFC", r.get("vi_txt", ""))
            diff = r.get("text_diff")

            diff_str = "null" if diff is None else json.dumps(diff, ensure_ascii=False)

            # Cell values
            ws.cell(row=row_idx, column=1, value=img_id)
            ws.cell(row=row_idx, column=2, value=sent_id)
            
            # Format ch_txt và vi_txt với CellRichText
            if diff is not None:
                ws.cell(row=row_idx, column=3, value=cls._build_rich_text(ch_txt, diff, "nom_pos"))
                ws.cell(row=row_idx, column=4, value=cls._build_rich_text(vi_txt, diff, "vi_pos"))
            else:
                ws.cell(row=row_idx, column=3, value=ch_txt)
                ws.cell(row=row_idx, column=4, value=vi_txt)

            ws.cell(row=row_idx, column=5, value=diff_str)

        # Căn chỉnh kích thước cột & wrap text
        column_widths = {1: 30, 2: 32, 3: 45, 4: 45, 5: 35}
        for col_idx, width in column_widths.items():
            ws.column_dimensions[chr(64 + col_idx)].width = width

        # Freeze hàng đầu tiên
        ws.freeze_panes = "A2"

        wb.save(output_path)

