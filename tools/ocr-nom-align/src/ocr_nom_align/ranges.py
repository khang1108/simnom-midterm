"""The author's declaration of which rows are translations by meaning (`null` text_diff) in a book that also has
phonetic parts. JSON: `{"meaning": [{"from_image": ..., "to_image": ...} | {"from_sentence": ..., "to_sentence": ...}]}`.
Ranges include both ends and follow the reading order of the book, not the file names; sentence ids are those of
the final rows (after merges), so declare them again when the merges change."""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path

KEYS = ("meaning",)


class RangeError(ValueError):
    pass


@dataclass
class Ranges:
    meaning: list[dict]

    @classmethod
    def load(cls, path: str | Path) -> Ranges:
        try:
            data = json.loads(Path(path).read_text(encoding="utf-8-sig"))
        except (OSError, json.JSONDecodeError) as exc:
            raise RangeError(f"ranges file {path}: {exc}") from None
        if not isinstance(data, dict) or set(data) - set(KEYS):
            raise RangeError(f"ranges file {path}: expected an object with the key(s) {KEYS}")
        out = []
        for r in data.get("meaning", []):
            ok_i = isinstance(r, dict) and set(r) == {"from_image", "to_image"}
            ok_s = isinstance(r, dict) and set(r) == {"from_sentence", "to_sentence"}
            if not (ok_i or ok_s):
                raise RangeError(
                    f"bad range {r!r}: use from_image + to_image, or from_sentence + to_sentence"
                )
            out.append(r)
        return cls(out)

    def resolve(self, rows: list, img_order: list[str]) -> set[int]:
        """Indexes of the rows in a `meaning` range. `rows` have `img_id` and `sentence_id`."""
        hit: set[int] = set()
        by_img = {im: k for k, im in enumerate(img_order)}
        by_sid = {}
        for k, r in enumerate(rows):
            by_sid.setdefault(r.sentence_id, k)
        for r in self.meaning:
            if "from_image" in r:
                for key in ("from_image", "to_image"):
                    if r[key] not in by_img:
                        raise RangeError(f"ranges: image {r[key]!r} is not in the book")
                a, b = by_img[r["from_image"]], by_img[r["to_image"]]
                if a > b:
                    raise RangeError(
                        f"ranges: {r['from_image']} is read after {r['to_image']} (reading order)"
                    )
                span = set(img_order[a : b + 1])
                hit |= {k for k, row in enumerate(rows) if row.img_id in span}
            else:
                for key in ("from_sentence", "to_sentence"):
                    if r[key] not in by_sid:
                        raise RangeError(f"ranges: sentence id {r[key]!r} is not a row of the book")
                a, b = by_sid[r["from_sentence"]], by_sid[r["to_sentence"]]
                if a > b:
                    raise RangeError(
                        f"ranges: {r['from_sentence']} comes after {r['to_sentence']} in the rows"
                    )
                hit |= set(range(a, b + 1))
        return hit


__all__ = ["RangeError", "Ranges"]
