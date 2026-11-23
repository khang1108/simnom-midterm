"""Reading table: which Vietnamese syllables read a Sino-Nom character.

Sources, any number, merged (each file is the contract; no other package is imported). Three levels of support:

1. first class: dictionary entries, `.jsonl` (`entries/<source>.jsonl`, plain or `.gz`), or a folder of them, one JSON
   entry per line; a folder is found by itself and a bad line is reported with its number;
2. second class: the other files of the same dictionary, `lab_dict.csv` (`char,syllable[,note]`) and `lexicon.sqlite`
   (table `reading_table(head, syllable, ...)`, opened read-only);
3. third class: any other table you have, best effort: a `.csv` / `.tsv` (`char,syllable` or `char<TAB>syl1,syl2`) or a `.json`
   (`{"天": ["thiên", "trời"]}`).

A character is *known* when any source lists a reading for it. Only single characters are kept.
"""

from __future__ import annotations

import csv
import gzip
import json
import re
import sqlite3
import unicodedata
from collections.abc import Iterable, Mapping
from pathlib import Path

from .tokens import nfc, syllable_key

JSONL_SUFFIXES = (".jsonl", ".jsonl.gz")
VIETNAMESE_SYSTEMS = (
    "qn",
    "hv",
    "nom",
)  # the reading systems that are Vietnamese; pinyin, on, hangul ... are not
_SPLIT = re.compile(r"[,\s]+")
_VARIATION_SELECTORS = {*range(0xFE00, 0xFE10), *range(0xE0100, 0xE01F0)}


class TableError(Exception):
    pass


def is_jsonl(path: Path) -> bool:
    return path.name.lower().endswith(JSONL_SUFFIXES)


def entry_files(folder: Path) -> list[Path]:
    """The entry files of a dictionary data folder: `*.jsonl` in it, else in its `entries/` (or `data/entries/`)
    subfolder. `manifest*.jsonl` crawl logs and the `rejected/` folder are not entries."""
    for d in (folder, folder / "entries", folder / "data" / "entries"):
        found = sorted(
            f
            for f in d.glob("*")
            if f.is_file() and is_jsonl(f) and not f.name.startswith("manifest")
        )
        if found:
            return found
    return []


def _one_char(text: str) -> str:
    """NFC text without variation selectors (a variant glyph reads like its base character)."""
    return "".join(c for c in nfc(text) if ord(c) not in _VARIATION_SELECTORS)


