# ocr-nom-align: User Guide

One guide, start to finish: two `Label.txt` files and a reading table to a coloured `<book>.csv` / `<book>.xlsx` that passes `check`, `check-diff --final` and `score`.
The README lists every option. Hand-over notes and open work: [HANDOFF.md](HANDOFF.md). Field formats: [SCHEMA.md](SCHEMA.md).

## Contents
1. The picture
2. Prerequisites and setup
3. Prepare the inputs
4. Recipes
5. Review
6. Check and score
7. Colab
8. Environment note for the report
9. File formats
10. Troubleshooting and cheat sheet

## 1. The picture

```
ch/Label.txt + vi/Label.txt + reading table      ocr-nom-align run      out/<book>.csv, .xlsx, _align_report.json
        pairs.csv (rows already paired)          ocr-nom-align diff     the same files
        out/<book>.csv                           ocr-nom-align check / check-diff / score    "ok" or the problems; the score
        hand-fixed out/<book>.csv                ocr-nom-align render   the XLSX again, text_diff untouched
        suggestions in out/<book>.csv            ocr-nom-align apply    Label.txt, CSV, Label_char.txt, XLSX in sync
```

The sentences are paired by Levenshtein distance on readings; the CSV is official, the XLSX is derived from it. The package reads and writes files only. Python 3.10+, `uv`. Dependencies: `click`, `openpyxl`. Only the online lookup of unknown characters uses the network, and `--offline` turns it off.

## 2. Prerequisites and setup

```bash
git clone https://github.com/obj-see/ocr-nom-align.git && cd ocr-nom-align
uv sync
cp .env.example .env        # set NOM_ALIGN_TABLE once (the dictionary entries folder); a variable set in the shell wins over .env
uv run ocr-nom-align readings 天 主   # shows which table files were read and the readings of two characters
```

## 3. Prepare the inputs

1. `ch/Label.txt` and `vi/Label.txt` from the OCR stages, boxes in reading order, text cleaned (no page numbers, no note marks, no stray characters).
2. A reading table: the dictionary entry files, `entries/*.jsonl` (the folder you were given): `--table lexicon/entries`, or
   `NOM_ALIGN_TABLE=lexicon/entries`. `lab_dict.csv` and `lexicon.sqlite` of the same dictionary work too, and so does any other `.csv` / `.tsv` / `.json` of
   `character -> syllables` (section 4, recipe on the dictionary). Characters the table lacks are looked up online (below).
3. Books whose Nom and Vietnamese pages differ in number (T1): `<book>_image_map.json`, or `--nom-order desc` for Nom read from the end.
4. Optional `names.txt`, one proper name per line (`Phi-lip-phê`): a run that reads as one is yellow when its Nom and Vietnamese character counts differ (and `reviewed` 1); with equal counts a wrong character stays red.
5. Declare the book type: `--mode phonetic` (diff every 1-1 row) or `--mode meaning` (all `null`). It is required; there is no `auto`. A book with both kinds gets `--ranges` (below).
6. Optional, for suggestions: a second Nom OCR `Label.txt` (`--ch-fallback`) and the similar-character CSV (`--similar`, or `NOM_ALIGN_SIMILAR` in `.env`).

## 4. Recipes

**A whole book from two label files**

```bash
uv run ocr-nom-align run --ch ch/Label.txt --vi vi/Label.txt --image-map Book_image_map.json \
    --book Book --mode phonetic --out-dir out --names names.txt --detail
# out/Book.csv  out/Book.xlsx  out/Book_align_report.json  out/Book_align_detail.jsonl
# and, when they have lines: out/Book_short_sentences.jsonl  out/Book_hyphens.jsonl
```

Smoke run first: three pages in each label file.

**The dictionary as `.jsonl` files**

The dictionary is handed out as `entries/<source>.jsonl` files. Use them as they are: no build, no conversion.

```bash
uv run ocr-nom-align readings 天 主 --table lexicon/entries       # folder: every *.jsonl in it; shows files and readings
uv run ocr-nom-align run --ch ch/Label.txt --vi vi/Label.txt --book Book --mode phonetic --out-dir out --table lexicon/entries
export NOM_ALIGN_TABLE=$PWD/lexicon/entries                        # or once, in .env
```

