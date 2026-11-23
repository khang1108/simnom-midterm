"""`ocr-nom-align run | diff | render | check | check-diff | apply | score | demo | readings`. Exit codes: `0` ok, `1` an error or a failed check."""

from __future__ import annotations

import json
from collections.abc import Iterable
from pathlib import Path

import click

from .align import AlignFailed, align_book
from .config import NomAlignConfig, RunConfig, load_env, read_names
from .diff import text_diff
from .online import OnlineLookup
from .pages import lint_label, pair_pages, read_image_map, read_label_file
from .ranges import RangeError, Ranges
from .readings import ReadingTable, TableError
from .report import build_report
from .rows import fill_text_diff, keep_reviewed, read_pairs
from .suggest import SimilarTable, Suggester
from .sync import ApplyError, apply_suggestions
from .tableio import read_csv, render_xlsx, write_csv, write_xlsx
from .tokens import nfc
from .validate import check_csv, check_xlsx, similarity
from .validate import check_diff as run_check_diff


def table_options(f):
    """`--table` (repeatable; with none, NOM_ALIGN_TABLE decides) and `--offline`."""
    f = click.option(
        "--offline",
        is_flag=True,
        envvar="NOM_ALIGN_OFFLINE",
        help="Do not look unknown characters up online (also: NOM_ALIGN_OFFLINE=1).",
    )(f)
    return click.option(
        "--table",
        "tables",
        multiple=True,
        type=click.Path(),
        help="Reading table source, repeatable: entries .jsonl (or the folder of them), lab_dict.csv, "
        "lexicon.sqlite, or any .csv / .tsv / .json. Default: NOM_ALIGN_TABLE (':'-separated).",
    )(f)


def cfg_options(f):
    for opt in reversed(
        (
            click.option(
                "--mode",
                type=click.Choice(["phonetic", "meaning"]),
                default=None,
                help="The book type, declared by the author (required for run / diff): phonetic: diff every "
                "1-1 row; meaning: never (all null). A mixed book uses --ranges.",
            ),
            click.option(
                "--tone-sensitive", is_flag=True, help="A tone-only difference is an error."
            ),
            click.option(
                "--unknown",
                "unknown_policy",
                type=click.Choice(["error", "match"]),
                default="error",
                show_default=True,
                help="A character in no table: red (default) or treated as equal while the table is thin.",
            ),
            click.option(
                "--warn-names", is_flag=True, help="Yellow for capitalised names of unequal length."
            ),
            click.option(
                "--names",
                "names_file",
                type=click.Path(dir_okay=False),
                help="One proper name per line; a run that reads as one is yellow.",
            ),
            click.option(
                "--phonetic-min-match",
                type=float,
                default=0.6,
                show_default=True,
                help="[tune] rows below this share are only listed in the report (low_match_rows).",
            ),
        )
    ):
        f = opt(f)
    return f


def colour_options(f):
    for name, default in (("black", "000000"), ("warn", "FFFF00"), ("error", "FF0000")):
        f = click.option(
            f"--{name}-color",
            f"{name}_color",
            default=None,
            help=f"{name} text colour (accepted set only; default {default}).",
        )(f)
    return f


def make_cfg(**kw) -> NomAlignConfig:
    names_file = kw.pop("names_file", None)
    if names_file:
        kw["names"] = read_names(names_file)
    return NomAlignConfig(**{k: v for k, v in kw.items() if v is not None})


def resolve_table(
    run: RunConfig, tables, tone_sensitive: bool, *, offline: bool = True, texts: Iterable[str] = ()
) -> tuple[ReadingTable, dict | None]:
    """The table, and unless `offline`, the characters of `texts` that it lacks looked up online (the report of that)."""
    table = ReadingTable.from_paths(tables or run.tables, tone_sensitive=tone_sensitive)
    if offline:
        return table, None
    lookup = OnlineLookup(run.cache, contact=run.contact)
    rep = lookup.resolve(table, "".join(texts))
    if rep["failed"] or rep.get("stopped"):
        click.echo(
            f"online lookup: {len(rep['failed'])} characters could not be asked "
            f"({rep.get('stopped') or 'network error'}); they stay unknown",
            err=True,
        )
    return table, rep


