from io import BytesIO

from parrot.knowledge.pageindex import builder


def test_extract_node_markdown_returns_pages(monkeypatch):
    monkeypatch.setattr(builder, "extract_markdown_per_page", lambda doc: [(1, "A"), (2, "B")])
    structure = [{"node_id": "0000", "start_index": 1, "end_index": 2}]
    node_md, pages = builder._extract_node_markdown("x.pdf", structure)
    assert node_md == {"0000": "AB"} and pages == [(1, "A"), (2, "B")]


def test_extract_node_markdown_fallbacks(monkeypatch):
    assert builder._extract_node_markdown(BytesIO(b"x"), []) == ({}, [])

    def boom(doc):
        raise ValueError("bad pdf")

    monkeypatch.setattr(builder, "extract_markdown_per_page", boom)
    assert builder._extract_node_markdown("x.pdf", []) == ({}, [])


def test_pages_returned_in_both_branches():
    from pathlib import Path

    source = Path(builder.__file__).read_text(encoding="utf-8")
    assert source.count('"_pages": pages,') == 2
