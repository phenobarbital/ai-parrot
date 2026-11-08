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


# ---------------------------------------------------------------------------
# Ownership (TASK-5301)
# ---------------------------------------------------------------------------
from parrot.knowledge.pageindex.segments import (  # noqa: E402
    DocumentRevision, SourceInfo, attach_pdf_document, attach_section_document, render_body, validate_ownership,
)
from parrot.knowledge.pageindex.utils import structure_to_list  # noqa: E402


def _rev(pages):
    segs = segment_pages(pages)
    return DocumentRevision(doc_id="d", revision=revision_id(segs), source=SourceInfo(name="d.pdf", kind="pdf"),
                            created_at="2026-11-07T00:00:00Z", segments=segs)


def test_attach_pdf_shared_page_partition():
    rev = _rev([(1, "# Ch 1\n\nIntro.\n\n## 1.1 Scope\n\nScope text."), (2, "More scope.")])
    tree = [{"title": "Ch 1", "start_index": 1, "end_index": 2,
             "nodes": [{"title": "1.1 Scope", "start_index": 1, "end_index": 2}]}]
    attach_pdf_document(tree, rev)
    parent, child = tree[0], tree[0]["nodes"][0]
    assert parent["owned"] == [[0, 2]] and child["span"] == [2, 5]
    assert parent["doc_id"] == "d" and parent["revision"] == rev.revision
    assert validate_ownership(structure_to_list(tree), rev) == []


def test_attach_pdf_no_title_match():
    rev = _rev([(1, "Alpha text.\n\nBeta text."), (2, "Gamma text.")])
    tree = [{"title": "A", "start_index": 1, "end_index": 1},
            {"title": "B", "start_index": 1, "end_index": 2}]
    attach_pdf_document(tree, rev)
    # B starts at the shared page's first segment; A (earlier sibling) ends there and owns nothing
    assert tree[1]["span"] == [0, 3]
    assert tree[0]["span"] is None and tree[0]["owned"] == []
    assert validate_ownership(structure_to_list(tree), rev) == []


def test_attach_pdf_parent_interstitial_text():
    rev = _rev([(1, "# P\n\n## A\n\nA text."), (2, "Between children."), (3, "## B\n\nB text.")])
    tree = [{"title": "P", "start_index": 1, "end_index": 3,
             "nodes": [{"title": "A", "start_index": 1, "end_index": 1},
                       {"title": "B", "start_index": 3, "end_index": 3}]}]
    attach_pdf_document(tree, rev)
    parent = tree[0]
    assert parent["owned"] == [[0, 1], [3, 4]]
    body = render_body(rev, parent, parent["nodes"])
    assert body.count("<!-- continues in:") == 2
    assert body.index("continues in: A") < body.index("Between children.") < body.index("continues in: B")
    assert validate_ownership(structure_to_list(tree), rev) == []


def test_attach_pdf_front_and_back_matter_owned():
    rev = _rev([(1, "Cover."), (2, "# One\n\nBody."), (3, "Index.")])
    tree = [{"title": "One", "start_index": 2, "end_index": 2}]
    attach_pdf_document(tree, rev)
    assert tree[0]["span"] == [0, 4]
    assert validate_ownership(tree, rev) == []


def test_attach_section_document_leaf_and_parent():
    segs = segment_text("Own.", ["P"]) + segment_text("Leaf one.\n\nLeaf two.", ["P", "C"], seq_start=1)
    rev = DocumentRevision(doc_id="d", revision=revision_id(segs), source=SourceInfo(name="d", kind="markdown"),
                           created_at="2026-11-07T00:00:00Z", segments=segs)
    child = {"title": "C"}
    parent = {"title": "P", "nodes": [child]}
    attach_section_document([parent], rev, {id(parent): (0, 1), id(child): (1, 3)})
    assert parent["owned"] == [[0, 1]] and parent["span"] == [0, 3]
    assert child["span"] == [1, 3] and child["owned"] == [[1, 3]]
    assert validate_ownership([parent, child], rev) == []