def _echo_summary(stats: dict, extra: str = "") -> None:
    sim = stats["similarity"]
    click.echo(
        f"rows={stats['rows']} phonetic={stats['phonetic_rows']} null={stats['null_rows']} "
        f"similarity={'n/a' if sim is None else f'{sim:.2f}%'} yellow_rate={stats['yellow_rate']:.3f}"
        + (f" {extra}" if extra else "")
    )


@click.group()
@click.option(
    "--env-file",
    type=click.Path(dir_okay=False),
    default=None,
    help="KEY=VALUE file read before the options (default: $NOM_ALIGN_ENV_FILE or ./.env). Real environment "
    "variables win. Keys: NOM_ALIGN_TABLE, NOM_ALIGN_OUT_DIR.",
)
def main(env_file) -> None:
    """Align Sino-Nom sentences with Vietnamese sentences and write the book CSV / XLSX."""
    load_env(env_file)


def _need_mode(mode):
    if mode is None:
        raise click.ClickException(
            "--mode is required: phonetic or meaning (declare the book type; use --ranges for a mixed book)"
        )


def _suggester(table: ReadingTable, similar: str | None, env: RunConfig):
    path = similar or env.similar
    sim = SimilarTable.load(path) if path else SimilarTable()
    return Suggester(table, sim), sim


def _read_list(path) -> frozenset[str]:
    if not path:
        return frozenset()
    lines = (ln.strip() for ln in Path(path).read_text(encoding="utf-8-sig").splitlines())
    return frozenset(ln for ln in lines if ln and not ln.startswith("#"))


def _read_merges(path) -> list[dict] | None:
    if not path:
        return None
    out = []
    for n, line in enumerate(Path(path).read_text(encoding="utf-8-sig").splitlines(), 1):
        if not line.strip():
            continue
        try:
            rec = json.loads(line)
        except json.JSONDecodeError as exc:
            raise ValueError(f"{path}:{n}: bad JSON ({exc})") from None
        if not isinstance(rec, dict) or rec.get("merge", "keep") not in ("keep", "prev", "next"):
            raise ValueError(f"{path}:{n}: merge must be keep, prev or next")
        out.append(rec)
    return out


def _names_in(folder) -> frozenset[str]:
    """Image names inside a folder (`missing/ch`, `missing/vi`): their rows are predicted on that side."""
    if not folder:
        return frozenset()
    return frozenset(p.name for p in Path(folder).iterdir() if p.is_file())


@main.command()
@click.option(
    "--ch",
    "ch_label",
    required=True,
    type=click.Path(exists=True, dir_okay=False),
    help="ch/Label.txt",
)
@click.option(
    "--vi",
    "vi_label",
    required=True,
    type=click.Path(exists=True, dir_okay=False),
    help="vi/Label.txt",
)
@click.option("--ch-fallback", type=click.Path(exists=True, dir_okay=False),
              help="Label.txt of a second Nom OCR: its characters become suggestions (yellow) where they fit.")  # fmt: skip
@click.option("--fallback-max-dist", type=float, default=0.5, show_default=True,
              help="Skip an image whose two Nom texts differ by more than this share.")  # fmt: skip