A file, a folder (it may be the folder that holds `entries/`), and `.jsonl.gz` all work; several `--table`
options are merged. Only the Vietnamese readings of single characters are used (SPECIFICATION §3.2). If the command
stops with `x.jsonl:N: not a dictionary entry`, a crawl log or another file is in the path: point at `entries/` itself.
The more entry files the folder holds, the fewer red `unknown_chars`.

**Characters the dictionary lacks** are searched online by themselves: when the run starts, every Nom character of the book
that no table file lists is looked up once on hvdic.thivien.net, added to the table and remembered in a cache file, so
the next run (and the next book) does not ask again. Nothing to do; what to know:

- Put your email in `NOM_ALIGN_CONTACT` (in `.env`): it goes in the `User-Agent` so the site can reach you.
- It needs network. Without it, or if the site refuses, those characters stay unknown (red) and one line on stderr says so;
  the run is not stopped. Rerun later: what was already found is in the cache.
- `--offline` (or `NOM_ALIGN_OFFLINE=1`) turns it off, for a reproducible run. The report has an `online` block: how many
  were asked, found, not found; list `online.not_found` to decide which characters to add to the dictionary by hand.
- Requests are one second apart and at most 300 per run: a very thin dictionary on a big book takes several runs to fill.

**A translation book (meaning, not reading)**: `--mode meaning --cost-mode length`. Every `text_diff` is `null`.

**A book that is partly phiên âm and partly translation**: declare `--mode phonetic` and list the translation parts in a ranges file, `--ranges ranges.json`:

```json
{"meaning": [
  {"from_image": "Lorem ipsum.010.jpg", "to_image": "Lorem ipsum.014.jpg"},
  {"from_sentence": "Lorem ipsum.030.2", "to_sentence": "Lorem ipsum.030.3"},
  {"from_sentence": "Lorem ipsum.040.1", "to_sentence": "Lorem ipsum.040.1"}
]}
```

Rows in a range get `text_diff` `null`. A range is either two images (`from_image`, `to_image`) or two sentence ids (`from_sentence`, `to_sentence`), both ends included, in reading order. For a T1 book the Nom pages are read from the end, so `"Lorem ipsum.010.2"` to `"Lorem ipsum.009.1"` is a valid range. The same id at both ends is one image or one row. Sentence ids are those of the final rows (`sentence_id` in the CSV, after merges): declare them again when you change the merges. An unknown id or a reversed range stops the run and names the id. `diff` takes `--ranges` too. `examples/ranges.json` is a sample.

**A book whose reading table is still thin**: `--unknown match` (unknown characters count as equal); read `unknown_chars` in the
report, extend the table, rerun without the flag.

**Rows already paired by a person or another tool**

```bash
uv run ocr-nom-align diff pairs.csv --out out/Book.csv --xlsx out/Book.xlsx --report out/Book_align_report.json
```

`pairs.csv` has `img_id, sentence_id, ch_txt, vi_txt` and optionally `kind` (`1-n`, `n-1`, `n-m` rows stay `null`).

**Short sentences.** `run` lists every sentence below `--short-warn` tokens (default 5; 0 turns it off) in `out/<book>_short_sentences.jsonl`, one line each: `{"side", "img_id", "sentence_id", "text", "tokens", "merge": "keep"}`. `keep` is the default and needs no action: a short sentence can be valid by itself, so no reason is needed. To join one to its neighbour, set `merge` to `prev` or `next` and run again with `--merges out/<book>_short_sentences.jsonl`. The merge happens before the alignment. A line whose text no longer matches (the split changed) stops the run: list the short sentences again. `--merge-short N` merges every sentence below N tokens automatically (default 0: never). Short sentences of the spec samples (3 to 4 tokens) will show up in the list; that is fine.

**Line-end hyphens.** With `--hyphen word` (default) a dash at a line end is joined, and kept when both parts start with a capital or the word is a listed name; otherwise it is dropped. Every joined hyphen is written to `out/<book>_hyphens.jsonl`: `{"img_id", "box", "left", "right", "result", "action", "reason", "reviewed"}` with `action` `kept` or `dropped` and `reason` `capitals`, `names`, `manual` or `default`. Check the lines with `reviewed` 0. Words that must keep their dash go into a UTF-8 file, one per line, hyphens included (`A-ve`; case does not matter), passed with `--hyphen-keep hyphens.txt`; their records become `reviewed` 1. There is no built-in list, so `A-ve` shows up for review until it is in your file (`examples/hyphen_keep.txt`). The report key `hyphen_inconsistent` lists words that appear both with and without a dash (`A-ve` and `Ave`); a word of the manual list is not reported for its listed form. `--hyphen space` drops every dash and keeps a space, `--hyphen keep` keeps every dash (old books).