def test_render_body_deterministic():
    rev = _rev([(1, "# P\n\nOwn.\n\n## C\n\nChild.")])
    tree = [{"title": "P", "start_index": 1, "end_index": 1,
             "nodes": [{"title": "C", "start_index": 1, "end_index": 1}]}]
    attach_pdf_document(tree, rev)
    first = render_body(rev, tree[0], tree[0]["nodes"])
    assert first == render_body(rev, tree[0], tree[0]["nodes"])
    assert first == "# P\n\nOwn.\n\n<!-- continues in: C -->"
    assert render_body(rev, tree[0]["nodes"][0], []) == "## C\n\nChild."


def test_validate_ownership_reports_gap_and_overlap():
    rev = _rev([(1, "A.\n\nB.\n\nC.")])
    nodes = [{"node_id": "1", "owned": [[0, 1]]}, {"node_id": "2", "owned": [[2, 3]]}]
    assert validate_ownership(nodes, rev) == ["gap [1, 2)"]
    nodes = [{"node_id": "1", "owned": [[0, 2]]}, {"node_id": "2", "owned": [[1, 3]]}]
    assert validate_ownership(nodes, rev) == ["overlap seq 1 owned by 1 and 2"]
    assert validate_ownership([{"node_id": "1", "owned": [[0, 9]]}], rev)[0].startswith("out of range")


def _anchor_free(tree):
    return all("anchor" not in n for n in structure_to_list(tree))


def test_attach_prefers_anchor():
    """Anchored nodes start at their own heading despite similar titles; no node keeps 'anchor' (AC-2, AC-10)."""
    pages = [(1, "# Scope Notes\n\nNotes text.\n\n# Scope\n\nScope text."), (2, "More.")]
    plain = [{"title": "Scope Notes", "start_index": 1, "end_index": 1},
             {"title": "Scope", "start_index": 1, "end_index": 2}]
    attach_pdf_document(plain, _rev(pages))
    assert [n["span"] for n in plain] == [None, [0, 5]]      # the ambiguity anchors remove (verified on current code)

    anchored = [{"title": "Scope Notes", "start_index": 1, "end_index": 1, "anchor": {"page": 1, "ordinal": 0}},
                {"title": "Scope", "start_index": 1, "end_index": 2, "anchor": {"page": 1, "ordinal": 2}}]
    rev = _rev(pages)
    attach_pdf_document(anchored, rev)
    assert [n["span"] for n in anchored] == [[0, 2], [2, 5]]
    assert validate_ownership(structure_to_list(anchored), rev) == []
    assert _anchor_free(anchored)


def test_attach_unresolved_anchor_and_cleared_subtree():
    """An unknown (page, ordinal) falls back to the title match; anchors under cleared subtrees are removed."""
    pages = [(1, "# Scope Notes\n\nNotes text.\n\n# Scope\n\nScope text."), (2, "More.")]
    tree = [{"title": "Scope Notes", "start_index": 1, "end_index": 1, "anchor": {"page": 1, "ordinal": 99}},
            {"title": "Ghost", "start_index": 5, "end_index": 5, "anchor": {"page": 5, "ordinal": 0},
             "nodes": [{"title": "Ghost child", "start_index": 5, "end_index": 5,
                        "anchor": {"page": 5, "ordinal": 1}}]}]
    attach_pdf_document(tree, _rev(pages))
    assert tree[0]["span"][0] == 0
    assert tree[1]["span"] is None
    assert _anchor_free(tree)


def test_attach_malformed_anchor_does_not_raise():
    """A malformed anchor (missing keys, unhashable values, non-dict) falls back without raising."""
    pages = [(1, "# A\n\nText."), (2, "# B\n\nMore.\n\n## C\n\nLeaf.")]
    tree = [{"title": "A", "start_index": 1, "end_index": 1, "anchor": {"page": [1], "ordinal": {}}},
            {"title": "B", "start_index": 2, "end_index": 2, "anchor": "bogus",
             "nodes": [{"title": "C", "start_index": 2, "end_index": 2, "anchor": {}}]}]
    attach_pdf_document(tree, _rev(pages))
    assert tree[0]["span"] == [0, 2]
    assert tree[1]["span"] == [2, 6] and tree[1]["nodes"][0]["span"] == [4, 6]
    assert _anchor_free(tree)