@click.option(
    "--similar",
    type=click.Path(dir_okay=False),
    help="SinoNom_Similar_Dic CSV (also: NOM_ALIGN_SIMILAR).",
)
@click.option("--ranges", type=click.Path(exists=True, dir_okay=False), help="JSON: rows that are translations by meaning.")  # fmt: skip
@click.option(
    "--image-map", type=click.Path(exists=True, dir_okay=False), help="<book>_image_map.json"
)
@click.option(
    "--book",
    required=True,
    help="Book name: files are <out-dir>/<book>.csv, .xlsx, _align_report.json.",
)
@click.option(
    "--out-dir",
    envvar="NOM_ALIGN_OUT_DIR",
    default="out",
    show_default=True,
    type=click.Path(file_okay=False),
)
@click.option("--xlsx/--no-xlsx", default=True, show_default=True, help="Also write <book>.xlsx.")
@click.option("--detail", is_flag=True, help="Also write <book>_align_detail.jsonl.")
@click.option("--nom-order", type=click.Choice(["asc", "desc"]), default="asc", show_default=True,
              help="Page order without an image map; desc for T1 (Nom read from the end).")  # fmt: skip
@click.option(
    "--hyphen", type=click.Choice(["word", "space", "keep"]), default="word", show_default=True
)
@click.option("--hyphen-keep", type=click.Path(exists=True, dir_okay=False),
              help="Words (one per line, hyphens included) that keep their hyphen; their records are reviewed.")  # fmt: skip
@click.option("--strip-notes/--no-strip-notes", default=False, show_default=True,
              help="Remove [1] / (1) note marks from the Vietnamese text (off: the text must match Label.txt).")  # fmt: skip
@click.option("--merges", type=click.Path(exists=True, dir_okay=False),
              help="<book>_short_sentences.jsonl with merge set to prev or next on the lines to join.")  # fmt: skip
@click.option(
    "--short-warn",
    type=int,
    default=5,
    show_default=True,
    help="List sentences below N tokens (0: off).",
)
@click.option(
    "--merge-short",
    type=int,
    default=0,
    show_default=True,
    help="Merge sentences below N tokens (0: never).",
)
@click.option(
    "--allow-skip",
    is_flag=True,
    help="Diagnosis: let the DP leave sentences unpaired (listed, never rows).",
)
@click.option("--cost-mode", type=click.Choice(["lev", "length"]), default="lev", show_default=True,
              help="length: length ratio only, for translations.")  # fmt: skip
