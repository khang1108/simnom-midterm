"""Config of a run. `NomAlignConfig` holds the alignment settings (every number marked [tune] is a guess to set after
looking at real pages); `RunConfig` holds where files live (env or flags); `load_env` reads a `.env` file."""

from __future__ import annotations

import os
from dataclasses import asdict, dataclass
from pathlib import Path

from . import __version__

ERROR_COLORS = frozenset(
    {"FF0000", "D32F2F"}
)  # colours the spec accepts, compared on the last six hex digits
WARN_COLORS = frozenset({"FFFF00", "D99A00"})
BLACK_COLORS = frozenset({"000000"})


@dataclass(frozen=True)
class NomAlignConfig:
    # --- row kind
    mode: str = "phonetic"  # the book type, declared by the author: "phonetic" (diff every 1-1 row) | "meaning" (never)
    phonetic_min_match: float = (
        0.6  # [tune] rows below this share are only listed (`low_match_rows`), never nulled
    )
    merged_diff: str = "null"  # rows of kind 1--n, n--1, n--m: "null" (default: a merged row is a translation) | "phonetic" (diff anyway)
    # --- token costs of the Levenshtein
    gap_cost: float = 1.0
    mismatch_cost: float = 1.0  # character known, syllable is not one of its readings
    unknown_cost: float = 0.5  # [tune] character in no dictionary: neutral, so length decides
    unknown_policy: str = "error"  # a Nom character found in no dictionary is red, so gaps in the table show | "match": black
    tone_sensitive: bool = False  # False: `mẫu` matches a reading `mau`
    warn_numbers: bool = True  # a number token against a run of Nom characters is yellow
    warn_names: bool = False  # capitalised syllables against a Nom run of another length are yellow
    names: tuple[
        str, ...
    ] = ()  # proper names (one per entry, e.g. `Phi-lip-phê`): a run that reads as one is yellow
    # --- sentences
    short_warn: int = (
        5  # sentences below this many tokens are listed for review (0: off); they are kept
    )
    merge_short: int = 0  # merge sentences below this many tokens into a neighbour (0: never)
    hyphen: str = (
        "word"  # line-end `-`: "word" (join; keep when both parts are capitalised or the word is listed, else drop)
        # | "space" (`tin-` + `tưởng` gives `tin tưởng`) | "keep" (`tin-tưởng`)
    )
    strip_notes: bool = False  # remove [1] and (1) note marks from Vietnamese text (off: the text must match Label.txt)
    # --- sentence DP
    cost_mode: str = (
        "lev"  # "lev": Levenshtein on readings | "length": length ratio only (translations)
    )
    max_group: int = 3  # sentences merged in one row on either side
    merge_penalty: float = 1.0  # [tune] per extra sentence in a group
    nm_penalty: float = 4.0  # [tune] extra for n--m (both sides more than one)
    skip_base: float = 0.5  # [tune] a sentence left without partner; must stay below merge_penalty
    skip_per_token: float = 1.0
    min_len_ratio: float = 0.5  # groups whose lengths differ more are not scored by Levenshtein
    beam: float = 40.0  # [tune] states costing more than best + beam are dropped (speed)
    band: int = 0  # half-width in sentences around the page-pair diagonal; 0: pick from the book
    nom_order: str = (
        "asc"  # page order without an image_map: "asc" | "desc" (T1 Nom read from the end)
    )
    # --- output
    allow_skip: bool = (
        False  # diagnostics: the DP may leave sentences unpaired; they never enter the CSV
    )
    fallback_max_dist: float = 0.5  # second OCR: edit distance / length above this skips the image
    error_color: str = (
        "FF0000"  # the Excel standard colours; D32F2F / D99A00 are accepted when reading
    )
    warn_color: str = "FFFF00"
    black_color: str = "000000"

    def __post_init__(self) -> None:
        for name, ok in (
            ("mode", ("phonetic", "meaning")),
            ("merged_diff", ("null", "phonetic")),
            ("unknown_policy", ("error", "match")),
            ("hyphen", ("word", "space", "keep")),
            ("cost_mode", ("lev", "length")),
            ("nom_order", ("asc", "desc")),
        ):
            if getattr(self, name) not in ok:
                raise ValueError(f"{name} must be one of {ok}, got {getattr(self, name)!r}")
        if not 1 <= self.max_group <= 4:
            raise ValueError("max_group must be between 1 and 4")
        if self.short_warn < 0 or self.merge_short < 0 or self.band < 0:
            raise ValueError("short_warn, merge_short and band must be >= 0")
        if not 0 < self.fallback_max_dist <= 1:
            raise ValueError("fallback_max_dist must be in (0, 1]")
        for name, ok in (
            ("error_color", ERROR_COLORS),
            ("warn_color", WARN_COLORS),
            ("black_color", BLACK_COLORS),
        ):
            val = getattr(self, name).upper()
            if val not in ok:
                raise ValueError(f"{name} must be one of {sorted(ok)}, got {val!r}")
            object.__setattr__(self, name, val)
        if not 0 < self.phonetic_min_match <= 1:
            raise ValueError("phonetic_min_match must be in (0, 1]")

    def to_dict(self) -> dict:
        return asdict(self)


