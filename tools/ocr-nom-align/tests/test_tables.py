from __future__ import annotations

import json
import sqlite3

import pytest

from ocr_nom_align import ReadingTable, RunConfig, TableError, load_env
from tests.helpers import READINGS


def make_sqlite(path):
    con = sqlite3.connect(path)
    con.execute(
        "CREATE TABLE reading_table (head TEXT, key TEXT, syllable TEXT, system TEXT, score REAL, n_src INT)"
    )
    con.executemany(
        "INSERT INTO reading_table VALUES (?, ?, ?, 'hv', 1.0, 1)",
        [
            ("天", "thien", "thiên"),
            ("天", "troi", "trời"),
            ("nhân văn", "nhan van", "nhân văn"),
            ("𠀧", "ba", "ba"),
        ],
    )
    con.commit()
    con.close()


def test_sqlite_keeps_characters_only(tmp_path):
    db = tmp_path / "lexicon.sqlite"
    make_sqlite(db)
    t = ReadingTable().load(db)
    assert t.readings("天") == {
        t.key("thiên"),
        t.key("trời"),
    }  # keys drop the five tone marks, not the horn
    assert t.known("𠀧")  # extension-plane character counts as one
    assert len(t) == 2  # the word head `nhân văn` is not a character


def test_sqlite_wrong_file(tmp_path):
    db = tmp_path / "x.sqlite"
    sqlite3.connect(db).close()
    with pytest.raises(TableError):
        ReadingTable().load(db)


def test_csv_and_folder(tmp_path):
    (tmp_path / "lab_dict.csv").write_text(
        "char,syllable,note\n主,chúa,hv:2\n主,chủ,hv:1\n", encoding="utf-8"
    )
    t = ReadingTable.from_paths([tmp_path])  # the folder is enough
    assert t.readings("主") == {t.key("chúa"), t.key("chủ")}
    assert t.sources == [str(tmp_path / "lab_dict.csv")]


def test_third_class_tables(tmp_path):
    (tmp_path / "t.json").write_text(
        json.dumps({"天": ["thiên", "trời"], "地": "địa"}), encoding="utf-8"
    )
    (tmp_path / "t.tsv").write_text("人\tnhân,nhơn\n", encoding="utf-8")
    (tmp_path / "t.csv").write_text("char,syllable\n主,chúa\n", encoding="utf-8")
    t = ReadingTable.from_paths([tmp_path / "t.json", tmp_path / "t.tsv", tmp_path / "t.csv"])
    assert t.readings("天") == {t.key("thiên"), t.key("trời")} and t.readings("地") == {
        t.key("địa")
    }
    assert t.readings("人") == {t.key("nhân"), t.key("nhơn")} and t.readings("主") == {
        t.key("chúa")
    }
    (tmp_path / "bad.json").write_text("[1]", encoding="utf-8")
    with pytest.raises(TableError, match="expected"):
        ReadingTable().load(tmp_path / "bad.json")
    with pytest.raises(TableError, match=r"entries/\*\.jsonl"):
        ReadingTable().load(tmp_path)  # a folder with none of the dictionary files


def test_empty_table_is_an_error(tmp_path):
    f = tmp_path / "e.csv"
    f.write_text("char,syllable\n", encoding="utf-8")
    with pytest.raises(TableError):
        ReadingTable.from_paths([f])


def test_tone_sensitive_keys():
    t = ReadingTable({"母": ["mẫu"]}, tone_sensitive=True)
    assert t.readings("母") == {"mẫu"}


def test_env_tables_and_env_file(tmp_path, monkeypatch):
    for k in ("NOM_ALIGN_TABLE", "NOM_ALIGN_OUT_DIR"):
        monkeypatch.delenv(k, raising=False)
    env = tmp_path / ".env"
    env.write_text(
        "export NOM_ALIGN_TABLE='a.csv:b.jsonl'  # two\nNOM_ALIGN_OUT_DIR=books\n",
        encoding="utf-8",
    )
    assert sorted(load_env(env)) == ["NOM_ALIGN_OUT_DIR", "NOM_ALIGN_TABLE"]
    run = RunConfig.from_env()
    assert run.tables == ("a.csv", "b.jsonl")
    assert run.paths("Book")["csv"].as_posix() == "books/Book.csv"
    assert run.paths("Book")["report"].name == "Book_align_report.json"


def test_real_environment_beats_env_file(tmp_path, monkeypatch):
    monkeypatch.setenv("NOM_ALIGN_OUT_DIR", "mine")
    env = tmp_path / ".env"
    env.write_text("NOM_ALIGN_OUT_DIR=theirs\n", encoding="utf-8")
    assert load_env(env) == []
    assert RunConfig.from_env().out_dir.as_posix() == "mine"


def test_helpers_table_loads():
    assert len(ReadingTable({c: {k} for c, k in READINGS.items()})) == len(READINGS)