@click.option(
    "--band",
    type=int,
    default=0,
    show_default=True,
    help="DP half-width in sentences (0: from the book).",
)
@table_options
@cfg_options
@colour_options
def run(**o):  # fmt: skip
    """Align a book from its two Label.txt files and write <book>.csv (+ .xlsx, report)."""
    _need_mode(o["mode"])
    env = RunConfig.from_env(out_dir=o["out_dir"])
    try:
        cfg = make_cfg(mode=o["mode"], nom_order=o["nom_order"], hyphen=o["hyphen"],
                       tone_sensitive=o["tone_sensitive"], allow_skip=o["allow_skip"],
                       warn_names=o["warn_names"], unknown_policy=o["unknown_policy"],
                       cost_mode=o["cost_mode"], band=o["band"], names_file=o["names_file"],
                       phonetic_min_match=o["phonetic_min_match"], strip_notes=o["strip_notes"],
                       short_warn=o["short_warn"], merge_short=o["merge_short"],
                       fallback_max_dist=o["fallback_max_dist"], error_color=o["error_color"],
                       warn_color=o["warn_color"], black_color=o["black_color"])  # fmt: skip
        ch_lf, vi_lf = read_label_file(o["ch_label"]), read_label_file(o["vi_label"])
        ch, vi = ch_lf.pages(), vi_lf.pages()
        fb = read_label_file(o["ch_fallback"]).pages() if o["ch_fallback"] else None
        merges = _read_merges(o["merges"])
        table, online = resolve_table(
            env, o["tables"], o["tone_sensitive"], offline=o["offline"],
            texts=(t for v in ch.values() for t in v),
        )  # fmt: skip
        suggester, sim = _suggester(table, o["similar"], env)
        ranges = Ranges.load(o["ranges"]) if o["ranges"] else None
        pairs = (
            read_image_map(o["image_map"])
            if o["image_map"]
            else pair_pages(list(ch), list(vi), order=o["nom_order"])
        )
        manual = _read_list(o["hyphen_keep"])
        records: list[dict] = []
        res = align_book(ch, vi, table, cfg, pairs, ranges, suggester, fb, manual, records, merges)
    except (TableError, AlignFailed, ValueError, RangeError) as exc:
        raise click.ClickException(str(exc)) from None
    out = env.paths(o["book"])
    out["csv"].parent.mkdir(parents=True, exist_ok=True)
    write_csv(res.rows, out["csv"])
    if o["xlsx"]:
        write_xlsx(res.rows, out["xlsx"], cfg)
    stats = similarity(read_csv(out["csv"]))
    short = [{"side": side, "img_id": s.img, "sentence_id": s.sid if side == "nom" else f"{s.img}#{s.n}",
              "text": s.text, "tokens": len(s.toks), "merge": "keep"} for side, s in res.short]  # fmt: skip
    if short:
        out["short"].write_text(
            "".join(json.dumps(x, ensure_ascii=False) + "\n" for x in short), encoding="utf-8"
        )
    if records:
        out["hyphens"].write_text(
            "".join(json.dumps(x, ensure_ascii=False) + "\n" for x in records), encoding="utf-8"
        )
    if res.orphans_nom or res.orphans_vi:
        orph = [
            {"side": "nom", "img_id": s.img, "sentence_id": s.sid, "text": s.text}
            for s in res.orphans_nom
        ]
        orph += [
            {"side": "vi", "img_id": s.img, "sentence_id": f"{s.img}#{s.n}", "text": s.text}
            for s in res.orphans_vi
        ]
        out["orphans"].write_text(
            "".join(json.dumps(x, ensure_ascii=False) + "\n" for x in orph), encoding="utf-8"
        )
    lint = {
        side: {k: len(v) for k, v in lint_label(lf).items()}
        for side, lf in (("ch", ch_lf), ("vi", vi_lf))
    }
    base = {**res.report, "similar_parse_errors": sim.parse_errors, "label_lint": lint,
            "meaning_ranges": ranges.meaning if ranges else [],
            "short_sentences": {"count": len(short), "file": str(out["short"]) if short else None},
            "hyphen_review": {"count": sum(1 for r in records if not r["reviewed"]),
                              "file": str(out["hyphens"]) if records else None}}  # fmt: skip
    report = build_report(
        res.rows, stats, cfg, base,
        orphans_nom=[s.sid for s in res.orphans_nom],
        orphans_vi=[f"{s.img}#{s.n}" for s in res.orphans_vi],
        reading_sources=table.sources,
        online=online,
    )  # fmt: skip
    out["report"].write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    if o["detail"]:
        with out["detail"].open("w", encoding="utf-8") as f:
            for r in res.rows:
                rec = {"img_id": r.img_id, "sentence_id": r.sentence_id, "kind": r.kind,
                       "vi_img": r.vi_img, "phonetic": r.phonetic}  # fmt: skip
                f.write(json.dumps(rec, ensure_ascii=False) + "\n")
    _echo_summary(stats, f"-> {out['csv']}")


@main.command()
@click.argument("pairs", type=click.Path(exists=True, dir_okay=False))
@click.option(
    "--out", "out_csv", required=True, type=click.Path(dir_okay=False), help="Book CSV to write."
)
@click.option(
    "--xlsx", "out_xlsx", type=click.Path(dir_okay=False), help="Also write the coloured XLSX."
)
@click.option("--report", "out_report", type=click.Path(dir_okay=False), help="Report JSON.")
@click.option(
    "--ranges",
    type=click.Path(exists=True, dir_okay=False),
    help="JSON: rows that are translations by meaning.",
)
@click.option(
    "--similar",
    type=click.Path(dir_okay=False),
    help="SinoNom_Similar_Dic CSV (also: NOM_ALIGN_SIMILAR).",
)
@click.option("--keep-reviewed", type=click.Path(exists=True, dir_okay=False),
              help="An earlier CSV: copy `reviewed` to every equal warn element.")  # fmt: skip
