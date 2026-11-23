# ocr-nom-align specification

Status: v0.2.0, 2026-11-16. Describes what the code does today: reading table, sentence DP, `text_diff`, suggestions, the CSV / XLSX writer, `check`, `check-diff`, `apply`, `render` and `score`.
Marks: **[tune]** a guess that changes only with a gold sample. The files and their fields live in [`SCHEMA.md`](SCHEMA.md); this file says how the package uses them.
Not done and not tested here: an `ocr-flow` `Stage` class (the CLI and the library are the interface). The package never
touches a bucket, a journal or Colab; the notebook (same shape as the `ocr-engines` notebooks) only calls the CLI. `ocr_flow` is used there for the bootstrap and the environment fingerprint, never in the package.

## 1. Purpose

Align Sino-Nom sentences with Vietnamese sentences by Levenshtein distance on readings, and write the book CSV / XLSX.
This package is the sentence-level step. `ocr-align` aligns one character to one syllable inside a stream and ranks
OCR candidates; the two are independent and do not import each other.

## 2. Flow

```
<book>/ch/Label.txt            PPOCRLabel, Nom side             \
<book>/vi/Label.txt            PPOCRLabel, Vietnamese side       } ocr-nom-align run    sentences, DP (section 6)
<book>_image_map.json          optional page pairs              /
reading table                  entries/*.jsonl, lab_dict.csv, lexicon.sqlite, ...   (section 3.1)
out/<book>.csv                 official; text_diff (section 7)
out/<book>.xlsx                derived; coloured text
out/<book>_align_report.json   counts, similarity, unknown characters
out/<book>_align_detail.jsonl  with --detail
out/<book>_short_sentences.jsonl   sentences below short_warn tokens (section 5)
out/<book>_hyphens.jsonl       every joined line-end hyphen (section 4)
out/<book>_align_orphans.jsonl with --allow-skip only (section 6)
```

`diff` starts one step later, from rows that are already paired. `check`, `check-diff` and `score` read the CSV (and the XLSX, and for `check-diff` the `Label.txt` files). `render` writes the XLSX from a CSV, `apply` writes accepted suggestions into all files at once. Nothing here is committed; the notebook only calls the CLI.

## 3. Inputs

| Input | Form |
|---|---|
| `ch/Label.txt`, `vi/Label.txt` | PPOCRLabel: `<folder>/<image>\t[{"transcription":..., "points":...}]`; box order is reading order |
| reading table | any number of sources, merged (§3.1); never committed |
| pairs file (command `diff`) | `pairs.csv` / `pairs.jsonl`: `img_id, sentence_id, ch_txt, vi_txt[, kind]`, rows already paired |
| names (optional) | one proper name per line; a run that reads as one is `warn` (`reviewed` 1) when its Nom and Vietnamese character counts differ |
| book type | `--mode phonetic` or `meaning`, required: the author declares it; there is no automatic detection |
| ranges (optional) | `--ranges FILE`: JSON `{"meaning": [...]}`, image ranges and sentence-id ranges of a mixed book (§7.2) |
| second OCR (optional) | `--ch-fallback FILE`: a second Nom `Label.txt`, source of suggestions (§7.1) |
| similar table (optional) | `--similar FILE` or `NOM_ALIGN_SIMILAR`: `SinoNom_Similar_Dic` CSV, source of suggestions (§7.1) |
| hyphen list (optional) | `--hyphen-keep FILE`: words that keep their line-end hyphen, one per line |
| merges (optional) | `--merges FILE`: the short-sentences file with `merge` edited (§5) |
| image map (optional) | `<book>_image_map.json`: `{"pairs":[{"ch":[...],"vi":[...],"note":...}]}`, pairs in reading order |

### 3.1 Reading table

