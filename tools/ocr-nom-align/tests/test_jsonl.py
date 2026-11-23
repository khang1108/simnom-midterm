"""The reading table read straight from dictionary entry files (`*.jsonl`)."""

from __future__ import annotations

import gzip
import json

import pytest
from click.testing import CliRunner

from ocr_nom_align import ReadingTable, TableError
from ocr_nom_align.cli import main
from tests.helpers import READINGS, write_label


def entry(id_, kind, head, script, readings=(), forms=(), **extra):
    e = {
        "id": id_,
        "source": id_.split(":")[0],
        "kind": kind,
        "head": head,
        "script": script,
        "readings": [{"value": v, "system": s} for v, s in readings],
        "forms": [{"text": t, "script": sc} for t, sc in forms],
        **extra,
    }
    return {k: v for k, v in e.items() if v not in ([], None)}


def write_entries(path, entries):
    path.write_text(
        "\n".join(json.dumps(e, ensure_ascii=False) for e in entries) + "\n", encoding="utf-8"
    )
    return path


ENTRIES = [
    entry("hv:1", "char", "天", "han", [("thiên", "hv"), ("tian1", "pinyin"), ("trời", "nom")]),
    entry("hv:2", "char", "主", "han", [("chủ", "hv"), ("chúa", "nom")]),
    entry("hv:3", "word", "天主", "han", [("thiên chúa", "hv")]),  # a word is not a character
    entry("hv:4", "char", "𠀧", "nom", [("ba", "nom")]),  # extension plane: one character
    entry("hv:5", "char", "⿰氵每", "nom", [("hải", "hv")], unencoded=True),  # no codepoint
    entry("hv:6", "char", "葉\ufe00", "han", [("diệp", "hv")]),  # variation selector is dropped
    entry("cc:1", "word", "地", "han", [("địa", "hv")]),  # a word with no char entry in its source
    entry("rcv:1", "word", "人", "han", [("nhân", "hv")]),
    entry("rcv:2", "char", "人", "han", [("nhơn", "hv")]),  # ... with one: both count
    entry("dn:1", "word", "Trời", "qn", forms=[("𡗶", "nom"), ("@img:x", "nom"), ("天上", "nom")]),  # noqa: E501
    entry("kr:1", "char", "天", "hangul", [("천", "hangul")]),  # another script: not Vietnamese
]


@pytest.fixture
def entries_dir(tmp_path):
    d = tmp_path / "lexicon" / "entries"
    d.mkdir(parents=True)
    for src in ("hv", "cc", "rcv", "dn", "kr"):
        write_entries(d / f"{src}.jsonl", [e for e in ENTRIES if e["source"] == src])
    (d / "manifest.jsonl").write_text('{"url": "x", "sha256": "y"}\n', encoding="utf-8")
    (d / "rejected").mkdir()
    write_entries(d / "rejected" / "hv.jsonl", [{"reason": "bad record"}])
    return d


def test_jsonl_file_keeps_vietnamese_readings_of_characters(tmp_path):
    t = ReadingTable().load(write_entries(tmp_path / "all.jsonl", ENTRIES))
    k = t.key
    assert t.readings("天") == {k("thiên"), k("trời")}  # pinyin and hangul are not readings here
    assert t.readings("主") == {k("chủ"), k("chúa")}
    assert t.known("𠀧") and t.readings("𠀧") == {k("ba")}
    assert t.readings("葉") == {k("diệp")}  # a variant glyph reads like its base character
    assert not t.known("地")  # a word whose source has no char entry for it
    assert t.readings("人") == {k("nhân"), k("nhơn")}
    assert t.readings("𡗶") == {k("trời")} and t.readings("天") >= {k("trời")}
    assert not t.known("⿰") and not t.known("每")  # unencoded: out
    assert "@" not in "".join("".join(t.readings(c)) for c in "天主𠀧")


