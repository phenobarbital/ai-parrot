import pytest

from parrot.knowledge.pageindex.segments import (
    SegmentAddress, derive_doc_id, format_cursor, parse_cursor, parse_page_spec,
    revision_id, segment_pages, segment_text, split_blocks,
)


@pytest.fixture(autouse=True)
def _stub_tiktoken(monkeypatch):
    monkeypatch.setattr("parrot.knowledge.pageindex.utils.count_tokens", lambda t, model="gpt-4o": max(1, len(t)))


PAGE = "# Title\n\nIntro para.\n\n```py\nx = 1\n\ny = 2\n```\n\n| a | b |\n|---|---|\n| 1 | 2 |\n\n- one\n- two\n"


def test_split_blocks_keeps_fences_and_tables_whole():
    blocks = split_blocks(PAGE)
    assert [k for k, _, _ in blocks] == ["heading", "paragraph", "code", "table", "list"]
    assert blocks[0][2] == 1
    assert blocks[2][1] == "```py\nx = 1\n\ny = 2\n```"


def test_split_blocks_keeps_every_nonblank_line_verbatim():
    text = "Para one\n  indented kept\n\n![fig](a.png)\n\n1. a\n   cont\n2. b\n\n```\nopen"
    blocks = split_blocks(text)
    joined = "\n".join(b[1] for b in blocks)
    for line in text.split("\n"):
        if line.strip():
            assert joined.count(line) == 1
    assert [k for k, _, _ in blocks] == ["paragraph", "caption", "list", "code"]


def test_segment_pages_ordinals_restart_per_page():
    segs = segment_pages([(1, "A.\n\nB."), (2, ""), (3, "C.")])
    assert [(s.seq, s.page, s.ordinal) for s in segs] == [(0, 1, 0), (1, 1, 1), (2, 3, 0)]


def test_segment_text_sets_section_and_no_page():
    segs = segment_text("One.\n\nTwo.", ["Setup", "Install"], seq_start=5)
    assert [(s.seq, s.page, s.ordinal, s.section) for s in segs] == [
        (5, None, 0, ["Setup", "Install"]), (6, None, 1, ["Setup", "Install"])]


def test_revision_id_is_content_hash():
    a = segment_pages([(1, "A.\n\nB.")])
    b = segment_pages([(7, "A.\n\nB.")])
    c = segment_pages([(1, "A.\n\nC.")])
    assert revision_id(a) == revision_id(b)
    assert revision_id(a) != revision_id(c)
    assert len(revision_id(a)) == 16


def test_derive_doc_id_stable_and_disambiguated():
    first = derive_doc_id("Report 2026.pdf", taken={}, source_sha256="aa")
    assert first == "report-2026"
    assert derive_doc_id("Report 2026.pdf", taken={}, source_sha256="aa") == first
    assert derive_doc_id("Report 2026.pdf", taken={first: "aa"}, source_sha256="aa") == first
    other = derive_doc_id("Report 2026.pdf", taken={first: "aa"}, source_sha256="bb")
    assert other != first and other.startswith(first + "-") and len(other) == len(first) + 7
    assert derive_doc_id("???", taken={}, source_sha256=None) == "doc"


def test_parse_page_spec_and_cursor():
    assert parse_page_spec("5-7,12", max_page=20) == [5, 6, 7, 12]
    for bad in ("", "0", "21", "a-b"):
        with pytest.raises(ValueError):
            parse_page_spec(bad, max_page=20)
    assert parse_cursor(format_cursor("doc", "0" * 16, 3, 10)) == ("doc", "0" * 16, 3, 10)
    with pytest.raises(ValueError):
        parse_cursor("nonsense")


def test_address_labels():
    paged = SegmentAddress(doc_id="d", revision="0" * 16, seq=4, page=12, ordinal=2)
    unpaged = SegmentAddress(doc_id="d", revision="0" * 16, seq=4, ordinal=1, section=["Setup", "Install"])
    assert paged.label == "p. 12 ¶3"
    assert unpaged.label == "Setup > Install ¶2"
    assert paged.key == f"d@{'0' * 16}#4"
