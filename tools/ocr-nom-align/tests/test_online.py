"""Characters that the table lacks are looked up online once, kept in a cache, and never stop a run."""

from __future__ import annotations

import json

import pytest
from click.testing import CliRunner

from ocr_nom_align import ReadingTable
from ocr_nom_align import online as online_mod
from ocr_nom_align.cli import main
from ocr_nom_align.online import OnlineError, OnlineLookup, RefusedError, parse_char_page
from tests.helpers import READINGS, write_label


def block(ch, hv=(), nom=(), kind="han"):
    links = lambda path, rs: "".join(f'<a href="/{path}/{r}">{r}</a> ' for r in rs)  # noqa: E731
    return (
        f'<div class="hvres {kind}-word"><div class="hvres-word {kind}"><a href="/whv/{ch}">{ch}</a></div>'
        f'<div class="hvres-meaning">Âm Hán Việt: {links("hv", hv)}<br>Âm Nôm: {links("nom", nom)}<br>'
        f"Tổng nét: 4</div></div>"
    )


def page(*blocks):
    return "<html><body>" + "".join(blocks) + "</body></html>"


PAGES = {
    "天": page(block("天", hv=["thiên"], nom=["trời"])),
    "経": page(block("経", hv=["kinh"])),
}


class Fake:
    """A stand-in for the web: `PAGES` by character, and a log of what was asked."""

    def __init__(self, pages=None):
        self.pages, self.asked = dict(PAGES if pages is None else pages), []

    def __call__(self, url):
        kind, _, key = url.removeprefix(online_mod.BASE + "/").partition("/")
        from urllib.parse import unquote

        self.asked.append((kind, unquote(key)))
        if kind == "wnom":
            return ""
        return self.pages.get(unquote(key), "")


def lookup(tmp_path, fake, **kw):
    return OnlineLookup(tmp_path / "cache.json", pause=0, get=fake, **kw)


def test_parse_keeps_only_the_character_asked_for():
    html = page(block("天", hv=["thiên"], nom=["trời", "giời"]), block("夭", hv=["yểu"]))
    assert parse_char_page(html, "天") == ["thiên", "trời", "giời"]
    assert parse_char_page(html, "夭") == ["yểu"]
    assert parse_char_page(html, "地") == []
    assert parse_char_page("", "天") == []


def test_unknown_characters_are_asked_and_added(tmp_path):
    table, fake = ReadingTable({"主": ["chúa"]}), Fake()
    rep = lookup(tmp_path, fake).resolve(table, "天主経。abc〓")
    assert table.readings("天") == {table.key("thiên"), table.key("trời")}
    assert table.known("経") and table.readings("主") == {
        table.key("chúa")
    }  # a known one is not asked
    assert [c for _, c in fake.asked if _ == "whv"] == ["天", "経"]  # no punctuation, letters or 〓
    assert rep["found"] == 2 and rep["asked"] == 2 and not rep["failed"] and rep["not_found"] == []
    assert any(s.startswith("online:") for s in table.sources)


def test_answers_are_cached_even_the_empty_ones(tmp_path):
    fake = Fake()
    lookup(tmp_path, fake).resolve(ReadingTable(), "天地")  # 地: the site has no page
    assert json.loads((tmp_path / "cache.json").read_text(encoding="utf-8")) == {
        "天": ["thiên", "trời"],
        "地": [],
    }
    fake2, table = Fake(), ReadingTable()
    rep = lookup(tmp_path, fake2).resolve(table, "天地")  # a second run asks nothing
    assert (
        fake2.asked == []
        and rep["cached"] == 2
        and rep["found"] == 1
        and rep["not_found"] == ["地"]
    )
    assert table.known("天") and not table.known("地")


def test_a_not_found_character_tries_the_nom_page_too(tmp_path):
    fake = Fake()
    lookup(tmp_path, fake).resolve(ReadingTable(), "地")
    assert fake.asked == [("whv", "地"), ("wnom", "地")]


def test_block_page_stops_the_lookups_and_caches_nothing(tmp_path):
    def refuse(url):
        raise RefusedError("block page")

    look = lookup(tmp_path, refuse)
    table = ReadingTable()
    rep = look.resolve(table, "天経地")
    assert (
        rep["found"] == 0
        and rep["stopped"] == "block page"
        and rep["skipped"] == 2
        and rep["failed"] == ["地"]
    )  # the first in code order
    assert not (tmp_path / "cache.json").exists()  # nothing was learned
    assert len(table) == 0  # the run goes on with these characters unknown