Sources: the dictionary entry files (`entries/<source>.jsonl`, plain or `.gz`; §3.2), `lab_dict.csv` (`char,syllable[,note]`) and a `lexicon.sqlite` (table `reading_table`, single-character heads only, opened read-only). Which one it is comes from the name (`.jsonl`, `.sqlite`, `.json`, else a CSV / TSV). A folder is searched in this order: `*.jsonl` (in the folder, else in `entries/`, else in `data/entries/`; `manifest*.jsonl` files are crawl logs and are skipped), then `lab_dict.csv`, then `lexicon.sqlite`. Keys drop the five tone marks and keep breve, circumflex, horn and `đ`; `tone_sensitive` keeps the tone too. A character is *known* when any source lists a reading. Support has three levels: first class, the `.jsonl` entry files (§3.2: found from a folder, validated line by line); second class, `lab_dict.csv` and `lexicon.sqlite`; third class, any other `.csv` / `.tsv` (`char,syllable` or `char<TAB>syl1,syl2`) or `.json` (`{"天": ["thiên"]}`), chosen by suffix and read best effort. The sources come from `--table` (repeatable), else `NOM_ALIGN_TABLE` (`:`-separated). An empty table is an error.

Without an image map pages are paired by page number when at least half the numbers agree (same-image or T2 books), otherwise by position
(`nom_order="desc"` reverses the Nom order, for T1). A pair with only a Nom side is reported; a pair with only a Vietnamese side is not aligned (its Nom page was lost in the scan, so there is nothing to align it with).

### 3.2 Entry files (`.jsonl`)

One JSON object per line, one dictionary entry; only these keys are read: `source`, `kind`, `head`, `script`, `unencoded`, `readings[].value`, `readings[].system`, `forms[].text`, `forms[].script`. The package reads them itself and imports no dictionary package.

- `script` `han` or `nom`, `unencoded` false, `head` one codepoint after dropping variation selectors (U+FE00..FE0F, U+E0100..E01EF): each reading of system `qn`, `hv` or `nom` is a reading of the character. `kind` `char`: always. `kind` `word` with a one-character head: only when the same `source` has a `char` entry for that head (the condition a `lexicon.sqlite` reading table applies).
- `script` `qn`: each `forms` item of script `nom` that is one codepoint and not `@img:...` makes that character read as the entry's `head`.
- Everything else (longer words, other scripts, other reading systems) is skipped. A blank line is skipped. A line that is not a JSON object with a string `head`, or is not valid JSON, raises `TableError` with `<file>:<line>`.
- Strings are NFC and keys are formed as for the other sources (§3.1). The result is the set of (character, syllable) pairs of the `reading_table` of a `lexicon.sqlite` built from the same entries, except that a head with a variation selector is kept (the build drops it); source weights are not needed for a set.

### 3.3 Online lookup

A Han or Nom character (`is_han`, not `〓`) of a Nom text that no table source lists is looked up once before alignment, unless `--offline` / `NOM_ALIGN_OFFLINE`. Request: `GET https://hvdic.thivien.net/whv/<character>`, then `/wnom/<character>` when that page lists nothing; a 404 means "no page". On the page, each block (`hvres han-word` / `nom-word`) whose head is exactly the character gives its `Âm Hán Việt` and `Âm Nôm` links as readings; readings of other characters on the page are ignored. The readings go into the table like any other source.