def test_quoc_ngu_entry_gives_one_character_nom_forms_only(tmp_path):
    t = ReadingTable().load(write_entries(tmp_path / "dn.jsonl", ENTRIES[-2:-1]))
    assert set(t._map) == {"𡗶"}  # `天上` is two characters, `@img:` is an image


def test_folder_of_entries_or_its_parent(entries_dir):
    for p in (entries_dir, entries_dir.parent):
        t = ReadingTable().load(p)
        assert t.known("天") and t.known("人") and not t.known("地")
        names = sorted(s.rsplit("/", 1)[-1] for s in t.sources)
        assert names == [
            "cc.jsonl",
            "dn.jsonl",
            "hv.jsonl",
            "kr.jsonl",
            "rcv.jsonl",
        ]  # no manifest, no rejected/


def test_gzip_file(tmp_path):
    raw = "\n".join(json.dumps(e, ensure_ascii=False) for e in ENTRIES[:2]).encode("utf-8")
    with gzip.open(tmp_path / "hv.jsonl.gz", "wb") as f:
        f.write(raw)
    assert ReadingTable().load(tmp_path / "hv.jsonl.gz").known("天")


def test_jsonl_is_merged_with_other_sources(tmp_path, entries_dir):
    lab = tmp_path / "lab_dict.csv"
    lab.write_text("経,kinh,hv:1\n", encoding="utf-8")
    t = ReadingTable.from_paths([entries_dir, lab])
    assert t.known("経") and t.known("天")


@pytest.mark.parametrize(
    "content,message",
    [
        ('{"head": "天"}\nnot json\n', "x.jsonl:2: bad JSON"),
        ('{"url": "http://a", "sha256": "b"}\n', "x.jsonl:1: not a dictionary entry"),
        ('["天"]\n', "x.jsonl:1: not a dictionary entry"),
    ],
)
def test_jsonl_errors_name_the_line(tmp_path, content, message):
    p = tmp_path / "x.jsonl"
    p.write_text(content, encoding="utf-8")
    with pytest.raises(TableError, match=message):
        ReadingTable().load(p)


def test_folder_without_any_source(tmp_path):
    (tmp_path / "empty").mkdir()
    with pytest.raises(TableError, match=r"entries/\*\.jsonl"):
        ReadingTable().load(tmp_path / "empty")


def test_cli_readings_and_run_with_an_entries_folder(tmp_path, entries_dir):
    r = CliRunner().invoke(main, ["readings", "天人", "--table", str(entries_dir)])
    assert r.exit_code == 0, r.output
    assert "thiên" in r.output and "nhơn" in r.output

    d = tmp_path / "lex"
    d.mkdir()
    write_entries(
        d / "hv.jsonl",
        [
            entry(f"hv:{i}", "char", c, "han", [(s, "hv")])
            for i, (c, s) in enumerate(READINGS.items())
        ],
    )
    ch = write_label(tmp_path / "ch.txt", {"B.001.jpg": ["経告命命命。", "天主造天地。"]}, "ch")
    vi = write_label(
        tmp_path / "vi.txt", {"B.001.jpg": ["Kinh Cáo Mệnh.", "Thiên Chúa tạo thiên địa."]}, "vi"
    )
    out = tmp_path / "out"
    args = ["--ch", str(ch), "--vi", str(vi), "--book", "B", "--out-dir", str(out)]
    r = CliRunner().invoke(
        main, ["run", "--mode", "phonetic", *args], env={"NOM_ALIGN_TABLE": str(d)}
    )  # the environment names the folder
    assert r.exit_code == 0, r.output
    report = json.loads((out / "B_align_report.json").read_text(encoding="utf-8"))
    assert report["unknown_chars"] == {} and report["reading_sources"] == [str(d / "hv.jsonl")]
    check = ["check", str(out / "B.csv"), "--xlsx", str(out / "B.xlsx")]
    assert CliRunner().invoke(main, check).exit_code == 0