def read_names(path: str | Path) -> tuple[str, ...]:
    """One proper name per line (`#` comments and blank lines ignored)."""
    p = Path(path)
    if not p.is_file():
        raise ValueError(f"names file not found: {p}")
    lines = (ln.strip() for ln in p.read_text(encoding="utf-8-sig").splitlines())
    return tuple(ln for ln in lines if ln and not ln.startswith("#"))


def load_env(path: str | Path | None = None) -> list[str]:
    """Read KEY=VALUE lines of an env file into os.environ. A variable already set in the real environment wins.
    Default file: `$NOM_ALIGN_ENV_FILE`, else `./.env` (missing = nothing happens). Returns the names that were set.
    Accepted: `export KEY=value`, single or double quotes, `# comment` lines, blank lines. No expansion."""
    f = Path(path or os.environ.get("NOM_ALIGN_ENV_FILE") or ".env")
    if not f.is_file():
        return []
    done: list[str] = []
    for raw in f.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        if line.startswith("export "):
            line = line[7:].lstrip()
        key, _, val = line.partition("=")
        key, val = key.strip(), val.strip()
        if val[:1] in "\"'" and val.find(val[0], 1) > 0:
            val = val[
                1 : val.find(val[0], 1)
            ]  # quoted: whatever follows the closing quote is a comment
        elif " #" in val:
            val = val.split(" #", 1)[0].rstrip()
        if key and key not in os.environ:
            os.environ[key] = val
            done.append(key)
    return done


@dataclass(frozen=True)
class RunConfig:
    """Where a run reads and writes. Flags win over the environment, the environment over these defaults."""

    out_dir: Path = Path("out")
    tables: tuple[
        str, ...
    ] = ()  # reading-table sources: entries .jsonl (or their folder), lab_dict.csv, lexicon.sqlite
    contact: str = ""
    similar: str = ""  # SinoNom_Similar_Dic CSV (NOM_ALIGN_SIMILAR)
    cache: Path = (
        Path.home() / ".cache" / "ocr-nom-align" / "online_readings.json"
    )  # answers of the online lookup

    @property
    def tool(self) -> str:
        return f"ocr-nom-align/{__version__}"

    def paths(self, book: str) -> dict[str, Path]:
        """The files of one book. `book` is the book name used in `<book>.csv`."""
        d = self.out_dir
        return {
            "csv": d / f"{book}.csv",
            "xlsx": d / f"{book}.xlsx",
            "report": d / f"{book}_align_report.json",
            "detail": d / f"{book}_align_detail.jsonl",
            "short": d / f"{book}_short_sentences.jsonl",
            "orphans": d / f"{book}_align_orphans.jsonl",
            "hyphens": d / f"{book}_hyphens.jsonl",
        }

    @classmethod
    def from_env(cls, **override) -> RunConfig:
        e = os.environ
        tables = [p for p in (e.get("NOM_ALIGN_TABLE") or "").split(os.pathsep) if p]
        base = {
            "out_dir": Path(e.get("NOM_ALIGN_OUT_DIR") or "out"),
            "tables": tuple(dict.fromkeys(tables)),
            "contact": e.get("NOM_ALIGN_CONTACT", ""),
            "similar": e.get("NOM_ALIGN_SIMILAR", ""),
            "cache": Path(e.get("NOM_ALIGN_CACHE") or cls.cache),
        }
        base.update({k: v for k, v in override.items() if v not in (None, ())})
        base["out_dir"] = Path(base["out_dir"])
        base["tables"] = tuple(base["tables"])
        base["cache"] = Path(base["cache"])
        return cls(**base)
