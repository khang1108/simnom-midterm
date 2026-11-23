# ocr-nom-align schema (v1)

The files the package reads and writes: the reading table (input), the book CSV and XLSX, the image map, the pairs file, the report and the detail file. Code: `readings.py` (reading table), `rows.py` and `diff.py` (rows, `text_diff`), `tableio.py` (CSV, XLSX), `report.py` (the run report), `validate.py` (`check`, `check-diff`, `score`), `ranges.py`, `suggest.py`, `sync.py` (`apply`). Tests: `tests/test_io.py`, `tests/test_tables.py`, `tests/test_check_diff.py`, `tests/test_apply.py`.

This revision adds optional keys and new files only, so the schema version stays v1.

## 1. Who reads what

| Consumer | Reads | How |
|---|---|---|
| the group | `<book>.xlsx` | review in Excel: red `error`, yellow `warn`, black equal |
| `ocr-validate` | `<book>.csv`, `<book>.xlsx` | submission rules, colours and the 95% score (source of truth; it must mirror section 3 and 4) |
| this package | `entries/*.jsonl`, `lab_dict.csv`, `lexicon.sqlite` | the reading table, never committed; written by `ocr-lexicon` |

## 2. Reading table sources (input)

First class: `entries/*.jsonl`. Second class: `lab_dict.csv`, `lexicon.sqlite`. Third class: any other `.csv` / `.tsv` / `.json`.

| Source | Form |
|---|---|
| `entries/<source>.jsonl` (also `.jsonl.gz`, or the folder) | one dictionary entry per line: `{"id", "source", "kind", "head", "script", "readings": [{"value", "system"}], "forms": [{"text", "script"}], "unencoded", ...}`; other keys are ignored (SPECIFICATION §2.2) |
| `lab_dict.csv` | `char,syllable[,note]`, no header needed |
| `.csv` / `.tsv` (any other) | `char,syllable` or `char<TAB>syl1,syl2` |
| `.json` (any other) | `{"天": ["thiên", "trời"]}` |
| `lexicon.sqlite` | table `reading_table(head, syllable, ...)`, read-only |

Example entry file line (`entries/hvdic.jsonl`):

```json
{"id": "hvdic:1", "source": "hvdic", "kind": "char", "head": "天", "script": "han", "readings": [{"value": "thiên", "system": "hv"}]}
```

## 3. `<book>.csv`

UTF-8 with BOM, `csv` quoting, no line breaks in a cell, NFC.

| Column | Meaning |
|---|---|
| `img_id` | image name without folder, ends in `.jpg`; the image holding the first character of the Nom sentence |
| `sentence_id` | `<img_id without .jpg>.<n>`, `n` from 1 over the Nom sentences that start on that image (an n--1 / n--m row takes the first) |
| `ch_txt` | Nom text, whitespace removed |
| `vi_txt` | Vietnamese text, sentences of a group joined by one space |
| `text_diff` | the four letters `null`, `[]` or an array of elements |

Element key sets. Key order is not significant for a reader; the tool always writes the order below. An unknown key is an error.

- `error`: exactly `nom_pos`, `nom_sub_text`, `vi_pos`, `vi_sub_text`, `type`.
- `warn`: the same five, then `reviewed`, then, only when a suggestion exists, `suggest` and `suggest_by`. `reviewed` is optional when reading (absent means 0); the tool writes it on every `warn`.

| Key | Type | Meaning |
|---|---|---|
| `nom_pos` / `vi_pos` | `[[start, end]]` or `[]` | half-open, 0-based code points of the NFC cell; first and last character are letters |
| `nom_sub_text` / `vi_sub_text` | string | the cell cut at the range; `""` when the range is `[]` |
| `type` | `error` \| `warn` | red / yellow; black is never written |
| `reviewed` | `0` \| `1` | only on `warn`; 1 when a person or a names file confirmed it. An `error` never has it |
| `suggest` | one code point | only on `warn`; the Nom character that would replace the one at `nom_pos`, which is then one range of length 1 |
| `suggest_by` | `fallback` \| `similar` | where the suggestion came from; always together with `suggest` |

