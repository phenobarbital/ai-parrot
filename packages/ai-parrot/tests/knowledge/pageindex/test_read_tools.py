"""Read tools: list_documents, outline, read_pages, read_segments (FEAT-840 / TASK-5309)."""

import asyncio
import json
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock

import pytest

from parrot.knowledge.pageindex.segments import RevisionMismatchError, RevisionUnavailableError
from parrot.knowledge.pageindex.toolkit import PageIndexToolkit
from parrot.knowledge.pageindex.utils import structure_to_list

LONG = "A" * 1000 + "B" * 1500  # one long paragraph (no blank line)
PAGES = [
    (1, "# Ch 1\n\nIntro text.\n\n## 1.1 Scope\n\nScope text."),
    (2, f"{LONG}\n\nSecond page paragraph."),
]


def _adapter() -> MagicMock:
    a = MagicMock()
    a.model = "heavy"
    response = MagicMock()
    response.output = "x"
    response.structured_output = None
    a.client = MagicMock()
    a.client.ask = AsyncMock(return_value=response)
    a.client.default_model = "test-model"
    a.ask = AsyncMock(return_value="x")
    return a


@pytest.fixture(autouse=True)
def _stub_tiktoken(monkeypatch):
    def _approx(text: str, model: str = "gpt-4o") -> int:
        return max(1, len(text or ""))

    monkeypatch.setattr("parrot.knowledge.pageindex.utils.count_tokens", _approx)
    monkeypatch.setattr("parrot.knowledge.pageindex.md_builder.count_tokens", _approx)
    monkeypatch.setattr(
        "parrot.knowledge.pageindex.toolkit.get_injection_scoring_engine", lambda force_reresolve=False: None
    )


@pytest.fixture
def toolkit(tmp_path: Path) -> PageIndexToolkit:
    return PageIndexToolkit(adapter=_adapter(), storage_dir=tmp_path, lightweight_model="light")


def _fake_build(pages):
    async def fake_build(doc, adapter, options=None, **kwargs):
        return {
            "doc_name": "doc.pdf",
            "structure": [
                {
                    "title": "Ch 1",
                    "node_id": "0000",
                    "start_index": 1,
                    "end_index": 2,
                    "nodes": [{"title": "1.1 Scope", "node_id": "0001", "start_index": 1, "end_index": 1}],
                }
            ],
            "_node_markdown": {},
            "_pages": pages,
        }

    return fake_build


@pytest.fixture
async def paged_toolkit(toolkit, tmp_path, monkeypatch):
    pdf = tmp_path / "doc.pdf"
    pdf.write_bytes(b"%PDF-1.4 fake")
    monkeypatch.setattr("parrot.knowledge.pageindex.toolkit.build_page_index", _fake_build(PAGES))
    await toolkit.create_tree("t")
    toolkit._imported = await toolkit.import_pdf("t", str(pdf))
    return toolkit


def _chars(result):
    return "".join(s["text"] for s in result["segments"])


@pytest.mark.asyncio
async def test_read_pages_order_and_budget(paged_toolkit):
    tk = paged_toolkit
    both = await tk.read_pages("t", "doc", "2,1", max_chars=100000)
    assert [s["address"]["page"] for s in both["segments"]] == [1, 1, 1, 1, 2, 2]
    assert both["framed"].startswith("<document_text") and both["truncated"] is False
    assert both["generation"] == 2

    stored = {s["seq"]: s["text"] for s in both["segments"]}
    got, cursor = {}, None
    for _ in range(50):
        part = await tk.read_pages("t", "doc", "1-2", max_chars=500, cursor=cursor)
        for s in part["segments"]:
            assert s["text"] == stored[s["seq"]][s["start"] : s["end"]]
            got.setdefault(s["seq"], "")
            got[s["seq"]] += s["text"]
        cursor = part["next_cursor"]
        if cursor is None:
            break
    assert got == stored


@pytest.mark.asyncio
async def test_read_pages_unpaged_document_raises(toolkit):
    await toolkit.create_tree("kb")
    md = "# Tutorial\n\nWelcome to the tutorial section of the manual with enough text.\n"
    imported = await toolkit.insert_markdown("kb", md, doc_name="Tut.md")
    with pytest.raises(ValueError, match="read_segments"):
        await toolkit.read_pages("kb", imported["doc_id"], "1")
    whole = await toolkit.read_segments("kb", imported["doc_id"])
    assert whole["segments"][0]["address"]["section"] == ["Tutorial"]


