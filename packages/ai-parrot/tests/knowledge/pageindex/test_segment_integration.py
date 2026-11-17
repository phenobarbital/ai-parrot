"""FEAT-840 integration tests: segments end to end."""

from __future__ import annotations

import asyncio
import json
import multiprocessing as mp
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest

from parrot.knowledge.pageindex.pdf_to_markdown import extract_markdown_per_page
from parrot.knowledge.pageindex.segment_store import SegmentStore
from parrot.knowledge.pageindex.segments import SegmentAddress
from parrot.knowledge.pageindex.toolkit import PageIndexToolkit

FIXTURE = Path(__file__).parent / "fixtures" / "arxiv_2408_09869.pdf"


@pytest.fixture(scope="module")
def fixture_pages() -> list[tuple[int, str]]:
    return extract_markdown_per_page(str(FIXTURE))


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
def _stubs(monkeypatch):
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


def _fake_builder(pages: list[tuple[int, str]]):
    last = pages[-1][0]
    mid = max(1, last // 2)

    async def fake_build(doc, adapter, options=None, **kwargs):
        return {
            "doc_name": "arxiv.pdf",
            "structure": [
                {"title": "First half", "node_id": "0000", "start_index": 1, "end_index": mid},
                {"title": "Second half", "node_id": "0001", "start_index": mid + 1, "end_index": last},
            ],
            "_node_markdown": {},
            "_pages": pages,
        }

    return fake_build


@pytest.mark.asyncio
async def test_segment_roundtrip_pdf_to_citation_address(toolkit, fixture_pages, monkeypatch, tmp_path):
    monkeypatch.setattr("parrot.knowledge.pageindex.toolkit.build_page_index", _fake_builder(fixture_pages))
    await toolkit.create_tree("t")
    imported = await toolkit.import_pdf("t", str(FIXTURE))
    docs = await toolkit.list_documents("t")
    assert len(docs) == 1 and docs[0]["pages"] == len(fixture_pages)
    outline = await toolkit.outline("t")
    assert len(outline["entries"]) == 2

    rev = SegmentStore(tmp_path).load_revision("t", imported["doc_id"], imported["revision"])
    cursor, seen = None, 0
    for _ in range(200):
        res = await toolkit.read_pages("t", imported["doc_id"], "1-2", max_chars=2000, cursor=cursor)
        for read in res["segments"]:
            stored = rev.segments[read["seq"]].text
            assert read["text"] == stored[read["start"]:read["end"]]
            label = SegmentAddress(**read["address"]).label
            assert label.startswith("p. ") and "¶" in label
            seen += 1
        cursor = res["next_cursor"]
        if cursor is None:
            break
    assert seen > 0 and cursor is None


def _reader(storage_dir: str, doc_id: str, out_path: str, loops: int) -> None:
    """Read page 1 repeatedly from a separate process; record revisions or the first error."""

    async def run() -> None:
        toolkit = PageIndexToolkit(adapter=SimpleNamespace(model="none", client=None), storage_dir=storage_dir)
        revisions: set[str] = set()
        error = None
        for _ in range(loops):
            try:
                res = await toolkit.read_pages("t", doc_id, "1", max_chars=2000)
                revisions.add(res["revision"])
            except Exception as exc:  # noqa: BLE001
                error = repr(exc)
                break
            await asyncio.sleep(0.01)
        Path(out_path).write_text(json.dumps({"revisions": sorted(revisions), "error": error}))

    asyncio.run(run())


@pytest.mark.asyncio
async def test_two_processes_read_during_reimport(tmp_path, fixture_pages, monkeypatch):
    short = fixture_pages[:4]
    changed = [(n, text + ("\n\nChanged paragraph." if n == 1 else "")) for n, text in short]
    toolkit = PageIndexToolkit(adapter=_adapter(), storage_dir=tmp_path, lightweight_model="light")
    monkeypatch.setattr("parrot.knowledge.pageindex.toolkit.build_page_index", _fake_builder(short))
    await toolkit.create_tree("t")
    first = await toolkit.import_pdf("t", str(FIXTURE), doc_id="arxiv")

    out = tmp_path / "reader.json"
    process = mp.get_context("spawn").Process(target=_reader, args=(str(tmp_path), "arxiv", str(out), 60))
    process.start()
    monkeypatch.setattr("parrot.knowledge.pageindex.toolkit.build_page_index", _fake_builder(changed))
    await asyncio.sleep(0.2)
    tree = await toolkit.get_tree("t")
    for node in list(tree["structure"]):
        await toolkit.delete_node("t", node["node_id"])
    second = await toolkit.import_pdf("t", str(FIXTURE), doc_id="arxiv")
    await asyncio.to_thread(process.join, 90)
    if process.is_alive():
        process.terminate()
        pytest.fail("reader did not finish")
    report = json.loads(out.read_text())
    assert second["revision"] != first["revision"]
    assert report["error"] is None, report
    assert report["revisions"] and set(report["revisions"]) <= {first["revision"], second["revision"]}


def test_bookstore_mcp_lists_new_tools(tmp_path):
    from parrot.knowledge.bookstore.config import LibraryLocation
    from parrot.knowledge.bookstore.mcp_server import create_bookstore_mcp_server

    server = create_bookstore_mcp_server([LibraryLocation(scope="project", root=tmp_path / "lib")])
    assert {"bookstore_read_pages", "bookstore_read_segments", "bookstore_outline"} <= set(server.tools)


@pytest.mark.asyncio
async def test_legacy_tree_untouched_until_index_segments(toolkit, tmp_path, monkeypatch):
    async def no_walk(self, query):
        from parrot.knowledge.pageindex.schemas import TreeSearchResult

        return TreeSearchResult(thinking="", node_list=[])

    monkeypatch.setattr("parrot.knowledge.pageindex.hybrid_search.PageIndexRetriever.search", no_walk)
    await toolkit.create_tree("old")
    node = await toolkit.add_node("old", "Legacy", body="Legacy body text about installers.")
    await toolkit.update_node_content("old", node["node_id"], "Legacy body text about installers, revised.")

    def snapshot() -> dict[str, tuple[int, int]]:
        return {
            p.relative_to(tmp_path).as_posix(): (p.stat().st_mtime_ns, p.stat().st_size)
            for p in sorted(tmp_path.rglob("*"))
            if p.is_file() and p.suffix != ".lock"
        }

    before = snapshot()
    await toolkit.get_tree("old")
    await toolkit.search("old", "installers", top_k=3, use_llm_walk=False, use_bm25=True)
    await toolkit.retrieve("old", "installers")
    assert snapshot() == before
    with pytest.raises(KeyError, match="pageindex_index_segments"):
        await toolkit.read_pages("old", "anything", "1")
