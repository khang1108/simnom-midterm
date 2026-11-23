from __future__ import annotations

from ocr_nom_align.pages import hyphen_inconsistent, join_vi


def run(lines, **kw):
    recs: list[dict] = []
    text, _ = join_vi([("p.001.jpg", lines)], records=recs, **kw)
    return text, recs


def test_capitalised_parts_are_kept_and_listed_unreviewed():
    text, recs = run(["Chúa Phi-", "Lip-pê đến."])
    assert "Phi-Lip-pê" in text
    r = recs[0]
    assert (r["action"], r["reason"], r["reviewed"]) == ("kept", "capitals", 0)


def test_lowercase_word_is_dropped_and_listed():
    text, recs = run(["tin-", "tưởng nhau"])
    assert text == "tin tưởng nhau"
    assert (recs[0]["action"], recs[0]["reason"], recs[0]["reviewed"]) == ("dropped", "default", 0)


def test_manual_list_marks_reviewed_and_keeps():
    text, recs = run(["gọi là A-", "ve nhé"], manual=frozenset({"A-ve"}))
    assert "A-ve" in text
    assert (recs[0]["action"], recs[0]["reason"], recs[0]["reviewed"]) == ("kept", "manual", 1)


def test_names_file_keeps_without_review():
    _, recs = run(["gọi là Phi-", "ri-tô"], keep_words=frozenset({"Phi-ri-tô"}))
    assert (recs[0]["action"], recs[0]["reason"], recs[0]["reviewed"]) == ("kept", "names", 0)


def test_inconsistent_forms_and_manual_list_silences():
    text = "Kính A-ve Maria. Lại nói Ave Maria."
    found = hyphen_inconsistent(text)
    assert len(found) == 1 and set(found[0]["forms"]) == {"A-ve", "Ave"}
    assert hyphen_inconsistent(text, frozenset({"A-ve"})) == []