@table_options
@cfg_options
@colour_options
def diff(**o):  # fmt: skip
    """Fill text_diff of rows that are already paired (CSV or JSONL: img_id, sentence_id, ch_txt, vi_txt[, kind])."""
    _need_mode(o["mode"])
    env = RunConfig.from_env()
    try:
        cfg = make_cfg(mode=o["mode"], tone_sensitive=o["tone_sensitive"], warn_names=o["warn_names"],
                       unknown_policy=o["unknown_policy"], names_file=o["names_file"],
                       phonetic_min_match=o["phonetic_min_match"], error_color=o["error_color"],
                       warn_color=o["warn_color"], black_color=o["black_color"])  # fmt: skip
        pair_rows = read_pairs(o["pairs"])
        table, online = resolve_table(
            env, o["tables"], o["tone_sensitive"], offline=o["offline"],
            texts=(p.ch_txt for p in pair_rows),
        )  # fmt: skip
        suggester, sim = _suggester(table, o["similar"], env)
        ranges = Ranges.load(o["ranges"]) if o["ranges"] else None
        rows, base = fill_text_diff(pair_rows, table, cfg, ranges, suggester)
        base["similar_parse_errors"] = sim.parse_errors
        if o["keep_reviewed"]:
            base["reviewed_kept"] = keep_reviewed(rows, o["keep_reviewed"])
    except (TableError, ValueError, RangeError) as exc:
        raise click.ClickException(str(exc)) from None
    Path(o["out_csv"]).parent.mkdir(parents=True, exist_ok=True)
    write_csv(rows, o["out_csv"])
    if o["out_xlsx"]:
        write_xlsx(rows, o["out_xlsx"], cfg)
    stats = similarity(read_csv(o["out_csv"]))
    if o["out_report"]:
        report = build_report(rows, stats, cfg, base, reading_sources=table.sources, online=online)
        Path(o["out_report"]).write_text(
            json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8"
        )
    _echo_summary(stats)


@main.command()
@click.argument("csv_path", type=click.Path(exists=True, dir_okay=False))
@click.option("--xlsx", "xlsx_path", required=True, type=click.Path(dir_okay=False))
@colour_options
def render(csv_path, xlsx_path, error_color, warn_color, black_color):
    """Write the XLSX of a (hand-fixed) CSV from its stored text_diff. Never recomputes the diff."""
    try:
        cfg = make_cfg(error_color=error_color, warn_color=warn_color, black_color=black_color)
        render_xlsx(csv_path, xlsx_path, cfg)
    except ValueError as exc:
        raise click.ClickException(str(exc)) from None
    click.echo(f"wrote {xlsx_path}")


@main.command("check-diff")
@click.argument("csv_path", type=click.Path(exists=True, dir_okay=False))
@click.option(
    "--xlsx", "xlsx_path", type=click.Path(exists=True, dir_okay=False), help="Also check the XLSX."
)
@click.option(
    "--ch",
    "ch_label",
    type=click.Path(exists=True, dir_okay=False),
    help="ch/Label.txt (Nom side SYNC).",
)
@click.option(
    "--vi",
    "vi_label",
    type=click.Path(exists=True, dir_okay=False),
    help="vi/Label.txt (Vietnamese side SYNC).",
)
@click.option(
    "--ch-char",
    type=click.Path(exists=True, dir_okay=False),
    help="ch/Label_char.txt (one character per box).",
)
@click.option(
    "--image-map", type=click.Path(exists=True, dir_okay=False), help="<book>_image_map.json"
)
@click.option("--nom-order", type=click.Choice(["asc", "desc"]), default="asc", show_default=True)
@click.option("--missing-ch", type=click.Path(exists=True, file_okay=False), help="Folder of lost Nom pages (rows are predicted on the Nom side).")  # fmt: skip
@click.option(
    "--missing-vi",
    type=click.Path(exists=True, file_okay=False),
    help="Folder of lost Vietnamese pages.",
)
@click.option("--strict", is_flag=True, help="Warnings fail too.")
@click.option("--final", is_flag=True, help="Submission gate: a pending suggestion is an error.")
@click.option("--sync-loose/--sync-exact", default=True, show_default=True,
              help="Loose (the spec rule); exact also lists the exact join_vi difference as a warning.")  # fmt: skip
