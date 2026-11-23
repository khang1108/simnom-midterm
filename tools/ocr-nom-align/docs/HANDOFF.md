# ocr-nom-align HANDOFF

The only handoff. Read it first. Section 6 is the work to do now; everything before it is standing context.
Other docs: `docs/USER_GUIDE.md`, `docs/SPECIFICATION.md`, `docs/SCHEMA.md`.

## 1. Rules for the assistant (the user's standing instructions)

1. Reply in English, terse (caveman/ultracave). Full prose for warnings, multi-step order, irreversible actions, and anything written into docs, code or commits.
2. Give full copy-paste commands. Send files (SendUserFile) as soon as they exist, not at the end.
3. Use "Vietnamese" everywhere, never "quoc ngu", in code, docs and messages.
4. Keep the layout of `ocr-lexicon`: README, docs set, config files, project structure. Same for `ocr-validate`; the three repos stay consistent.
5. Lint: `ruff`, line length 100. Tests: `uv run pytest` or `python tools/offline_pytest.py`.

- The package is files in, files out (SPECIFICATION §14). No `ocr-flow` import, no bucket. The one network use is the online lookup of unknown characters (SPECIFICATION §3.3); tests never reach it (`tests/conftest.py` turns it off).
- Costs and thresholds marked **[tune]** change only with a gold sample.
- The CSV is official; the XLSX is derived and checked against it.
- Comments say why only.

## 2. What the project is

`ocr-nom-align` aligns Sino-Nom sentences with their Vietnamese reading by Levenshtein distance and writes the book `<book>.csv` / `.xlsx` with `text_diff`. Layout: `align.py` (sentence DP), `sentences.py`, `pages.py`, `tokens.py`, `lev.py`, `diff.py` (`text_diff`), `rows.py`, `tableio.py` (CSV, XLSX, `render`) and `readings.py` (reading table), `online.py` (lookup), `ranges.py` (`--ranges`), `suggest.py` (similar table, second-OCR map, suggestions), `sync.py` (`apply`), `report.py`, `validate.py` (`check`, `check-diff`, `score`), `config.py`, `cli.py`.
Related repos (files are the interface): `ocr-lexicon` (entry files, `lab_dict.csv`, `lexicon.sqlite` are the reading table), `ocr-validate` (checks the submission rules on the CSV / XLSX; the source of truth for them).

## 3. State (v0.2.0)

132 tests pass (`PYTHONPATH=src python -m pytest -q`, offline; `tools/offline_pytest.py` is the stand-in for a sandbox without pytest).

Online lookup (`online.py`): written against the page structure of `hvdic.thivien.net/whv/<character>` and tested with
fake pages and a fake `get`; **it has not been run against the live site** (no network in the build sandbox). First task on
a machine with network: `uv run ocr-nom-align readings 天 𠀧 --table <any small table>` and check that readings come back;
if they do not, fix `parse_char_page` only (the rest is covered by tests). Cache and request limits are in SPECIFICATION §3.3.

Checked: the reading table read from `entries/*.jsonl` equals the one in a `lexicon.sqlite` and a `lab_dict.csv` built from
the same entries (one deliberate difference: a head with a variation selector is kept). `.jsonl` is the form in which the
dictionary is handed out, so it is the main source and `lab_dict.csv` / `lexicon.sqlite` are alternatives.

### 3.1 Where the code came from

Five earlier implementations were merged. The base is the workspace one (`ocr-nom-align.zip`, package under `packages/`),
because it is the only one that covers the whole submission format end to end: image map, page pairing, sentence DP, `text_diff` with
`[MASK]`, CSV + XLSX writer, `check`, similarity. The others were read, not run.

| Version | What was taken | What was left |
|---|---|---|
| `ocr-nom-align.zip` (workspace) | everything in `align`, `diff`, `pages`, `sentences`, `tokens`, `tableio`, `validate`, `lev` | the monorepo layout |
| `(1)` labels / tables / levenshtein | idea of `align.jsonl` per row, now `--detail` | its own DP and sentence rules (the base has the same moves) |
| `(2)` pairing / rows / check / score | `diff` command on already paired rows, `score --min`, reading table from `lexicon.sqlite`, `readings` listing | strict-tone default and the guessed 0.5 / 0.5 row thresholds |
| `(3)` xlsx / names / demo | `--names` file (yellow for names), `demo` command, `python -m ocr_nom_align` | tone-only cost 0.2, the `am` / `nghia` column |
| `(4)` sentences / rows / rowalign / table | `NOM_ALIGN_TABLE` environment list, folder as a reading source | its own sentence DP and weighted syllable distance |

## 4. Open problems

- The online lookup has not run against the live site (section 3); fix `parse_char_page` only if readings do not come back.
- `uv sync` with the real lock file has not been run in the build sandbox (no network).
- The XLSX writer leaves the Nom column in Calibri; `ocr-validate` warns (`XLSX-FONT`). Set a Han-Nom font on `ch_txt` in `tableio.py`.

