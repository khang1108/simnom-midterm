<div align="center">

# 🧩 ocr-nom-align

Align the Sino-Nom sentences of a book with its Vietnamese sentences by Levenshtein distance over character-to-syllable
readings, and write the submission files `<book>.csv` and `<book>.xlsx` with `text_diff` — as a CLI and a small Python
library, with no sibling module. The only network use is the optional online lookup of characters the dictionary lacks.

</div>

# :notebook_with_decorative_cover: Table of Contents

- [About the Project](#star2-about-the-project)
  - [Features](#dart-features)
  - [Design Notes](#books-design-notes)
- [Getting Started](#toolbox-getting-started)
  - [Prerequisites](#bangbang-prerequisites)
  - [Run Locally](#running-run-locally)
  - [Configuration](#key-configuration)
- [Usage](#eyes-usage)
  - [As a CLI](#as-a-cli)
  - [Reading Table](#reading-table)
  - [Align a Book](#align-a-book)
  - [Rows Already Paired](#rows-already-paired)
  - [Check and Score](#check-and-score)
  - [As a Library](#as-a-library)
  - [Output Files](#output-files)
  - [Failure Rules](#failure-rules)
  - [Colab Notebook](#notebook-colab-notebook)
  - [Reading the Result in Other Modules](#reading-the-result-in-other-modules)
  - [Troubleshooting](#rotating_light-troubleshooting)
  - [Example Workflow](#example-workflow)
  - [End-to-End Guide](#end-to-end-guide)
- [Project Structure](#file_folder-project-structure)
- [Running Tests](#test_tube-running-tests)
- [Contributing](#wave-contributing)
- [License](#warning-license)
- [Contact](#handshake-contact)
- [Acknowledgements](#gem-acknowledgements)

> Full walkthrough: [docs/USER_GUIDE.md](docs/USER_GUIDE.md). Hand-over notes: [docs/HANDOFF.md](docs/HANDOFF.md).

## :star2: About the Project

A book is delivered as one file: one row per aligned Nom/Vietnamese pair, and for phiên âm rows a `text_diff` that
says where the Nom text and its reading differ. `ocr-nom-align` produces that file:

```
ch/Label.txt   vi/Label.txt   [Book_image_map.json]      PPOCRLabel files, boxes in reading order
lexicon/entries/*.jsonl                                   reading table (any number of files, merged;
                                                          lab_dict.csv and lexicon.sqlite work as well)
        │
        ▼  ocr-nom-align run
out/Book.csv   out/Book.xlsx   out/Book_align_report.json
```

The package is the sentence-level step. `ocr-align` aligns one character to one syllable inside a stream and ranks OCR
candidates; the two are independent and do not import each other. The package never touches a bucket, a journal or
Colab: the files are the contract.

### :dart: Features

- Joins page text in reading order, so a sentence cut by a page break is whole again; `img_id` and `sentence_id` come from
  the image where the sentence starts. A dash at a line end is joined (`tin-` `tưởng` gives `tin tưởng`).
- Splits both sides at punctuation (a hint, not a certainty). Sentences below `--short-warn` tokens (5) are listed in
  `<book>_short_sentences.jsonl` and kept; they are merged only by `--merges` or `--merge-short`.
- Aligns sentences with a banded DP: moves 1-1, 1-n, n-1 and 2-2 (skips only with `--allow-skip`, for diagnosis); the cost of a move is the Levenshtein distance
  between the Nom characters and the Vietnamese syllables (a syllable that is a reading of the character costs 0).
- Decides per row *phonetic* (`text_diff` is a JSON array, `[]` when equal) or *meaning* (`null`) from the book type the author
  declares with `--mode`; a mixed book gets `--ranges`. Merged rows are `null`. No row has an empty side.
- Writes `text_diff` elements (`nom_pos`, `nom_sub_text`, `vi_pos`, `vi_sub_text`, `type`) with NFC code-point positions;
  `[MASK]` is never in a `pos`; a number against Nom characters and a listed proper name of unequal length are `warn` (yellow),
  the rest `error` (red). A `warn` carries `reviewed` (0 or 1).
- **Suggestions**: a character that the dictionary rejects can get a suggested replacement from a second Nom OCR
  (`--ch-fallback`) or a similar-character table (`--similar`). It is a yellow `warn` with `suggest`; the text does not change.
  `apply` writes the accepted ones into `Label.txt`, the CSV, `Label_char.txt` and the XLSX together; `check-diff --final` is the
  submission gate (no pending suggestion).
- **The dictionary as it is handed out**: the `entries/*.jsonl` files are the first-class reading table; point at one file or
  at the folder. Nothing else is needed (no `lexicon.sqlite`, no `lab_dict.csv`, no build step).
- **Three levels of table support**: first class `entries/*.jsonl`; second class the other files of the same dictionary
  (`lab_dict.csv`, `lexicon.sqlite`); third class any other `.csv` / `.tsv` / `.json` of `character -> syllables`. Several
  sources at once, merged.
- **Unknown characters are looked up online**: a Nom character that no table source lists is searched on the web once
  (Hán Việt and Nôm readings), added to the table and kept in a local cache, so the book is aligned with it instead of
  being red. `--offline` turns this off; a failed request leaves the character unknown and never stops the run.
- **Rows already paired?** `diff` recomputes `text_diff` for a `pairs.csv` / `pairs.jsonl` with the same settings.
- Writes the `.xlsx` with coloured runs that match `text_diff`, checks both files before submission, computes the
  similarity `(1 - red / scored Nom characters) * 100`. `render` rebuilds the `.xlsx` from a hand-fixed CSV without
  recomputing; `check-diff` checks the CSV and XLSX against `ch/Label.txt`, `vi/Label.txt` and `Label_char.txt`.
- `.env` file and environment variables for paths; flags win over both.

### :books: Design Notes

- **The CSV is official.** The `.xlsx` is derived from it and checked against it; when they disagree the CSV wins.
- **Nothing is guessed silently.** A Nom character found in no table and not found online is red by default (`--unknown match`
  turns that off while the table is thin); every such character is listed in the report.
- **Every number marked [tune] is a guess** until a gold sample says otherwise; the config used is written into the report.
- **A failed check is a stop.** `check` exits `1` with the list of rows; nothing is repaired on its own.
- Full design: [`docs/SPECIFICATION.md`](docs/SPECIFICATION.md) and [`docs/SCHEMA.md`](docs/SCHEMA.md).

## :toolbox: Getting Started

### :bangbang: Prerequisites

- Python 3.10 or newer and [uv](https://docs.astral.sh/uv/).
- A reading table: the dictionary entry files (`entries/*.jsonl`) . `lab_dict.csv` and `lexicon.sqlite` work too. Tables are never committed.
- No network is needed to run or to test.

### :running: Run Locally

```bash
git clone https://github.com/obj-see/ocr-nom-align.git
cd ocr-nom-align
uv sync
uv run ocr-nom-align demo 経告命命命。 "Kinh Cáo Mệnh." --table examples/entries
```

`demo` prints the `text_diff` of one cell pair; if it prints one `error` element over `命命`, the install is good.

Plain `pip` works too: `pip install -e ".[test,lint]"`.

### :key: Configuration

Copy `.env.example` to `.env` (never commit it). Real environment variables win over `.env`.

| Variable | Flag | Default | Meaning |
|---|---|---|---|
| `NOM_ALIGN_TABLE` | `--table` (repeatable) | empty | reading-table sources, `:`-separated: entry `.jsonl` files or their folder, `lab_dict.csv`, `lexicon.sqlite` |
| `NOM_ALIGN_SIMILAR` | `--similar` | empty | `SinoNom_Similar_Dic` CSV for suggestions (`"Input Character","Top 20 Similar Characters"`) |
| `NOM_ALIGN_OFFLINE` | `--offline` | off | `1`: do not look unknown characters up online |
| `NOM_ALIGN_CACHE` | | `~/.cache/ocr-nom-align/online_readings.json` | the answers of the online lookup, one JSON file |
| `NOM_ALIGN_CONTACT` | | empty | email or URL put in the `User-Agent` of the online lookup |
| `NOM_ALIGN_OUT_DIR` | `--out-dir` | `./out` | where `<book>.csv`, `.xlsx` and the report are written |
| `NOM_ALIGN_ENV_FILE` | `--env-file` | `./.env` | the env file to read |

Alignment settings (`--mode` (required), `--unknown`, `--tone-sensitive`, `--hyphen`, `--cost-mode`, `--band`, `--names`, ...) are options
of the commands; every field of `NomAlignConfig` is written into the report.

## :eyes: Usage

### As a CLI

```text
ocr-nom-align run --ch CH --vi VI --book NAME --mode phonetic|meaning [--out-dir D] [--image-map F] [--table T ...] [--ranges F] [--ch-fallback F] [--similar F] [--detail] ...
ocr-nom-align diff PAIRS --out CSV --mode phonetic|meaning [--xlsx F] [--report F] [--table T ...] [--ranges F] [--keep-reviewed OLD.csv]
ocr-nom-align render CSV --xlsx F
ocr-nom-align check-diff CSV [--xlsx F] [--ch F] [--vi F] [--ch-char F] [--image-map F] [--nom-order asc|desc] [--missing-ch DIR] [--missing-vi DIR] [--strict] [--final]
ocr-nom-align apply CSV --ch F --vi F [--ch-char F] [--xlsx F] [--accept reviewed|all] [--reject-rest] [--out-dir D | --in-place]
ocr-nom-align check CSV [--xlsx F]
ocr-nom-align score CSV [--min PERCENT]
ocr-nom-align demo CH_TEXT VI_TEXT [--table T ...]
ocr-nom-align readings CHARS... [--table T ...]
```

Exit codes: `0` ok, `1` an error or a failed check. `python -m ocr_nom_align` works as well.

### Reading Table

```bash
uv run ocr-nom-align readings 天 主 --table ~/lexicon/entries
```

prints how many characters were loaded, from which files, and the readings of each character; a character that the table
lacks is looked up online (`--offline` to skip). Keys drop the five tone marks and keep breve, circumflex, horn and `đ`
(`--tone-sensitive` keeps the tone). Only single characters are used.

| Level | Files | What you get |
|---|---|---|
| 1, first class | `entries/<source>.jsonl`, `.jsonl.gz`, or the folder | found from the folder by itself, read as described below, a bad line is reported with its number, tested |
| 2, second class | `lab_dict.csv`, `lexicon.sqlite` of the same dictionary | read with their own loaders; a folder that holds one of them works |
| 3, third class | any other `.csv` / `.tsv` (`char,syllable` or `char<TAB>syl1,syl2`), `.json` (`{"天": ["thiên"]}`) | best effort: the file kind comes from the suffix, nothing is checked beyond the shape |

**The dictionary `.jsonl` files** (`entries/<source>.jsonl`, one JSON entry per line) are read directly:

```bash
uv run ocr-nom-align readings 天 --table ~/lexicon/entries            # the folder: every *.jsonl in it (or in its entries/)
uv run ocr-nom-align readings 天 --table ~/lexicon/entries/hvdic.jsonl  # one file; .jsonl.gz works as well
```

- A Han or Nom entry with one codepoint (`kind` `char`) gives its readings of system `qn`, `hv` and `nom` (pinyin, on,
  hangul and the others are not Vietnamese). A single-character `word` entry counts only when its source also has a `char`
  entry for that character, the same condition a `lexicon.sqlite` reading table applies.
- A Vietnamese entry (`script` `qn`, Đại Nam style) that lists a one-character Nom form in `forms` gives that character the
  entry head as reading.
- Words, unencoded characters (`unencoded`), `@img:` forms and other scripts are skipped. A variation selector after a
  character is dropped, so the variant glyph reads like its base character.
- In a folder, `manifest*.jsonl` crawl logs and the `rejected/` folder are not entries. A line that is not an entry stops
  the load and names the file and line (`x.jsonl:2: not a dictionary entry`).
- The result equals the reading table of a `lexicon.sqlite` built from the same entries (same characters, same readings);
  the entry files carry no source weights, which a set of readings does not need.

**Characters the table lacks** are searched online, once, while the run starts: each Nom character of the book that no
source lists is asked for on the `/whv/<character>` page of [hvdic.thivien.net](https://hvdic.thivien.net) (then
`/wnom/` for a Nom character), its Hán Việt and Nôm readings are added to the table, and the answer, empty ones too, is
kept in the cache file (`NOM_ALIGN_CACHE`). The second run, and every later book, asks nothing for it.

- Requests are one second apart, at most 300 per run; the site's block page or three failed requests in a row end the
  lookups of that run (the rest stay unknown and red, a note goes to stderr).
- Whatever was added is in the report: `online` (`asked`, `cached`, `found`, `not_found`, `failed`, `skipped`) and a
  `reading_sources` entry `online:...`. Put your email in `NOM_ALIGN_CONTACT` so the site can reach you.
- `--offline` (or `NOM_ALIGN_OFFLINE=1`) asks nothing: use it for a reproducible run, or on a machine without network.

### Align a Book

```bash
uv run ocr-nom-align run --ch ch/Label.txt --vi vi/Label.txt --image-map Book_image_map.json \
    --book Book --mode phonetic --out-dir out --names names.txt --detail
```

Without an image map pages are paired by page number when at least half the numbers agree (same-image or T2 books),
otherwise by position (`--nom-order desc` reverses the Nom order, for T1).

| Option | Meaning |
|---|---|
| `--mode` | required, the book type the author declares: `phonetic`: diff every 1-1 row; `meaning`: never (all `null`). There is no `auto` |
| `--ranges FILE` | mixed book: JSON list of `meaning` ranges (image ranges or sentence-id ranges); see the User Guide |
| `--cost-mode length` | length ratio instead of Levenshtein, for translations |
| `--unknown match` | characters in no table count as equal (table still thin) |
| `--names FILE` / `--warn-names` | proper names (file) or capitalised syllables (heuristic) are yellow; a name from the file is `reviewed` 1 and yellow only when the Nom and Vietnamese character counts differ |
| `--ch-fallback FILE` | `Label.txt` of a second Nom OCR; substituted characters become suggestions |
| `--fallback-max-dist F` | skip an image whose two Nom texts differ by more than this share (0.5); listed in `fallback_skipped_images` |
| `--similar FILE` | similar-character CSV (or `NOM_ALIGN_SIMILAR`): second source of suggestions |
| `--hyphen word\|space\|keep` | line-end dash: `word` (default) joins and keeps the dash when both parts are capitalised or the word is a name or in the `--hyphen-keep` list; `space` drops it; `keep` always keeps it |
| `--hyphen-keep FILE` | words (one per line, hyphens included) that keep their dash; their records are `reviewed` 1 |
| `--strip-notes` / `--no-strip-notes` | remove `[1]` / `(1)` note marks from the Vietnamese text (default off: the text must match `Label.txt`) |
| `--short-warn N` | list sentences below N tokens in `<book>_short_sentences.jsonl` (5; 0 turns the list off) |
| `--merges FILE` | the short-sentences file with `merge` set to `prev` or `next` on the lines to join |
| `--merge-short N` | merge sentences below N tokens automatically (0: never) |
| `--allow-skip` | diagnosis: the DP may leave sentences unpaired; they go to `<book>_align_orphans.jsonl`, never into the CSV |
| `--band N` | DP half-width in sentences (0: picked from the book) |
| `--error-color`, `--warn-color`, `--black-color` | XLSX colours, accepted set only (see SCHEMA); also on `render`, `check-diff`, `apply` |
| `--detail` | also write `<book>_align_detail.jsonl` |

### Rows Already Paired

```bash
uv run ocr-nom-align diff pairs.csv --out out/Book.csv --xlsx out/Book.xlsx --report out/Book_align_report.json
```

`pairs.csv` / `pairs.jsonl` holds `img_id, sentence_id, ch_txt, vi_txt` and optionally `kind` (`1-1` default; `1-n`, `n-1`,
`n-m` rows stay `null`). Any `text_diff` already in the file is recomputed, so `diff` erases a hand fix of `text_diff`;
`--mode` is required here too, and `--keep-reviewed OLD.csv` copies `reviewed` from an earlier CSV to equal `warn` elements.

### Check and Score

```bash
uv run ocr-nom-align check out/Book.csv --xlsx out/Book.xlsx   # ok, or the problems and exit 1
uv run ocr-nom-align score out/Book.csv --min 95                # similarity, null_rate, yellow_rate; exit 1 under 95
```

`check-diff` is the deeper check (`row N: CODE: message`, exit `1` on any error; `--strict`: warnings fail too):

```bash
uv run ocr-nom-align check-diff out/Book.csv --xlsx out/Book.xlsx --ch ch/Label.txt --vi vi/Label.txt \
    [--ch-char ch/Label_char.txt] [--missing-ch missing/ch] [--missing-vi missing/vi] [--final]
```

| Code | Meaning |
|---|---|
| `KEYS`, `OOB`, `SUB`, `OVERLAP`, `EDGE`, `MASK` | element key set, range, sub text, overlap, edge or `[MASK]` rule broken |
| `SELECTOR`, `EMPTY`, `FORM` | variation selector in `ch_txt`; empty `ch_txt` / `vi_txt`; not NFC or a line break in a cell |
| `REVIEWED` | `reviewed` is not 0 or 1 (error); count of unreviewed `warn` (warning) |
| `SUGGEST`, `SUGGEST_PENDING` | malformed suggestion; a `warn` with `suggest` still pending (warning, an error with `--final`) |
| `XLSX` | colour outside the accepted set, colours differ from `text_diff`, or the text differs |
| `SYNC` | CSV text differs from `Label.txt` (only a side that has a file; rows of a lost page in `--missing-ch` / `--missing-vi` need one whole `warn` instead) |
| `SYNC_CHAR`, `LABELCHAR` | `Label_char.txt` differs from the CSV Nom text; a box holds more than one character, or the boxes are missing, extra or unsorted |

A CSV without `img_id` / `text_diff` (plain-text types) gets only `EMPTY`, `SELECTOR` and `FORM`.

**Suggestions and manual fixes**

```bash
uv run ocr-nom-align apply out/Book.csv --ch ch/Label.txt --vi vi/Label.txt --ch-char ch/Label_char.txt \
    --xlsx out/Book.xlsx --accept reviewed --reject-rest --out-dir fixed
uv run ocr-nom-align render out/Book.csv --xlsx out/Book.xlsx   # XLSX of a hand-fixed CSV; never recomputes text_diff
```

`apply` first checks SYNC and refuses (nothing written) on a difference. It writes the accepted suggestions (`--accept reviewed`:
only `reviewed` 1; `all`) into `Label.txt`, the CSV, `Label_char.txt` and the XLSX, turns the rest into red `error` elements with
`--reject-rest`, runs `check-diff --final` on the result and prints `applied`, `rejected`, `skipped`. If `Label_char.txt` exists
beside `--ch`, `--ch-char` is required. Give exactly one of `--out-dir` or `--in-place` (which keeps a `.bak` of each file).

### As a Library

```python
from ocr_nom_align import (
    NomAlignConfig,
    ReadingTable,
    align_book,
    check_csv,
    fill_text_diff,
    read_label,
    read_pairs,
    similarity,
    write_csv,
    write_xlsx,
)
from ocr_nom_align.tableio import read_csv

table = ReadingTable.from_paths(["lexicon/entries"])
cfg = NomAlignConfig(mode="phonetic")  # declare the book type; there is no "auto"
res = align_book(read_label("ch/Label.txt"), read_label("vi/Label.txt"), table, cfg)
write_csv(res.rows, "Book.csv")
write_xlsx(res.rows, "Book.xlsx", cfg)
print(check_csv("Book.csv"), similarity(read_csv("Book.csv"))["similarity"])

rows, report = fill_text_diff(read_pairs("pairs.csv"), table, cfg)  # rows already paired
```

### Output Files

| Path | Written by | Holds |
|---|---|---|
| `<out-dir>/<book>.csv` | `run`, `diff` | `img_id, sentence_id, ch_txt, vi_txt, text_diff`; UTF-8 with BOM |
| `<out-dir>/<book>.xlsx` | `run`, `diff`, `render`, `apply` | sheet `align`, `ch_txt` and `vi_txt` in coloured runs (red `FF0000`, yellow `FFFF00`) |
| `<out-dir>/<book>_align_report.json` | `run`, `diff` | counts, kinds, similarity, null and yellow rates, orphans, `unknown_chars`, notes, reading sources, `online`, suggestion and review counters, config |
| `<out-dir>/<book>_align_detail.jsonl` | `run --detail` | per row: kind, Vietnamese image, phiên âm flag |
| `<out-dir>/<book>_short_sentences.jsonl` | `run` | sentences below `--short-warn` tokens, with `merge: keep` to edit |
| `<out-dir>/<book>_hyphens.jsonl` | `run` | every line-end hyphen that was joined, with `reviewed` 0 or 1 |
| `<out-dir>/<book>_align_orphans.jsonl` | `run --allow-skip` | unpaired sentences, for diagnosis |

Formats: [`docs/SCHEMA.md`](docs/SCHEMA.md).

### Failure Rules

- An empty or missing reading table stops the run with a clear message (exit `1`).
- A path with no alignment inside the band (two texts too different, wrong pairing) stops the run: `AlignFailed`, exit `1`. Without `--allow-skip` no sentence is left unpaired, so a path may need merges (up to 3 sentences per side) or fail with a hint.
- `run` and `diff` without `--mode`, or with `--mode auto`, stop with a message. An unknown id or a reversed range in `--ranges` stops the run and names the id.
- A stale line in the `--merges` file (the sentence is no longer there) stops the run; it is never skipped silently.
- A bad label line, a bad image map or a pairs file with missing columns names the file and the line.
- `check` lists every problem (first 200) and exits `1`.

### :notebook: Colab Notebook

`notebooks/align.ipynb` has the same shape as the `ocr-engines` notebooks: CONFIG (the only cell you edit) → BOOTSTRAP →
SETUP → RUN → REVIEW → ENV. BOOTSTRAP clones and installs this repo with `ocr_flow.bootstrap.setup` (Colab secret
`GITHUB_TOKEN`; the token travels only in a header). RUN calls `ocr-nom-align run`, REVIEW calls `check` and `score`, ENV
prints the environment fingerprint for the report. Input and output are plain files on `/content`; it pushes nothing, and the
package itself still never imports `ocr_flow`. It is unverified until someone has run it clean on Colab.
`tests/test_notebook.py` guards the shape.

### Reading the Result in Other Modules

- **Dictionary data:** the `entries/*.jsonl` files are read as they are
  (`export NOM_ALIGN_TABLE=/path/to/lexicon/entries`). A `lab_dict.csv` or a `lexicon.sqlite` built from the same entries
  gives the same table and works too.
- **Teachers / reviewers:** submit `<book>.csv` and `<book>.xlsx` with the numbers of the report.

### :rotating_light: Troubleshooting

| Symptom | Cause and fix |
|---|---|
| `empty reading table` | give `--table` (or set `NOM_ALIGN_TABLE`) |
| `online lookup: N characters could not be asked` | no network, or the site refused; they stay unknown. Rerun later (answers already found are cached) or use `--offline` |
| `not a lexicon.sqlite with a reading_table` | the file has no `reading_table`; use the `entries/*.jsonl` files instead |
| `x.jsonl:N: not a dictionary entry` | the file is a crawl log or another jsonl; pass the entries folder or an `entries/<source>.jsonl` |
| `x.jsonl:N: bad JSON` | a damaged line in an entry file; fetch the file again |
| `no entries/*.jsonl, lab_dict.csv or lexicon.sqlite in ...` | the folder has no entry files; point at the folder that holds `<source>.jsonl` |
| `no alignment path inside the band` | wrong page pairing: add an image map or `--nom-order desc`; or `--band` larger |
| many `n-1` / `1-n` rows | punctuation differs between the sides; fix it, or accept `null` rows |
| many red characters | thin table and no online answer: read `unknown_chars` and `online.not_found` in the report, add a table source, rerun |
| `row N: ... sentence_id` from `check` | `sentence_id` is `<img_id without .jpg>.<n>` |
| `.xlsx` differs from `.csv` | the CSV is official; rewrite the XLSX with `render` from the fixed CSV (`diff` would recompute `text_diff` and erase the fix) |
| `SYNC` from `check-diff` | the CSV text differs from `Label.txt`; fix both together (User Guide, manual fix) |
| `--mode is required` | declare the book type: `--mode phonetic` or `--mode meaning` |

### Example Workflow

```bash
export NOM_ALIGN_TABLE=$HOME/lexicon/entries
uv run ocr-nom-align readings 天
uv run ocr-nom-align run --ch ch/Label.txt --vi vi/Label.txt --book Book --mode phonetic --out-dir out --detail
uv run ocr-nom-align check out/Book.csv --xlsx out/Book.xlsx
uv run ocr-nom-align check-diff out/Book.csv --xlsx out/Book.xlsx --ch ch/Label.txt --vi vi/Label.txt --final
uv run ocr-nom-align score out/Book.csv --min 95
```

### End-to-End Guide

The full walkthrough (setup, recipes for a phiên âm book, a translation book, a thin table, rows already paired, review of
the report, the notebook) is in [`docs/USER_GUIDE.md`](docs/USER_GUIDE.md).

## :file_folder: Project Structure

```text
docs/
├── SPECIFICATION.md        # what the code does today, repo rules (§14)
├── SCHEMA.md               # CSV, XLSX, image map, pairs file, report, detail file
├── USER_GUIDE.md           # end-to-end walkthrough
└── HANDOFF.md              # the ONE handoff: rules, state, to-do list, where the code came from
src/ocr_nom_align/
├── __init__.py
├── cli.py                  # click CLI: run, diff, render, check, check-diff, apply, score, demo, readings
├── config.py               # NomAlignConfig (alignment settings), RunConfig (paths), load_env, read_names
├── readings.py             # ReadingTable: entries .jsonl (1st class), lab_dict.csv, lexicon.sqlite (2nd), csv / tsv / json (3rd)
├── online.py               # online lookup of characters the table lacks, with a cache
├── pages.py                # Label.txt, image map, page pairing, line joining
├── sentences.py            # sentence splitting, short-sentence list, manual merges
├── ranges.py               # --ranges file: image and sentence-id ranges of meaning rows
├── suggest.py              # similar-character table, second-OCR map, suggestions
├── sync.py                 # apply: accepted suggestions into Label.txt, CSV, Label_char.txt, XLSX
├── tokens.py               # Nom characters, syllables, code-point positions, [MASK]
├── lev.py                  # weighted Levenshtein with edit script
├── align.py                # sentence DP, rows, book result
├── diff.py                 # text_diff of one row
├── rows.py                 # pairs.csv / pairs.jsonl -> text_diff
├── tableio.py              # CSV and XLSX writers
├── validate.py             # check, check_xlsx, check_diff (SYNC, LABELCHAR, ...), similarity
├── report.py               # run report
└── py.typed
tools/                      # offline_pytest.py
notebooks/align.ipynb       # Colab: one book
examples/                   # entries/hv.jsonl, lab_dict.csv, pairs.csv, names.txt, similar.csv, hyphen_keep.txt, ranges.json
tests/                      # synthetic only
```

## :test_tube: Running Tests

```bash
uv sync
uv run pytest -v
uv run ruff check .
uv run ruff format --check .
```

The tests are synthetic (small label files and reading tables built in the test, a fake web for the online lookup): no network, no real book. Without `pytest`,
copy `tools/offline_pytest.py` to `pytest.py` and run `PYTHONPATH=<dir>:src:. python pytest.py [test_file_stem]`.

## :wave: Contributing

Contributions are always welcome!

Please read the [contribution guidelines](./CONTRIBUTING.md). The rules that are specific to this repo (no imports of other
module repos, only `cli.py` uses click, the CSV is official, a failed check is a stop) are in
[`docs/SPECIFICATION.md`](docs/SPECIFICATION.md) §14.

<!-- Code of Conduct -->

### :scroll: Code of Conduct

Please read the [Code of Conduct](./CODE_OF_CONDUCT.md).

## :warning: License

This project is licensed under the **Creative Commons
Attribution-NonCommercial-ShareAlike 4.0 International (CC BY-NC-SA 4.0)**
License.

[![License: CC BY-NC-SA 4.0](https://licensebuttons.net/l/by-nc-sa/4.0/88x31.png)](https://creativecommons.org/licenses/by-nc-sa/4.0/).

See the **[LICENSE.md](./LICENSE.md)** file for full details. Reading tables keep their own licences.

<!-- Contact -->

## :handshake: Contact

[obj-see](https://github.com/obj-see) —
[github.com/obj-see/ocr-nom-align](https://github.com/obj-see/ocr-nom-align)

## :gem: Acknowledgements

- [click](https://click.palletsprojects.com/) — the CLI framework.
- [openpyxl](https://openpyxl.readthedocs.io/) — the coloured `.xlsx`.
- [uv](https://docs.astral.sh/uv/) — Python packaging and tool management.