Shape examples (compact JSON as written):

```
{"nom_pos":[[3,4]],"nom_sub_text":"命","vi_pos":[[10,14]],"vi_sub_text":"Mình","type":"error"}
{"nom_pos":[[0,3]],"nom_sub_text":"丕離批","vi_pos":[[0,8]],"vi_sub_text":"Philiphê","type":"warn","reviewed":1}
{"nom_pos":[[5,6]],"nom_sub_text":"毋","vi_pos":[[14,17]],"vi_sub_text":"Mẫu","type":"warn","reviewed":0,"suggest":"母","suggest_by":"fallback"}
```

`[MASK]` is never inside a range. A character is in at most one element. Positions, `ch_txt` and `vi_txt` never change because a suggestion exists. A `warn` with `suggest` is a working state: it is accepted (`apply`; the element is removed) or rejected (`apply --reject-rest`; it becomes an `error`) before submission, so submitted data has none (`check-diff --final` fails on one). `text_diff` is `[]`, not `null`, when an `apply` removed the last element.

The text of `ch_txt` and `vi_txt` equals `Label.txt` (whitespace ignored, `-` ignored for Vietnamese), except for a side of a row whose image is in `missing/ch` or `missing/vi` (a lost page): that side is one whole `warn` element.

## 4. `<book>.xlsx`

Sheet `align` (the first sheet is read when none has that name), same columns. `ch_txt` and `vi_txt` are rich text: `FF0000` inside
an `error` range, `FFFF00` inside a `warn` range, black elsewhere. The tool writes only these standard colours (Excel palette), so
`--error-color`, `--warn-color` and `--black-color` take only the accepted set below.

| State | Accepted when reading |
|---|---|
| error (red) | `FF0000`, `D32F2F` |
| warn (yellow) | `FFFF00`, `D99A00` |
| equal (black) | `000000`, or no colour |

Colours are compared on the last six hex digits, because Excel stores ARGB (`FFFF0000`). Any other colour, a theme colour or an
indexed colour is an unknown colour and a problem. `ocr-nom-align check B.csv --xlsx B.xlsx` compares colour and `text_diff` per
character; `render` writes the XLSX from the stored `text_diff` and never recomputes it. The Nom column has no Han-Nom font yet (open).

## 5. `<book>_image_map.json` (input, optional)

```json
{"pairs": [{"ch": ["Book.010.jpg"], "vi": ["Book.012.jpg", "Book.013.jpg"], "note": ""}]}
```

Pairs in reading order; a pair with both sides empty is an error.

## 6. `pairs.csv` / `pairs.jsonl` (input of `diff`)

Columns or keys `img_id, sentence_id, ch_txt, vi_txt`, optional `kind` (`1-1` default, `1-n`, `n-1`, `n-m`). Any `text_diff`
column is ignored and recomputed.

## 7. `<book>_align_report.json`

`rows, phonetic_rows, null_rows, null_rate, nom_chars_phonetic, yellow_chars, yellow_rate, red_chars, scored_chars,
similarity` (see SPECIFICATION §10), `warn_reviewed`, `warn_unreviewed` (absent `reviewed` counts as unreviewed),
`suggested_fallback_chars`, `suggested_similar_chars` (pending only), `kinds` (count per row kind), `unknown_chars` (character to count), `orphans_nom`,
`orphans_vi` (only with `--allow-skip`), `nom_sentences`, `vi_sentences`, `notes`, `images_missing_text`, `reading_sources`, `online` (`null` with `--offline`, else `source`, `asked`, `cached`, `found`, `not_found`, `failed`, `skipped`, `stopped`), `config` (every
`NomAlignConfig` field).

Added by this revision (`run`; `diff` writes the ones that apply to it):