def test_network_errors_stop_after_three_in_a_row(tmp_path):
    calls = []

    def down(url):
        calls.append(url)
        raise OnlineError("no network")

    rep = lookup(tmp_path, down).resolve(ReadingTable(), "天経地人之")
    assert (
        len(calls) == 3
        and rep["stopped"].startswith("3 requests failed")
        and len(rep["failed"]) == 3
    )
    assert rep["skipped"] == 2


def test_a_success_resets_the_failure_count(tmp_path):
    state = {"n": 0}

    def flaky(url):
        state["n"] += 1
        if state["n"] in (1, 3):
            raise OnlineError("blip")
        return PAGES["天"]

    rep = lookup(tmp_path, flaky).resolve(ReadingTable(), "天経人")
    assert "stopped" not in rep and len(rep["failed"]) == 2


def test_max_lookups_caps_the_requests(tmp_path):
    fake = Fake({c: PAGES["天"].replace("天", c) for c in "天経地"})
    rep = lookup(tmp_path, fake, max_lookups=2).resolve(ReadingTable(), "天経地")
    assert rep["asked"] == 2 and rep["skipped"] == 1


def test_damaged_cache_is_rebuilt(tmp_path):
    (tmp_path / "cache.json").write_text("{not json", encoding="utf-8")
    table = ReadingTable()
    lookup(tmp_path, Fake()).resolve(table, "天")
    assert table.known("天")


@pytest.fixture
def web(monkeypatch, tmp_path):
    fake = Fake()
    monkeypatch.setattr(online_mod, "http_get", lambda url, **kw: fake(url))
    monkeypatch.setattr(online_mod.time, "sleep", lambda s: None)
    return fake, {"NOM_ALIGN_OFFLINE": "0", "NOM_ALIGN_CACHE": str(tmp_path / "c.json")}


def test_cli_readings_looks_up_what_the_table_lacks(tmp_path, web):
    fake, env = web
    t = tmp_path / "t.json"
    t.write_text(json.dumps({"主": ["chúa"]}), encoding="utf-8")
    r = CliRunner().invoke(main, ["readings", "主天", "--table", str(t)], env=env)
    assert r.exit_code == 0, r.output
    assert "thiên" in r.output and "chua" in r.output and fake.asked[0] == ("whv", "天")


def test_cli_offline_asks_nothing(tmp_path, web):
    fake, env = web
    t = tmp_path / "t.json"
    t.write_text(json.dumps({"主": ["chúa"]}), encoding="utf-8")
    r = CliRunner().invoke(main, ["readings", "天", "--table", str(t), "--offline"], env=env)
    assert r.exit_code == 0 and "(not in the table)" in r.output and fake.asked == []
    r = CliRunner().invoke(
        main, ["readings", "天", "--table", str(t)], env={**env, "NOM_ALIGN_OFFLINE": "1"}
    )
    assert "(not in the table)" in r.output and fake.asked == []


def test_cli_run_fills_the_gap_and_reports_it(tmp_path, web):
    fake, env = web
    table = {c: [s] for c, s in READINGS.items() if c != "経"}  # 経 is missing from the table
    t = tmp_path / "t.json"
    t.write_text(json.dumps(table, ensure_ascii=False), encoding="utf-8")
    ch = write_label(tmp_path / "ch.txt", {"B.001.jpg": ["経告命命命。"]}, "ch")
    vi = write_label(tmp_path / "vi.txt", {"B.001.jpg": ["Kinh Cáo Mệnh."]}, "vi")
    out = tmp_path / "out"
    r = CliRunner().invoke(
        main,
        [
            "run",
            "--mode",
            "phonetic",
            "--ch",
            str(ch),
            "--vi",
            str(vi),
            "--book",
            "B",
            "--out-dir",
            str(out),
            "--table",
            str(t),
        ],
        env=env,
    )
    assert r.exit_code == 0, r.output
    report = json.loads((out / "B_align_report.json").read_text(encoding="utf-8"))
    assert report["online"]["found"] == 1 and report["online"]["asked"] == 1
    assert "経" not in report["unknown_chars"] and fake.asked == [("whv", "経")]