@colour_options
def check_diff_cmd(csv_path, xlsx_path, ch_label, vi_label, ch_char, image_map, nom_order, missing_ch,
                   missing_vi, strict, final, sync_loose, error_color, warn_color, black_color):  # fmt: skip
    """Check text_diff against the cells and the files (Label.txt, Label_char.txt, XLSX). Exit 1 on any error."""
    try:
        cfg = make_cfg(error_color=error_color, warn_color=warn_color, black_color=black_color)
        pairs = read_image_map(image_map) if image_map else None
        res = run_check_diff(
            csv_path, xlsx=xlsx_path, ch_label=ch_label, vi_label=vi_label, ch_char=ch_char, pairs=pairs,
            nom_order=nom_order, missing_ch=_names_in(missing_ch), missing_vi=_names_in(missing_vi),
            strict=strict, final=final, sync_exact=not sync_loose, cfg=cfg,
        )  # fmt: skip
    except (ValueError, OSError) as exc:
        raise click.ClickException(str(exc)) from None
    errors = 0
    for level, line in res[:500]:
        click.echo(line + ("  [warning]" if level == "warning" else ""))
    errors = sum(1 for lvl, _ in res if lvl == "error")
    if errors:
        raise click.ClickException(f"{errors} error(s)")
    click.echo("ok")


@main.command()
@click.argument("csv_path", type=click.Path(exists=True, dir_okay=False))
@click.option(
    "--ch",
    "ch_label",
    required=True,
    type=click.Path(exists=True, dir_okay=False),
    help="ch/Label.txt",
)
@click.option(
    "--vi",
    "vi_label",
    required=True,
    type=click.Path(exists=True, dir_okay=False),
    help="vi/Label.txt",
)
@click.option(
    "--ch-char",
    type=click.Path(exists=True, dir_okay=False),
    help="ch/Label_char.txt: updated too.",
)
@click.option(
    "--xlsx", "xlsx_path", type=click.Path(dir_okay=False), help="XLSX to rebuild from the new CSV."
)
@click.option(
    "--image-map", type=click.Path(exists=True, dir_okay=False), help="<book>_image_map.json"
)
@click.option("--nom-order", type=click.Choice(["asc", "desc"]), default="asc", show_default=True)
@click.option(
    "--missing-ch", type=click.Path(exists=True, file_okay=False), help="Folder of lost Nom pages."
)
@click.option(
    "--missing-vi",
    type=click.Path(exists=True, file_okay=False),
    help="Folder of lost Vietnamese pages.",
)
@click.option("--accept", type=click.Choice(["reviewed", "all"]), default="reviewed", show_default=True,
              help="Which pending suggestions are written into Label.txt.")  # fmt: skip