class ReadingTable:
    def __init__(
        self, direct: Mapping[str, Iterable[str]] | None = None, *, tone_sensitive: bool = False
    ) -> None:
        self.tone_sensitive = tone_sensitive
        self._map: dict[str, set[str]] = {}
        self.sources: list[str] = []
        for ch, rs in (direct or {}).items():
            for r in rs:
                self.add(ch, r)

    def key(self, syllable: str) -> str:
        return nfc(syllable).lower() if self.tone_sensitive else syllable_key(syllable)

    def add(self, ch: str, syllable: str) -> None:
        ch = unicodedata.normalize("NFC", ch.strip())
        if len(ch) == 1 and syllable.strip():
            self._map.setdefault(ch, set()).add(self.key(syllable.strip()))

    def readings(self, ch: str) -> frozenset[str]:
        return frozenset(self._map.get(ch, ()))

    def known(self, ch: str) -> bool:
        return ch in self._map

    def __len__(self) -> int:
        return len(self._map)

    # ------------------------------------------------------------------ loading
    def load(self, path: str | Path) -> ReadingTable:
        """Load one source; the kind is read from the name (folder, `.jsonl`, `.sqlite`, `.json`, else a CSV / TSV)."""
        p = Path(path)
        if p.is_dir():
            files = entry_files(p)
            if files:
                for f in files:
                    self.load_jsonl(f)
                    self.sources.append(str(f))
                return self
            for name in ("lab_dict.csv", "lexicon.sqlite"):
                if (p / name).is_file():
                    p = p / name
                    break
            else:
                raise TableError(f"no entries/*.jsonl, lab_dict.csv or lexicon.sqlite in {p}")
        if not p.is_file():
            raise TableError(f"reading table not found: {p}")
        if is_jsonl(p):
            self.load_jsonl(p)
        elif p.suffix.lower() == ".sqlite":
            self.load_sqlite(p)
        elif p.suffix.lower() == ".json":
            self.load_json(p)
        else:
            self.load_csv(p)
        self.sources.append(str(p))
        return self

    def load_jsonl(self, path: str | Path) -> ReadingTable:
        """Dictionary entries (one JSON object per line); the evidence kept is:

        - a Han or Nom entry with one codepoint: its readings of system `qn`, `hv`, `nom`. A `word` entry counts only when
          its source also has a `char` entry for that character (a lone word entry is weaker evidence);
        - a Vietnamese entry (`script` `qn`): each one-character Nom form in `forms` reads as the entry's head.

        Longer words, other scripts, unencoded characters (`unencoded`) and other reading systems are skipped. A line
        that is not an entry (no `head`) stops the load with its line number: a crawl log or another file by mistake.
        """
        p = Path(path)
        if not p.is_file():
            raise TableError(f"entries file not found: {p}")
        opener = gzip.open if p.name.lower().endswith(".gz") else open
        chars: set[tuple[str, str]] = set()  # (source, head) of the `char` entries
        words: dict[
            tuple[str, str], list[str]
        ] = {}  # single-character `word` entries, kept until the file is read
        with opener(p, "rt", encoding="utf-8-sig") as fh:
            for no, line in enumerate(fh, 1):
                line = line.strip()
                if not line:
                    continue
                try:
                    entry = json.loads(line)
                except json.JSONDecodeError as exc:
                    raise TableError(f"{p}:{no}: bad JSON ({exc.msg})") from None
                if not isinstance(entry, dict) or not isinstance(entry.get("head"), str):
                    raise TableError(
                        f"{p}:{no}: not a dictionary entry (no `head`); is this a manifest or pairs file?"
                    )
                self._read_entry(entry, chars, words)
        for key, syllables in words.items():
            if key in chars:
                for syl in syllables:
                    self.add(key[1], syl)
        return self

    def _read_entry(
        self, entry: dict, chars: set[tuple[str, str]], words: dict[tuple[str, str], list[str]]
    ) -> None:
        script = entry.get("script")
        if script in ("han", "nom"):
            head = _one_char(entry["head"])
            if entry.get("unencoded") or len(head) != 1:
                return
            key = (str(entry.get("source", "")), head)
            vi = [
                r["value"]
                for r in entry.get("readings") or ()
                if isinstance(r, dict) and r.get("system") in VIETNAMESE_SYSTEMS and r.get("value")
            ]
            if entry.get("kind") == "char":
                chars.add(key)
                for syl in vi:
                    self.add(head, syl)
            elif entry.get("kind") == "word":
                words.setdefault(key, []).extend(vi)
        elif script == "qn":
            for f in entry.get("forms") or ():
                if not (isinstance(f, dict) and f.get("script") == "nom"):
                    continue
                text = f.get("text")
                if (
                    isinstance(text, str)
                    and not text.startswith("@img:")
                    and len(_one_char(text)) == 1
                ):
                    self.add(_one_char(text), entry["head"])

    def load_csv(self, path: str | Path) -> ReadingTable:
        p = Path(path)
        if not p.is_file():
            raise TableError(f"lexicon CSV not found: {p}")
        text = p.read_text(encoding="utf-8-sig")
        first = text.splitlines()[0] if text else ""
        names = [h.strip() for h in next(csv.reader([first]))] if first else []
        if (
            "QuocNgu" in names and "SinoNom" in names
        ):  # QuocNgu_SinoNom dictionary: syllable first, character second
            qn, sn = names.index("QuocNgu"), names.index("SinoNom")
            for row in list(csv.reader(text.splitlines()))[1:]:
                if len(row) > max(qn, sn):
                    self.add(row[sn], row[qn])
            return self
        tsv = "\t" in first
        for row in csv.reader(text.splitlines(), delimiter="\t" if tsv else ","):
            if len(row) < 2 or row[0].startswith("#"):
                continue  # a header or a word head is skipped by `add` (not one character)
            for syl in _SPLIT.split(row[1]) if tsv else [row[1]]:
                self.add(row[0], syl)
        return self

    def load_json(self, path: str | Path) -> ReadingTable:
        try:
            data = json.loads(Path(path).read_text(encoding="utf-8-sig"))
        except json.JSONDecodeError as exc:
            raise TableError(f"{path}: bad JSON ({exc.msg})") from None
        if not isinstance(data, dict):
            raise TableError(f'{path}: expected {{"char": ["syllable", ...]}}')
        for ch, rs in data.items():
            for r in [rs] if isinstance(rs, str) else rs:
                self.add(ch, r)
        return self

    def load_sqlite(self, path: str | Path) -> ReadingTable:
        """A `lexicon.sqlite`: `reading_table(head, syllable)`, characters only."""
        p = Path(path)
        try:
            con = sqlite3.connect(f"file:{p}?mode=ro", uri=True)
        except sqlite3.Error as exc:
            raise TableError(f"{p}: cannot open ({exc})") from None
        try:
            for head, syl in con.execute(
                "SELECT head, syllable FROM reading_table WHERE length(head) = 1"
            ):
                self.add(head, syl)
        except sqlite3.Error as exc:
            raise TableError(f"{p}: not a lexicon.sqlite with a reading_table ({exc})") from None
        finally:
            con.close()
        return self

    @classmethod
    def from_paths(
        cls, paths: Iterable[str | Path], *, tone_sensitive: bool = False
    ) -> ReadingTable:
        t = cls(tone_sensitive=tone_sensitive)
        for p in paths:
            t.load(p)
        if not len(t):
            raise TableError(
                "empty reading table: pass --table (entries/*.jsonl, lab_dict.csv, lexicon.sqlite, ...) "
                "or set NOM_ALIGN_TABLE"
            )
        return t


__all__ = ["ReadingTable", "TableError", "entry_files", "is_jsonl"]
