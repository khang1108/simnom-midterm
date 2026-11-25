import csv
import json
import sys
import unicodedata
from pathlib import Path

PH = "〓"
PUA_FILE = Path("configs/pua_to_unicode.csv")


def _labels(path: Path) -> dict:
    if not path.exists():
        return {}
    out = {}
    for line in path.read_text(encoding="utf-8").splitlines():
        img, boxes = line.split("\t", 1)
        out[img.split("/")[-1]] = [b["transcription"] for b in json.loads(boxes)]
    return out


def build(book_dir: Path, book_name: str) -> list:
    label, chars = _labels(book_dir / "ch" / "Label.txt"), _labels(book_dir / "ch" / "Label_char.txt")
    order = [img for p in json.loads((book_dir / f"{book_name}_image_map.json").read_text(encoding="utf-8"))["pairs"] for img in p["ch"]]
    order += sorted(set(label) - set(order))
    lab = []
    for img in order:
        char_idx = [i for i, t in enumerate(chars.get(img, [])) if t == PH]
        k = 0
        for bi, t in enumerate(label.get(img, [])):
            for pos, c in enumerate(t):
                if c == PH:
                    lab.append({"img_id": img, "box_index": bi, "pos": pos, "char_box_index": char_idx[k] if img in chars else None})
                    k += 1
    rows = list(csv.DictReader((book_dir / f"{book_name}.csv").open(encoding="utf-8-sig")))
    ali = [(r["img_id"], {"sentence_id": r["sentence_id"], "pos": pos}) for r in rows for pos, c in enumerate(r["ch_txt"]) if c == PH]
    if len(lab) != len(ali):
        raise ValueError(f"Số 〓 trong Label.txt ({len(lab)}) khác trong ch_txt ({len(ali)})")
    known = [r for r in csv.DictReader(PUA_FILE.open(encoding="utf-8")) if r["unicode"] == "U+3013"] if PUA_FILE.exists() else []
    ids, note = (known[0]["ids"] or None, f"Kim Hán Nôm PUA {known[0]['pua']}, âm {known[0]['reading']}") if len(known) == 1 else (None, "")
    out = []
    for lb, (row_img, al) in zip(lab, ali):
        pairs = [(lb, al)] if lb["img_id"] == row_img else [(lb, None), (None, al)]
        out += [{"label": a, "align": b, "unicode": None, "ids": ids, "note": note} for a, b in pairs]
    return out


def check(book_dir: Path, book_name: str, items: list) -> list:
    label, chars = _labels(book_dir / "ch" / "Label.txt"), _labels(book_dir / "ch" / "Label_char.txt")
    rows = {r["sentence_id"]: r for r in csv.DictReader((book_dir / f"{book_name}.csv").open(encoding="utf-8-sig"))}
    err, seen_l, seen_a = [], set(), set()
    for i, it in enumerate(items):
        lb, al, u, ids = it["label"], it["align"], it["unicode"], it["ids"]
        if lb is None and al is None:
            err.append(f"#{i}: label và align cùng null")
        if lb:
            if label[lb["img_id"]][lb["box_index"]][lb["pos"]] != PH:
                err.append(f"#{i}: label.pos không phải 〓")
            if lb["char_box_index"] is not None and chars[lb["img_id"]][lb["char_box_index"]] != PH:
                err.append(f"#{i}: char_box_index không chỉ chứa 〓")
            key = (lb["img_id"], lb["box_index"], lb["pos"])
            err += [f"#{i}: trùng label {key}"] if key in seen_l else []
            seen_l.add(key)
        if al:
            r = rows[al["sentence_id"]]
            if r["ch_txt"][al["pos"]] != PH:
                err.append(f"#{i}: align.pos không phải 〓")
            if r["text_diff"] != "null" and not any(e["type"] == "error" and any(a <= al["pos"] < b for a, b in e["nom_pos"]) for e in json.loads(r["text_diff"])):
                err.append(f"#{i}: 〓 không nằm trong phần tử error")
            key = (al["sentence_id"], al["pos"])
            err += [f"#{i}: trùng align {key}"] if key in seen_a else []
            seen_a.add(key)
        if u is not None:
            cp = int(u[2:], 16) if u.startswith("U+") and u[2:] == u[2:].upper() and 4 <= len(u) - 2 <= 6 else -1
            if cp < 0 or cp == 0x3013 or 0xFE00 <= cp <= 0xFE0F or 0xE0100 <= cp <= 0xE01EF or unicodedata.category(chr(cp)) == "Co":
                err.append(f"#{i}: unicode không hợp lệ {u}")
        if ids is not None and any(c == PH or not (0x2FF0 <= ord(c) <= 0x2FFF or ord(c) == 0x31EF or unicodedata.category(c) in ("Lo", "Co")) for c in ids):
            err.append(f"#{i}: ids không hợp lệ {ids}")
    n_label = sum(t.count(PH) for ts in label.values() for t in ts)
    n_char = sum(t.count(PH) for ts in chars.values() for t in ts)
    n_csv = sum(r["ch_txt"].count(PH) for r in rows.values())
    if n_label != sum(it["label"] is not None for it in items):
        err.append(f"Label.txt có {n_label} 〓 nhưng số phần tử có label khác")
    if n_csv != sum(it["align"] is not None for it in items):
        err.append(f"ch_txt có {n_csv} 〓 nhưng số phần tử có align khác")
    if n_char != sum(it["label"] is not None and it["label"]["char_box_index"] is not None for it in items):
        err.append(f"Label_char.txt có {n_char} 〓 nhưng số phần tử có char_box_index khác")
    return err


def write(book_dir: Path, book_name: str) -> int:
    out = book_dir / f"{book_name}_placeholder_map.json"
    items = build(book_dir, book_name)
    if not items:
        out.unlink(missing_ok=True)
        return 0
    errors = check(book_dir, book_name, items)
    if errors:
        raise ValueError(f"placeholder_map không hợp lệ: {errors[:5]}")
    out.write_text(json.dumps({"placeholders": items}, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return len(items)


if __name__ == "__main__":
    d = Path(sys.argv[1])
    print(f"placeholder_map: {write(d, d.name)} phần tử")