- Cache: JSON `{character: [readings]}` at `NOM_ALIGN_CACHE` (default `~/.cache/ocr-nom-align/online_readings.json`); a found or confirmed-empty answer is stored and never asked again; a failed request is not stored. A damaged cache is rebuilt.
- Courtesy and limits: standard library `urllib`, `User-Agent: ocr-nom-align/<version> (<NOM_ALIGN_CONTACT>)`, 10 s timeout, 1 s between requests, at most 300 requests per run. A block page (HTTP 403 / 429, or the site's access-denied text) ends the lookups of the run; so do 3 failed requests in a row. The characters not asked stay unknown.
- A failure is never fatal: the run continues, stderr gets one line, and the report `online` object counts `asked`, `cached`, `found`, `not_found` (listed), `failed` (listed), `skipped` and `stopped` (the reason, when set).
- `readings`, `demo`, `diff` and `run` look up; the library does nothing online unless `OnlineLookup.resolve(table, chars)` is called.

## 4. Text preparation

- NFC everywhere. Nom: all whitespace removed. Vietnamese: whitespace collapsed. Note marks `[1]` and `(1)` are removed only with `strip_notes` (default off: the CSV text must equal `Label.txt`, so notes are cleaned there, and `lint_label` lists them in the report as `label_lint`). The tool never edits `Label.txt` text on its own.
- Vietnamese lines are joined by one space. A line ending in `-` is joined to the next line: `hyphen="word"` (default) joins the two parts and keeps the dash when both parts start with a capital, or the word is in the names or in the `--hyphen-keep` list, else drops it; `"space"` drops the dash and keeps a space; `"keep"` joins without space and keeps the dash (old books).
- Each joined hyphen is one record of `<book>_hyphens.jsonl`: `img_id, box, left, right, result, action` (`kept` or `dropped`), `reason` (`capitals`, `names`, `manual`, `default`), `reviewed` (1 only for a word of the manual list). The records with `reviewed` 0 are the ones to check. The report lists `hyphen_inconsistent`: words that appear both with and without the dash (`A-ve`, `Ave`), unless one form is in the manual list. There is no built-in word list.
- Page texts of a side are concatenated in reading order before splitting, so a sentence cut by a page break is one sentence. It belongs to the image of its first character.
- `sentence_id = <image name without .jpg>.<n>`, `n` counted from 1 over the Nom sentences that start on that image (including sentences that end up merged or without partner).

## 5. Sentence splitting

Nom: `。！？；：` and ASCII `!?;:`, closing quotes and brackets stay with the sentence. Vietnamese: `. ? ! ; : …`; a dot is not a boundary after a single letter, a listed abbreviation (`Tp`, `St`, `Ts`, ...) or when the next word is lower case. A sentence with fewer than `short_warn` (5) tokens is listed in `<book>_short_sentences.jsonl` (`side, img_id, sentence_id, text, tokens, merge`); `merge` is `keep` by default, which needs no work (a short sentence can be valid on its own). Set it to `prev` or `next` and pass the file as `--merges` to join it to that neighbour before the DP; a line whose text no longer matches its sentence is an error. `merge_short` N joins every sentence below N tokens automatically (default 0: never); `short_warn` 0 turns the list off.
The split is a hint: a wrong split is repaired by the merge moves of §6.

## 6. Sentence DP

Moves `(a, b)`: `a` Nom sentences with `b` Vietnamese sentences. Allowed: `(1,1)`, `(1,n)`, `(n,1)` up to `max_group` (3), `(2,2)`, and skips `(1,0)`, `(0,1)` only with `allow_skip`.
Cost of a move with both sides:

`lev(nom characters, vi syllables) + merge_penalty*(a+b-2) + nm_penalty*[a>1 and b>1]`

`lev` is Levenshtein with gap cost 1 and substitution cost 0 (the syllable is a reading), `mismatch_cost` 1.0 (character known, syllable is not one of its readings) or `unknown_cost` 0.5 (character in no table, or a number token). Matching is tone-insensitive unless `tone_sensitive`. If the two lengths differ by more than a factor `1/min_len_ratio` (2) the cost is `max(n, m)` without running the Levenshtein. `cost_mode="length"` replaces `lev` by a length-ratio term (for translations where readings are useless).
A skip (with `allow_skip`) costs `skip_base + skip_per_token * tokens` and stays below a merge that only absorbs the surplus (`skip_base < merge_penalty`).
The DP runs in a band around the page-pair diagonal (anchors from the pairs; straight line without pairs), half-width `band` (default 25 with pairs, else `max(40, 10 %)`), doubled up to three times if no path exists, and drops states costing more than the best state of the row plus `beam` (40). Failure raises `AlignFailed` with a hint (without skips a path may not exist when the texts differ too much).
Rows: a row never has an empty side. Without `allow_skip` every sentence is paired. With `allow_skip` (diagnosis only) the unpaired sentences go to `orphans_nom` / `orphans_vi` in the report and to `<book>_align_orphans.jsonl` (`side, img_id, sentence_id, text`), never into the CSV; the second-OCR map is off then because rows are no longer contiguous.

## 7. Row kinds and `text_diff`

| Kind | `text_diff` |
|---|---|
| 1-1 with `mode="phonetic"`, not in a `meaning` range | array (`[]` if equal) |
| 1-1 with `mode="meaning"`, or in a `meaning` range of `--ranges` | `null` |
| 1-n, n-1, n-m | `null` (a merged row is a translation); `merged_diff="phonetic"` diffs them anyway |

The declared mode decides, never the text. `phonetic_min_match` (0.6 **[tune]**) only feeds the report list `low_match_rows`: rows whose share of aligned pairs that are not a known mismatch is below it.

Diff of a phonetic row: tokens are Nom characters (Han, extension planes, private use, and 〓) and Vietnamese syllables / numbers (split at spaces, dashes, punctuation). `[MASK]` splits both texts; segment `k` pairs with segment `k` (if the mask counts differ the masks are ignored and the text is aligned jointly). Levenshtein edit script; ties in the backtrace prefer a gap, so surplus Nom characters are the *last* repeats (`経告命命命` gives `[[3,5]]`).
A maximal run of non-equal operations is one element. `type` is:

- `warn` when the run contains a number token and Nom characters (`warn_numbers`), or, with `warn_names`, when all Vietnamese tokens are capitalised and the two sides have different lengths;
- `error` otherwise, always when the run holds 〓.

A run whose Vietnamese side is a proper name of the `names` list (a whole name or syllables inside one) is `warn` as well, but only when the Nom and Vietnamese character counts of the run differ; with equal counts the run is `error` (a wrong character is not a name). Such a name is written with `reviewed` 1.
Every `warn` has `reviewed` (0 or 1, written after the five keys); a number or heuristic `warn` is 0. In the spec `reviewed` is optional and absent means 0, and key order is not significant; the tool always writes the same order. An `error` never has `reviewed`. A pair whose character is in no table is `error` by default (`unknown_policy="error"`); `"match"` treats it as equal (use while the table is incomplete; the report lists the unknown characters either way).
`pos` ranges are half-open, 0-based, code points of the NFC cell, one range per side per element, first and last character are letters; punctuation or spaces inside a range are coloured with it. A side without characters has `pos` `[]` and sub text `""`.

### 7.1 Suggestions

A substituted pair that the DP marked mismatch (or unknown with `unknown_policy="error"`) can get a suggested Nom character. The DP is not changed by it; positions, `ch_txt` and `vi_txt` stay as they are. The element becomes a one-pair `warn` with `reviewed` 0, `suggest` (one character) and `suggest_by`. Sources, in this order, each accepted only when the Vietnamese syllable is a reading of the suggested character:

1. `fallback`: the character at the same place in the second OCR `Label.txt` (`--ch-fallback`). The two Nom streams of an image are aligned by character Levenshtein (ties: diagonal, then delete, then insert); only substituted positions give a character. An image whose edit distance over its length exceeds `fallback_max_dist` (0.5), or that the second file lacks, is skipped and listed in `fallback_skipped_images`.
2. `similar`: the first compatible entry, by rank, of the top-20 list of the Nom character in the similar table (`SinoNom_Similar_Dic` CSV, `--similar`). A list that does not parse is empty and counted in `similar_parse_errors`.

A suggestion is a working state. Before submission each one is accepted by `apply` (the character goes into `Label.txt`, `ch_txt`, `Label_char.txt`; the element is removed, so the character is black) or rejected by `apply --reject-rest` (the element becomes a red `error`). `check-diff --final` fails on a pending one. Only the Nom `Label.txt` changes.

### 7.2 Ranges file

`{"meaning": [range, ...]}`, ranges inclusive, in reading order (for T1 the Nom pages are read from the end, so `from` can have a higher page number than `to`). A range is `{"from_image", "to_image"}` (rows whose `img_id` lies between them) or `{"from_sentence", "to_sentence"}` (rows from one `sentence_id` to the other). Sentence ids are those of the final rows, after merges, so declare them again when the merges change. `run` / `diff` stop with a message that names the id when an id is unknown or a range is reversed. The file format is the tool's own input, not part of the submission.

## 8. Files and commands

Commands: `run` (two `Label.txt` files, optional image map, `--mode` required; writes `<out-dir>/<book>.csv`, `.xlsx`, `_align_report.json`, `_short_sentences.jsonl` and `_hyphens.jsonl` when they have lines, with `--detail` `_align_detail.jsonl`), `diff` (rows already paired: recompute `text_diff` with the same rules, so a hand fix of `text_diff` is lost; `kind` `1-1` by default, merged kinds stay `null`; `--keep-reviewed OLD.csv` copies `reviewed` to equal `warn` elements), `render CSV --xlsx F` (XLSX from the stored `text_diff`, never recomputes), `check`, `check-diff` (§9.1), `apply` (§9.2), `score [--min N]`, `demo CH VI`, `readings CHARS`. Exit codes: `0` ok, `1` an error or a failed check.


`<book>.csv`: UTF-8 with BOM, `csv` module quoting, `text_diff` compact JSON (`ensure_ascii=False`) or the four letters `null`; no line breaks in cells.
`<book>.xlsx`: sheet `align`, same columns; `ch_txt` and `vi_txt` are rich text, red `FF0000` for `error`, yellow `FFFF00` for `warn`, black elsewhere (`--error-color`, `--warn-color`, `--black-color` accept only the Excel standard pair and `D32F2F` / `D99A00`; reading compares the last six hex digits). The CSV is official when they disagree. Open: the Nom column has no Han-Nom font yet.
`<book>_align_report.json`: counts, kinds, similarity, null and yellow rates, orphans, unknown characters, notes, reading sources, online lookup, `mode`, `meaning_rows`, suggestion and review counters, `fallback_skipped_images`, `similar_parse_errors`, `short_sentences`, `low_match_rows`, `label_lint`, `hyphen_review`, `hyphen_inconsistent`, `yellow_by_reason`, config. `<book>_align_detail.jsonl`: per row `img_id, sentence_id, kind, vi_img, phonetic`. Field formats: [`SCHEMA.md`](SCHEMA.md).

## 9. Checks (`check`)

CSV: exact columns; NFC; no line breaks; `img_id` ends in `.jpg` without folder; `sentence_id` is `<img stem>.<n>`; `text_diff` is `null` or an array whose elements have the key set of their type (an `error`: the five keys; a `warn`: the five, plus optional `reviewed`, `suggest`, `suggest_by`; order is not checked, unknown keys are an error), `type` in `warn`/`error`, ranges inside the cell, ascending, non-overlapping inside and across elements (a character is in at most one element), edges on letters, no `[MASK]`, sub text equal to the cut, not both sides empty.
XLSX (with `--xlsx`): same number of rows; per character the colour equals the state derived from the CSV `text_diff`; a colour outside the accepted set, a theme or an indexed colour is a problem. The first sheet is read when none is named `align`.

### 9.1 `check-diff`

`check-diff CSV [--xlsx F] [--ch F] [--vi F] [--ch-char F] [--image-map F] [--nom-order asc|desc] [--missing-ch DIR] [--missing-vi DIR] [--strict] [--final] [--sync-loose|--sync-exact]`. Lines are `row N: CODE: message`; exit `1` on any error; `--strict` makes warnings errors; `--final` is the submission gate.

| Code | Level | Meaning |
|---|---|---|
| `KEYS` | error | key set wrong for the type, unknown key, or a missing column |
| `OOB` | error | range not two integers, start not below end, or outside the cell |
| `SUB` | error | `*_sub_text` differs from the cell cut at `pos` (fix `ch_txt` / `vi_txt`, `text_diff`, `Label.txt` and `Label_char.txt` together) |
| `OVERLAP` | error | ranges overlap or are not ascending, or a character is in two elements |
| `EDGE` | error | a range starts or ends on a non-letter |
| `MASK` | error | a range covers `[MASK]` |
| `SELECTOR` | error | `ch_txt` holds a variation selector |
| `EMPTY` | error | `ch_txt` or `vi_txt` is empty, or both sides of an element are |
| `FORM` | error | not NFC, or a line break in a cell |
| `REVIEWED` | error / warning | value not 0 or 1 (error); count of `warn` with `reviewed` 0 or absent (warning) |
| `SUGGEST` | error | `suggest` without `suggest_by` or the reverse, not one character, `suggest_by` not `fallback` / `similar`, `nom_pos` not one range of length 1, or a suggestion on an `error` |
| `SUGGEST_PENDING` | warning; error with `--final` | a `warn` with `suggest` is still there |
| `XLSX` | error | colour outside the accepted set, colours differ from `text_diff`, or the text differs |
| `SYNC` | error | the CSV text differs from `Label.txt` on a side that has a file |
| `SYNC_CHAR` | error | `Label_char.txt` differs from the CSV Nom text, per image, boxes in order |
| `LABELCHAR` | error | a box holds more than one character (`[MASK]` may be one box), or the boxes of an image, concatenated, differ from its Nom text in `Label.txt` (missing, extra or unsorted boxes) |

SYNC: the text of the CSV must equal `Label.txt` (mandatory; whitespace ignored, `-` ignored for Vietnamese), in the page order `run` would use. `--ch` and `--vi` are independent: a side without a file is not checked. The only exception is a row of a lost page (image name in `--missing-ch` for the Nom side, `--missing-vi` for the Vietnamese side): that side is cut out of the comparison, and the row needs one `warn` element covering the whole side. Every other row, a fully yellow name row included, must match. `--sync-exact` also lists the exact `join_vi` difference as a warning. A CSV without `img_id` / `text_diff` columns (plain-text types) gets only `EMPTY`, `SELECTOR`, `FORM`, and the output says so.

### 9.2 `apply`

`apply CSV --ch F --vi F [--ch-char F] [--xlsx F] [--image-map F] [--nom-order asc|desc] [--missing-ch DIR] [--missing-vi DIR] [--accept reviewed|all] [--reject-rest] (--out-dir D | --in-place)`, exactly one of the two. In this order:

1. SYNC runs first; on any difference nothing is written (exit `1`).
2. If `Label_char.txt` exists beside `--ch` and `--ch-char` is missing, exit `1`. With `--ch-char` the LABELCHAR check runs on each image to change, and the box must hold the old character; otherwise exit `1`.
3. Accepted: `warn` with `suggest`; with `--accept reviewed` (default) only those with `reviewed` 1, with `all` every one. The new character goes into the Nom `Label.txt` (only that box's `transcription` in `Label_char.txt`), `ch_txt` changes by one character for one character, and the element is removed from `text_diff` (`[]` when none is left), so other positions stay valid.
4. `--reject-rest`: every other pending suggestion becomes an `error` (drop `reviewed`, `suggest`, `suggest_by`); the text is unchanged.
5. The XLSX is rebuilt from the new CSV, `check-diff --final` runs on the outputs, and the files are moved into place one by one (`--out-dir`, or `--in-place` with a `.bak` of each). A failed check writes nothing. The output line is `applied=N rejected=N skipped=N`, and a report next to the CSV gets `suggestions_accepted`, `suggestions_rejected`.

## 10. Similarity

Over rows whose `text_diff` is not `null`: `(1 - red / scored) * 100`. `red` is the sum over `error` elements of the larger of the Nom character count and the Vietnamese syllable count. `scored` is the Nom characters of those rows without punctuation, `[MASK]` and yellow characters. A pending suggestion is yellow, so it is not scored until `apply` accepts or rejects it. Also reported: `null_rate` (rows with `null` over all rows), `yellow_rate` (yellow Nom characters over Nom characters of phonetic rows), `warn_reviewed` and `warn_unreviewed` (absent counts as unreviewed), `suggested_fallback_chars` and `suggested_similar_chars` (pending only), counts of merged rows.

## 11. Consumers

| Reader | Reads | Uses it for |
|---|---|---|
| the group | `<book>.csv`, `<book>.xlsx` | review in Excel, then the submission |
| `ocr-validate` | the same files, inside a submission | the rules of the guide: `text_diff`, colours, the 95% score; the source of truth for submission rules |
| `ocr-lexicon` | none | its entry files, `lab_dict.csv` and `lexicon.sqlite` are this package's reading table (section 3.1) |

The package imports none of them. Files are the interface.

## 12. Tests

Synthetic only, no network (`tests/conftest.py` turns the online lookup off). `tests/test_diff.py`: `text_diff` positions, kinds and `[MASK]`. `tests/test_sentences.py`: splitting. `tests/test_book.py`: pages, DP, a whole book. `tests/test_tables.py`: reading table sources. `tests/test_online.py`: the lookup with fake pages. `tests/test_io.py`: CSV, XLSX, `check`, `score`. `tests/test_rows_cli.py`, `tests/test_jsonl.py`: `diff` and the CLI. `tests/test_check_diff.py`: every `check-diff` code, SYNC and predicted rows. `tests/test_apply.py`: `apply`, `--reject-rest`, `Label_char.txt`. `tests/test_suggest.py`: similar table, second-OCR map, suggestions. `tests/test_hyphens.py`: hyphen records and inconsistency. `tests/test_handoff_misc.py`: smaller rules of the v0.2.0 change. `tests/test_import_rules.py`: no sibling imports.

## 13. Open

- Dictionary coverage decides how sharp the DP is: with few known characters the cost is mostly length, and `unknown_policy="error"` makes every unknown Nom character red. The online lookup (§3.3) fills gaps for Han characters; rarer Nom characters often stay unknown. Read `unknown_chars` and `online.not_found`, add a table source, rerun.
- The online lookup parses one site's page layout; if the site changes it, lookups return nothing (the run still works) and `online.not_found` fills up.
- Names and years of unequal length are red unless `warn_names` (heuristic), the names file or the number rule applies; set yellow by hand or with `predicted_diff` where the text allows it.
- Merged rows (`merged_diff`) and the report metrics matrix are parked: merged kinds keep their `null` behaviour.
- The XLSX writer sets no Han-Nom font on `ch_txt` (`ocr-validate` warns `XLSX-FONT`).
- `examples/similar.csv` is a one-row illustration; the real `SinoNom_Similar_Dic_v2.csv` is not in the repo.
- Sentence boundaries that differ between the two sides make n-1 / 1-n rows, which are `null`; prefer fixing punctuation in a phonetic book.
- `predicted_diff` does not handle `[MASK]` inside a predicted row.
- Pure Python Levenshtein: about 5 s for 3,000 sentences on the test machine.

## 14. Repository rules

1. The package imports no other module repo (`ocr_align`, `ocr_flow`, ...), no third-party network or image library; the only network use is the online lookup (§3.3), with `urllib`. The files
   are the contract (`tests/test_import_rules.py`).
2. Only `cli.py` imports `click`. The library reads and writes files it is given and prints nothing.
3. `.csv` is official; the `.xlsx` is derived from it and checked against it. Never extend the CSV columns.
4. A check that fails is a stop: `check` exits `1` and lists the rows; nothing is repaired silently.
5. Costs and thresholds marked **[tune]** change only with a gold sample and a note in `HANDOFF.md`.