**Suggestions for characters the dictionary rejects.** Where a Nom character does not fit its syllable, the tool can propose another character, from a second OCR of the same book or from the similar-character table:

```bash
uv run ocr-nom-align run --ch ch/Label.txt --vi vi/Label.txt --book Book --mode phonetic --out-dir out \
    --ch-fallback ch2/Label.txt --similar SinoNom_Similar_Dic_v2.csv
```

The second OCR is compared with the first per image by edit distance; only substituted positions give a character, and an image whose two texts differ by more than `--fallback-max-dist` (0.5) is skipped and listed in `fallback_skipped_images`. The similar table gives the first entry of the top-20 list that fits the syllable. Each hit is a yellow `warn` with `suggest` and `suggest_by` (`fallback` or `similar`); the text is not changed. See Review (workflow B).

**One cell, to see its `text_diff`**: `uv run ocr-nom-align demo 経告命命命。 "Kinh Cáo Mệnh."`

## 5. Review

Open the `.xlsx`: red = `error` (fix the Nom or the Vietnamese; Vietnamese must be exact), yellow = `warn`, black = equal.
In the report look at:

| Field | Reading |
|---|---|
| `kinds` | many `n-1` / `1-n` in a phonetic book mean the punctuation differs between the sides |
| `orphans_nom`, `orphans_vi` | only with `--allow-skip`: text without a partner (wrong page pairing or missing text); without it the run fails instead of leaving sentences out |
| `unknown_chars` | not in the table: add them, or confirm on the online dictionaries before you leave them red |
| `notes`, `images_missing_text` | pages without a partner, images named in the map but absent from the labels |
| `similarity`, `null_rate`, `yellow_rate` | the three numbers of the report to the teachers |
| `warn_reviewed`, `warn_unreviewed`, `suggested_fallback_chars`, `suggested_similar_chars` | yellow elements confirmed or not; pending suggestions |
| `low_match_rows`, `short_sentences`, `label_lint`, `hyphen_review`, `hyphen_inconsistent`, `fallback_skipped_images` | rows that read little like phiên âm, files to review, notes and marks still in `Label.txt`, hyphen records to check, images the second OCR could not be aligned for |

The CSV stays official. After any hand edit, rebuild the XLSX with `render` (never with `diff`, which recomputes `text_diff` and erases the fix) and run `check-diff`.

**Workflow A: manual fix of a character or a name.** Change every place that must stay in sync, then rebuild and check:

1. `ch/Label.txt` (or `vi/Label.txt`): the text of the box.
2. `out/<book>.csv`: `ch_txt` (or `vi_txt`) of the row.
3. `text_diff` of that row: positions and `*_sub_text` of the elements, or remove the element when the pair is now equal.
4. `ch/Label_char.txt`, when the book has it: the one box of the character.

```bash
uv run ocr-nom-align render out/Book.csv --xlsx out/Book.xlsx
uv run ocr-nom-align check-diff out/Book.csv --xlsx out/Book.xlsx --ch ch/Label.txt --vi vi/Label.txt \
    --ch-char ch/Label_char.txt
```

`check-diff` prints `row N: CODE: message` and exits 1 on an error. `SYNC` means the CSV text differs from a `Label.txt` (whitespace ignored, `-` ignored for Vietnamese); `SUB` means `*_sub_text` no longer equals the cell cut at `pos`; `SYNC_CHAR` means `Label_char.txt` differs from the CSV Nom text; `LABELCHAR` means a box holds more than one character, or the boxes are missing, extra or not in reading order; `XLSX` means the colours or text differ (run `render` again).
`Label_char.txt` is the PPOCRLabel format with exactly one character per box, boxes sorted in reading order; `[MASK]` may be one box.
The one exception to SYNC is a row of a lost page: with the image in `--missing-ch DIR` (Nom side predicted) or `--missing-vi DIR` (Vietnamese side predicted) the side is skipped, and the row needs one `warn` element that covers that whole side. Pass the same folders to `check-diff` and `apply`. A side without a `Label.txt` option is not checked.

