"""FEAT-843 — snapshot-bound search/read helpers (AC-16)."""

import copy
import inspect
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock

import pytest

from parrot.knowledge.pageindex.segments import RevisionMismatchError
from parrot.knowledge.pageindex.toolkit import PageIndexToolkit

LONG = "A" * 1000 + "B" * 1500
PAGES = [
    (1, "# Ch 1\n\nIntro text.\n\n## 1.1 Scope\n\nScope text."),
    (2, f"{LONG}\n\nSecond page paragraph."),
]


def _adapter() -> MagicMock:
    adapter = MagicMock()
    adapter.model = "heavy"
    response = MagicMock()
    response.output = "x"
    response.structured_output = None
    adapter.client = MagicMock()
    adapter.client.ask = AsyncMock(return_value=response)
    adapter.client.default_model = "test-model"
    adapter.ask = AsyncMock(return_value="x")
    return adapter


@pytest.fixture(autouse=True)
def _stub_tiktoken(monkeypatch: pytest.MonkeyPatch) -> None:
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


def _fake_build(pages: list[tuple[int, str]], title: str = "Ch 1"):
    async def fake_build(doc, adapter, options=None, **kwargs):
        return {
            "doc_name": "doc.pdf",
            "structure": [
                {
                    "title": title,
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
async def paged_toolkit(toolkit: PageIndexToolkit, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> PageIndexToolkit:
    pdf = tmp_path / "doc.pdf"
    pdf.write_bytes(b"%PDF-1.4 fake")
    monkeypatch.setattr("parrot.knowledge.pageindex.toolkit.build_page_index", _fake_build(PAGES))
    await toolkit.create_tree("t")
    toolkit._imported = await toolkit.import_pdf("t", str(pdf), doc_id="doc")
    toolkit._pdf = pdf
    return toolkit


def _snapshot_tools(toolkit: PageIndexToolkit, tree: dict) -> dict[str, object]:
    return {tool.name: tool.bound_method for tool in toolkit._agentic_read_tools("t", tree)}


def test_public_read_tools_unchanged_signatures(paged_toolkit: PageIndexToolkit) -> None:
    tools = paged_toolkit._agentic_read_tools("t", copy.deepcopy(paged_toolkit._load_tree("t")))
    for tool in tools:
        public_name = tool.name.removeprefix("pageindex_")
        assert inspect.signature(tool.bound_method) == inspect.signature(getattr(paged_toolkit, public_name))
        assert tool.bound_method.__doc__ == getattr(paged_toolkit, public_name).__doc__


def test_snapshot_tools_named_like_public(paged_toolkit: PageIndexToolkit) -> None:
    tools = paged_toolkit._agentic_read_tools("t", copy.deepcopy(paged_toolkit._load_tree("t")))
    assert {tool.name for tool in tools} == {
        "pageindex_list_documents",
        "pageindex_outline",
        "pageindex_read_pages",
        "pageindex_read_segments",
    }


@pytest.mark.asyncio
async def test_snapshot_rejects_other_tree_name(paged_toolkit: PageIndexToolkit) -> None:
    tools = _snapshot_tools(paged_toolkit, copy.deepcopy(paged_toolkit._load_tree("t")))
    calls = {
        "pageindex_list_documents": {},
        "pageindex_outline": {},
        "pageindex_read_pages": {"doc_id": "doc", "pages": "1"},
        "pageindex_read_segments": {"doc_id": "doc"},
    }
    for name, tool in tools.items():
        with pytest.raises(ValueError, match="bound to tree 't'"):
            await tool(tree_name="other", **calls[name])


@pytest.mark.asyncio
async def test_reimport_does_not_change_snapshot(
    paged_toolkit: PageIndexToolkit, monkeypatch: pytest.MonkeyPatch
) -> None:
    toolkit = paged_toolkit
    snapshot = copy.deepcopy(toolkit._load_tree("t"))
    tools = _snapshot_tools(toolkit, snapshot)
    old_revision = toolkit._imported["revision"]
    old_generation = snapshot["generation"]["id"]

    before_documents = await tools["pageindex_list_documents"](tree_name="t")
    before_outline = await tools["pageindex_outline"](tree_name="t")
    first_read = await tools["pageindex_read_pages"](tree_name="t", doc_id="doc", pages="2", max_chars=500)
    assert first_read["next_cursor"] is not None

    live_tree = toolkit._load_tree("t")
    for node in list(live_tree["structure"]):
        await toolkit.delete_node("t", node["node_id"])
    replacement_pages = [(1, "# Replacement\n\nNew text."), (2, "A different second page.")]
    monkeypatch.setattr(
        "parrot.knowledge.pageindex.toolkit.build_page_index", _fake_build(replacement_pages, "Replacement")
    )
    imported = await toolkit.import_pdf("t", str(toolkit._pdf), doc_id="doc")

    after_documents = await tools["pageindex_list_documents"](tree_name="t")
    after_outline = await tools["pageindex_outline"](tree_name="t")
    continued = await tools["pageindex_read_pages"](
        tree_name="t", doc_id="doc", pages="2", max_chars=500, cursor=first_read["next_cursor"]
    )
    snapshot_read = await tools["pageindex_read_pages"](tree_name="t", doc_id="doc", pages="2", max_chars=100000)

    assert imported["revision"] != old_revision
    assert toolkit._load_tree("t")["generation"]["id"] != old_generation
    assert after_documents == before_documents
    assert after_documents[0]["revision"] == old_revision
    assert after_outline == before_outline
    assert after_outline["generation"] == old_generation
    assert continued["revision"] == old_revision
    assert snapshot_read["generation"] == old_generation
    assert LONG in "".join(segment["text"] for segment in snapshot_read["segments"])
    with pytest.raises(RevisionMismatchError):
        await tools["pageindex_read_pages"](
            tree_name="t", doc_id="doc", pages="1", cursor=f"doc@{imported['revision']}#0+0"
        )


def test_agentic_search_not_cached(paged_toolkit: PageIndexToolkit) -> None:
    snapshot = copy.deepcopy(paged_toolkit._load_tree("t"))
    cached = dict(paged_toolkit._search)
    engine = paged_toolkit._agentic_search("t", snapshot)

    assert engine._tree is snapshot
    assert engine.generation_id == snapshot["generation"]["id"]
    assert paged_toolkit._search == cached