| Key | Meaning |
|---|---|
| `mode` | the declared book type |
| `meaning_rows`, `meaning_ranges` | number of rows in a `meaning` range, and the ranges used |
| `suggested_fallback`, `suggested_similar` | pending suggestions found by source |
| `suggestions_accepted`, `suggestions_rejected` | counts by source, added by `apply` when a report sits beside the CSV |
| `fallback_skipped_images` | images the second OCR could not be aligned for (too different, or missing) |
| `similar_parse_errors` | entries of the similar table that did not parse |
| `short_sentences` | `{count, file}` of the short-sentences file |
| `low_match_rows` | `sentence_id` of rows below `phonetic_min_match` |
| `label_lint` | per side (`ch`, `vi`), count per kind: `note_mark`, `line_end_hyphen`, `selector`, `not_nfc`, `stray_whitespace` |
| `hyphen_review` | `{count, file}`: records with `reviewed` 0 |
| `hyphen_inconsistent` | words found both with and without a dash: `{key, forms: {form: [offsets]}}` |
| `yellow_by_reason` | `warn` count by reason: `name`, `number`, `suggest_fallback`, `suggest_similar`, `heuristic` |
| `reviewed_kept` | `diff --keep-reviewed`: elements that took `reviewed` from the old CSV |

## 8. `<book>_align_detail.jsonl` (`--detail`)

One line per CSV row: `img_id, sentence_id, kind, vi_img, phonetic`. `kind` is `1-1`, `1-n`, `n-1` or `n-m`. No row has an empty side, so `nom-only` and `vi-only` are no longer written.

## 9. Online lookup cache

`NOM_ALIGN_CACHE` (default `~/.cache/ocr-nom-align/online_readings.json`): one JSON object, character to the list of readings the
site gave; `[]` means the site was asked and has nothing. Delete the file to ask again.

## 10. `--ranges` file (input, optional)

```json
{"meaning": [
  {"from_image": "Lorem ipsum.010.jpg", "to_image": "Lorem ipsum.014.jpg"},
  {"from_sentence": "Lorem ipsum.030.2", "to_sentence": "Lorem ipsum.030.3"}
]}
```

Only the key `meaning`. Each range uses either `from_image` + `to_image` or `from_sentence` + `to_sentence`, both ends included, in
reading order (T1: `010.2` to `009.1` is valid). The same id at both ends is one image or one row. Sentence ids are those of the final rows.

## 11. `<book>_short_sentences.jsonl` and `--merges`

One line per sentence below `short_warn` tokens: `{"side", "img_id", "sentence_id", "text", "tokens", "merge"}`. `side` is `nom` or `vi` (a
Vietnamese `sentence_id` is `<img stem>#<n>`); `merge` is `keep` (default, no action), `prev` or `next`. `run --merges FILE` reads
the file after you edited `merge`; a line whose text no longer matches is an error.

## 12. `<book>_hyphens.jsonl` and `--hyphen-keep`

One line per joined line-end hyphen: `{"img_id", "box", "left", "right", "result", "action", "reason", "reviewed"}`. `action` is `kept` or
`dropped`; `reason` is `capitals`, `names`, `manual` or `default`; `reviewed` is 1 only for `manual`. `--hyphen-keep FILE`: UTF-8, one
word per line exactly as it should appear, hyphens included, compared case-insensitively; `#` lines and blank lines are ignored.

## 13. Similar table, `<book>_align_orphans.jsonl`

- `--similar FILE` (`SinoNom_Similar_Dic` CSV, UTF-8, a BOM is accepted): header `"Input Character","Top 20 Similar Characters"`, each value a Python list literal in a string, e.g. `"['毋', '毎']"`; list order is the rank. A value that does not parse is an empty list.
- `<book>_align_orphans.jsonl` (`--allow-skip` only): `{"side", "img_id", "sentence_id", "text"}` per sentence left without a partner. For diagnosis; never in the CSV.

## 14. What is not in v1

No schema version field in the files (the header columns are the version). Per-character confidence, alternative readings per row and `kind` in the CSV are not written; `kind` lives in the detail file only. The optional keys `reviewed`, `suggest`, `suggest_by` are additive, so v1 data without them stays valid.