**Workflow B: suggestions.**

```bash
uv run ocr-nom-align run ... --mode phonetic --ch-fallback ch2/Label.txt --similar SinoNom_Similar_Dic_v2.csv
# 1. open out/Book.xlsx: yellow characters with a suggestion; in out/Book.csv set "reviewed":1 on the ones you accept
uv run ocr-nom-align apply out/Book.csv --ch ch/Label.txt --vi vi/Label.txt --ch-char ch/Label_char.txt \
    --xlsx out/Book.xlsx --accept reviewed --reject-rest --out-dir fixed
uv run ocr-nom-align check-diff fixed/Book.csv --xlsx fixed/Book.xlsx --ch fixed/Label.txt --vi vi/Label.txt \
    --ch-char fixed/Label_char.txt --final
```

- `reviewed` is 0 or 1 on every `warn`; the report counts `warn_reviewed` and `warn_unreviewed`. A names file sets 1 on names.
- `apply --accept reviewed` (default) writes only suggestions with `reviewed` 1 into the Nom `Label.txt`; `--accept all` writes every one.
- Accepted: the character goes into `Label.txt`, `ch_txt`, `Label_char.txt` (one box) and the XLSX, and the element leaves `text_diff` (the character is black). `--reject-rest` turns each remaining suggestion into a red `error`. Without it they stay pending.
- `apply` runs SYNC first and writes nothing if `Label.txt` differs from the CSV, if `Label_char.txt` exists beside `--ch` and you did not pass `--ch-char`, or if a box does not hold the old character. It checks its own result with `check-diff --final`, then writes with exactly one of `--out-dir` or `--in-place` (which keeps a `.bak` of each file), and prints `applied`, `rejected`, `skipped`.
- A pending suggestion is a working state: `check-diff` warns (`SUGGEST_PENDING`), and `--final` makes it an error. Submit only data that passes `--final`.
- After a new `run` over a changed book, `diff --keep-reviewed OLD.csv` copies `reviewed` to equal `warn` elements.

## 6. Check and score

```bash
uv run ocr-nom-align check out/Book.csv --xlsx out/Book.xlsx   # "ok", or the problems and exit 1
uv run ocr-nom-align score out/Book.csv --min 95                # JSON; exit 1 under 95 %
uv run ocr-nom-align check-diff out/Book.csv --xlsx out/Book.xlsx --ch ch/Label.txt --vi vi/Label.txt --final
```

`check-diff` is the submission gate. Codes: `KEYS`, `OOB`, `SUB`, `OVERLAP`, `EDGE`, `MASK`, `SELECTOR`, `EMPTY`, `FORM`, `REVIEWED`, `SUGGEST`, `SUGGEST_PENDING`, `XLSX`, `SYNC`, `SYNC_CHAR`, `LABELCHAR`; each line is `row N: CODE: message`. `--strict` fails on warnings too (for example unreviewed `warn`). A CSV without `img_id` or `text_diff` (plain-text types) gets only `EMPTY`, `SELECTOR` and `FORM`.
`run` never writes a row with an empty side; `--allow-skip` is for diagnosis: unpaired sentences go to `out/<book>_align_orphans.jsonl` and never into the CSV.

## 7. Colab

`notebooks/align.ipynb`, same shape as the `ocr-engines` notebooks. Add the Colab secret `GITHUB_TOKEN` (key icon, Notebook access ON),
upload the two `Label.txt` files and the lexicon tables to `/content`, edit the CONFIG cell (book, label paths, table paths), then run
the cells top to bottom: BOOTSTRAP and SETUP (clone, install, check the files), RUN (`run`), REVIEW (`check`, `score`), ENV (fingerprint
for the report). Nothing is pushed anywhere; copy `OUT_DIR` where you need it.

## 8. Environment note for the report

Record Python version, OS, `uv.lock`, the dictionary files used (names and dates) and the command lines above.
`out/<book>_align_report.json` already holds `config` and `reading_sources`.

## 9. File formats

Every file, column and key: [SCHEMA.md](SCHEMA.md). Design and rules: [SPECIFICATION.md](SPECIFICATION.md).

## 10. Troubleshooting and cheat sheet

The README has the troubleshooting table and the command cheat sheet. First checks: `uv run ocr-nom-align readings 天 主` shows which table files were read; `unknown_chars` in the report lists what the table lacks.