@pytest.mark.asyncio
async def test_read_segments_oversized_segment_prefix(paged_toolkit):
    tk = paged_toolkit
    page2 = await tk.read_pages("t", "doc", "2", max_chars=100000)
    long_seq = next(s["seq"] for s in page2["segments"] if s["text"] == LONG)
    res = await tk.read_segments("t", "doc", start=long_seq, end=long_seq + 1, max_chars=1000)
    seg = res["segments"][0]
    assert (seg["start"], seg["end"], seg["truncated"]) == (0, 1000, True)
    assert res["truncated"] and res["next_cursor"].endswith(f"#{long_seq}+1000")
    assert "B" not in _chars(res) and _chars(res) == "A" * 1000


@pytest.mark.asyncio
async def test_read_segments_by_node_owned_ranges(paged_toolkit):
    tk = paged_toolkit
    nodes = structure_to_list((await tk.get_tree("t"))["structure"])
    parent, child = nodes[0], nodes[1]
    res = await tk.read_segments("t", node_id=parent["node_id"], max_chars=100000)
    texts = [s["text"] for s in res["segments"]]
    assert "Intro text." in texts and "Scope text." not in texts
    child_res = await tk.read_segments("t", node_id=child["node_id"], max_chars=100000)
    assert "Scope text." in [s["text"] for s in child_res["segments"]]


@pytest.mark.asyncio
async def test_cursor_outside_selection_rejected(paged_toolkit):
    """FEAT-844 AC-7: a cursor whose seq is not in the requested pages raises instead of dropping its offset."""
    tk = paged_toolkit
    first = await tk.read_pages("t", "doc", "2", max_chars=600)
    assert first["truncated"] and first["next_cursor"]
    cursor = first["next_cursor"]
    with pytest.raises(ValueError, match="not in the requested selection"):
        await tk.read_pages("t", "doc", "1", cursor=cursor)
    resumed = await tk.read_pages("t", "doc", "2", cursor=cursor)
    assert resumed["segments"][0]["seq"] == first["segments"][-1]["seq"]
    assert resumed["segments"][0]["start"] == first["segments"][-1]["end"]


@pytest.mark.asyncio
async def test_cursor_revision_mismatch(paged_toolkit):
    with pytest.raises(RevisionMismatchError):
        await paged_toolkit.read_pages("t", "doc", "1", cursor=f"doc@{'0' * 16}#0+0")
    with pytest.raises(ValueError):
        await paged_toolkit.read_pages("t", "doc", "1", cursor="garbage")


@pytest.mark.asyncio
async def test_read_pins_generation_and_unavailable_revision(paged_toolkit, tmp_path):
    tk = paged_toolkit
    old_tree = await tk.get_tree("t")
    revision = tk._imported["revision"]
    (tmp_path / "t" / "segments" / f"doc.{revision}.json").unlink()
    tk._segment_store._cache.clear()
    with pytest.raises(RevisionUnavailableError):
        await asyncio.to_thread(tk._revision_for, "t", old_tree, "doc")
    with pytest.raises(RevisionUnavailableError):
        await tk.read_pages("t", "doc", "1")
    rows = await tk.list_documents("t")
    assert rows[0]["available"] is False


@pytest.mark.asyncio
async def test_no_segmented_documents_message(toolkit):
    await toolkit.create_tree("empty")
    with pytest.raises(KeyError, match="pageindex_index_segments"):
        await toolkit.read_pages("empty", "doc", "1")
    assert await toolkit.list_documents("empty") == []


@pytest.mark.asyncio
async def test_outline_and_list_documents(paged_toolkit):
    tk = paged_toolkit
    rows = await tk.list_documents("t")
    assert len(rows) == 1 and rows[0]["doc_id"] == "doc" and rows[0]["pages"] == 2 and rows[0]["available"]
    assert rows[0]["segments"] == 6 and rows[0]["scored_by"] == "regex"

    full = await tk.outline("t", max_depth=3)
    assert [e["depth"] for e in full["entries"]] == [1, 2] and not full["truncated"]
    shallow = await tk.outline("t", max_depth=1)
    assert [e["title"] for e in shallow["entries"]] == ["Ch 1"]
    sub = await tk.outline("t", node_id=full["entries"][1]["node_id"])
    assert len(sub["entries"]) == 1
    tiny = await tk.outline("t", max_chars=10)
    assert tiny["truncated"] is True and len(json.dumps(tiny["entries"])) <= 300


def test_read_tools_are_exposed(toolkit):
    names = set(toolkit.list_tool_names())
    assert {"pageindex_list_documents", "pageindex_outline", "pageindex_read_pages", "pageindex_read_segments"} <= names