@click.option(
    "--reject-rest", is_flag=True, help="Every suggestion not accepted becomes an error (red)."
)
@click.option("--out-dir", type=click.Path(file_okay=False), help="Write the changed files here.")
@click.option("--in-place", is_flag=True, help="Overwrite the files (each keeps a .bak).")
@colour_options
def apply(csv_path, ch_label, vi_label, ch_char, xlsx_path, image_map, nom_order, missing_ch, missing_vi,
          accept, reject_rest, out_dir, in_place, error_color, warn_color, black_color):  # fmt: skip
    """Write accepted suggestions into Label.txt, the CSV, Label_char.txt and the XLSX, all in sync."""
    try:
        cfg = make_cfg(error_color=error_color, warn_color=warn_color, black_color=black_color)
        pairs = read_image_map(image_map) if image_map else None
        res = apply_suggestions(
            csv_path, ch_label, vi_label, ch_char=ch_char, xlsx=xlsx_path, pairs=pairs, accept=accept,
            reject_rest=reject_rest, out_dir=out_dir, in_place=in_place, nom_order=nom_order,
            missing_ch=_names_in(missing_ch), missing_vi=_names_in(missing_vi), cfg=cfg,
        )  # fmt: skip
    except (ApplyError, ValueError, OSError) as exc:
        raise click.ClickException(str(exc)) from None
    click.echo(f"applied={res['applied']} rejected={res['rejected']} skipped={res['skipped']}")


@main.command()
@click.argument("csv_path", type=click.Path(exists=True, dir_okay=False))
@click.option("--xlsx", "xlsx_path", type=click.Path(exists=True, dir_okay=False))
def check(csv_path, xlsx_path):
    """Validate the CSV (and that the XLSX colours match its text_diff). Exit 1 on any problem."""
    errs = check_csv(csv_path) + (check_xlsx(csv_path, xlsx_path) if xlsx_path else [])
    for e in errs[:200]:
        click.echo(e)
    if errs:
        raise click.ClickException(f"{len(errs)} problem(s)")
    click.echo("ok")


@main.command()
@click.argument("csv_path", type=click.Path(exists=True, dir_okay=False))
@click.option(
    "--min",
    "minimum",
    type=float,
    default=None,
    help="Exit 1 when the similarity is below this (%).",
)
def score(csv_path, minimum):
    """Similarity (%) and the null / yellow rates of a finished CSV."""
    stats = similarity(read_csv(csv_path))
    click.echo(json.dumps(stats, ensure_ascii=False, indent=2))
    sim = stats["similarity"]
    if minimum is not None and (sim is None or sim < minimum):
        raise click.ClickException(
            f"similarity {'n/a' if sim is None else f'{sim:.2f}'} < {minimum}"
        )


@main.command()
@click.argument("ch")
@click.argument("vi")
@table_options
@cfg_options
def demo(ch, vi, tables, offline, mode, tone_sensitive, unknown_policy, warn_names, names_file,
         phonetic_min_match):  # fmt: skip
    """Print the text_diff of one Nom cell against one Vietnamese cell."""
    try:
        cfg = make_cfg(mode=mode, tone_sensitive=tone_sensitive, warn_names=warn_names,
                       unknown_policy=unknown_policy, names_file=names_file,
                       phonetic_min_match=phonetic_min_match)  # fmt: skip
        table, _ = resolve_table(
            RunConfig.from_env(), tables, tone_sensitive, offline=offline, texts=[ch]
        )
    except (TableError, ValueError) as exc:
        raise click.ClickException(str(exc)) from None
    res = text_diff(nfc(ch), nfc(vi), table, cfg)
    click.echo(json.dumps(res.elements, ensure_ascii=False, indent=2))
    click.echo(f"match_ratio={res.match_ratio:.2f} unknown={''.join(res.unknown)}")


@main.command()
@click.argument("chars", nargs=-1, required=True)
@table_options
def readings(chars, tables, offline):
    """Show the readings of characters in the reading table (and which sources were read)."""
    try:
        table, _ = resolve_table(RunConfig.from_env(), tables, False, offline=offline, texts=chars)
    except TableError as exc:
        raise click.ClickException(str(exc)) from None
    click.echo(f"{len(table)} characters from {', '.join(table.sources)}")
    for c in "".join(chars):
        if not c.isspace():
            rs = sorted(table.readings(c))
            click.echo(f"{c}\t{', '.join(rs) if rs else '(not in the table)'}")


if __name__ == "__main__":
    main()