## 5. Later work (in order)

1. Run `uv sync` and `uv run pytest` with the real lock file; fix what they report.
2. Gold sample: tune `phonetic_min_match` (0.6), `unknown_cost` (0.5), `merge_penalty`, `nm_penalty`, `beam`.
3. Re-run keeping existing `warn` elements (exclude their tokens from the alignment).
4. Variant fallback in the reading table (variant characters, lower weight) to cut false red.
5. Sentence pairing for translation books: `cost_mode="length"` is weak; anchors from `ocr-align` are needed.
6. `ocr-flow` `Stage` class after `ocr-align`, once the CLI is stable (spec: not done).

## 6. Current work (2026-11-16): spec v2.4 changes, v0.2.0

### 6.1 Intent
Bring the SN-QN fallback ideas (second OCR, similar-character table) into this tool as reviewable suggestions, keep `Label.txt`, CSV, `Label_char.txt` and XLSX in sync, and follow the v2.4 submission rules. The output contract stays intact: same CSV columns, `ch_txt` / `vi_txt` equal the `Label.txt` text, same element JSON; the new keys are optional. The schema version does not change (`docs/SCHEMA.md` keeps v1); the spec's own v2.4 row is a separate matter.

### 6.2 Decisions taken (change freely)
- The author declares the book type (`--mode phonetic|meaning`, required; no `auto`). A mixed book gets `--ranges` (image ranges or sentence-id ranges). The file format is the tool's own input; the spec fixes none.
- `warn` carries `reviewed` (0 or 1; optional in the spec, absent means 0; key order is not significant; the tool always writes it). A names file gives `reviewed` 1 and yellow only when the Nom and Vietnamese character counts differ.
- A suggestion (`suggest`, `suggest_by` `fallback` or `similar`) is a working state: `apply` accepts it (into `Label.txt`, CSV, `Label_char.txt`, XLSX), `apply --reject-rest` makes it a red `error`, `check-diff --final` fails on a pending one. The DP is not changed by a suggestion.
- The text in CSV and XLSX must equal `Label.txt` (SYNC), per side. The only exception is a row of a lost page (image in `missing/ch` or `missing/vi`), whose side is one whole `warn`.
- `Label_char.txt`: one character per box, boxes sorted; `check-diff` verifies it (`LABELCHAR`, `SYNC_CHAR`) and `apply` refuses on a violation.
- Colours: Excel standard `FF0000`, `FFFF00`, `000000` written; `D32F2F` and `D99A00` also accepted when reading (last six hex digits).
- No row has an empty side. `--keep-orphans` is gone; `--allow-skip` is diagnosis only (`<book>_align_orphans.jsonl`).
- Short sentences are listed and kept (`merge: keep`); merging is manual (`--merges`) or opt-in (`--merge-short`). Line-end hyphens: `--hyphen word` with a review file and `--hyphen-keep`; no built-in word list.
- `ocr-validate` is the source of truth for submission rules; `validate.py` here stays for use while aligning.
- Parked, do not touch: merged rows (`merged_diff`; kinds 1-n, n-1, n-m keep their `null` behaviour) and the report metrics matrix.

### 6.3 Task status (update after every task; deliver the zip after every task)
- [x] Milestone 1: contract (key sets, optional `reviewed`, colour sets, `check_row`, schema docs)
- [x] Milestone 2: names rule fix, `--mode` required, `ranges.py`
- [x] Milestone 3: `check-diff` with SYNC, `SUGGEST_PENDING`, plain-text mode, `lint_label`; `render`
- [x] Milestone 4: suggestion pass (`suggest.py`, edit-distance fallback map, report counters)
- [x] Milestone 5: `apply` (`sync.py`), atomic writes, `--reject-rest`, `Label_char.txt` guard
- [x] Milestone 6: short sentences and merges, orphans removal, hyphen `word` with review file and inconsistency report
- [x] Milestone 7: docs, examples, notebook, version 0.2.0
- [x] SPECIFICATION, SCHEMA, USER_GUIDE, HANDOFF in the numbered pattern
- [ ] X-1 (other repo): mirror the contract in `ocr-validate` (colour sets, optional `reviewed`, order-free keys, no pending `suggest`, SYNC per side)
- [ ] Han-Nom font on `ch_txt` in the XLSX (`tableio.py`)

### 6.4 Open questions and known gaps
1. Should `run` call `ocr-validate` at its end, or stay separate?
2. The online lookup is still untested against the live site (section 3).
3. `examples/similar.csv` is a one-row illustrative sample (`母`), because the real `SinoNom_Similar_Dic_v2.csv` is not in the repo. Run with the real file before trusting the suggestion counts.
4. Parked items wait for the user: merged rows and the report metrics matrix.
