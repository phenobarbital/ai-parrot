"""Unit tests for the bulk ingest tools (FEAT-569 TASK-3356)."""

import pytest

from parrot.knowledge.wiki.project import WikiProjectConfig
from parrot.knowledge.wiki.store import WikiPageRecord, create_wiki_store
from parrot.knowledge.wiki.symbols import SymbolKind, SymbolRecord
from parrot.knowledge.wiki.tools import (
    SourceSlicePayload,
    WikiIngestBatchTool,
    WikiPageHashesTool,
    create_bulk_tools,
)


@pytest.fixture
def plane(tmp_path):
    (tmp_path / ".parrot" / "wiki").mkdir(parents=True)
    store = create_wiki_store(tmp_path / ".parrot" / "wiki", wiki_name="t", backend="sqlite")
    return tmp_path, store, WikiProjectConfig(wiki_name="t")


def _slice(path="pkg/a.py", body="x"):
    page = WikiPageRecord(concept_id=f"file:{path}", title=path, body=body, source_id=f"file:{path}", content_hash="h1")
    sym = SymbolRecord(
        rel_path=path,
        language="python",
        kind=SymbolKind.FUNCTION,
        name="f",
        qualname="f",
        start_line=1,
        end_line=1,
        start_byte=0,
        end_byte=1,
        content_hash="s1",
    )
    return SourceSlicePayload(source_id=f"file:{path}", pages=[page], symbols=[sym])


async def test_ingest_then_hashes_then_delete(plane):
    root, store, cfg = plane
    tool = WikiIngestBatchTool(store, root, cfg)
    res = await tool._execute(slices=[_slice(), _slice("pkg/b.py")], batch_id="b1")
    assert res.result["slices_applied"] == 2 and res.result["symbols_dropped"] == 0
    assert (await store.symbols_for("pkg/a.py"))[0].qualname == "f"
    hashes = (await WikiPageHashesTool(store)._execute(["file:pkg/a.py", "file:nope"])).result["hashes"]
    assert hashes == {"file:pkg/a.py": "h1", "file:nope": None}
    res = await tool._execute(slices=[], deleted_source_ids=["file:pkg/b.py"])
    assert res.result["slices_deleted"] == 1 and await store.get_page("file:pkg/b.py") is None


async def test_limits(plane):
    root, store, cfg = plane
    tool = WikiIngestBatchTool(store, root, cfg)
    res = await tool._execute(slices=[_slice(f"p/{i}.py") for i in range(201)])
    assert res.success is False
    assert await store.get_page("file:p/0.py") is None
    big = await tool._execute(slices=[_slice("p/big.py", body="y" * 1_100_000)])
    assert big.success is False and "payload too large" in big.error
    assert await store.get_page("file:p/big.py") is None
    assert (await WikiPageHashesTool(store)._execute(["i"] * 2001)).success is False
    names = [t.name for t in create_bulk_tools(store, root, cfg)]
    assert names[:2] == ["wiki_page_hashes", "wiki_ingest_batch"]
    assert set(names[2:]) == {"wiki_sync_push", "wiki_sync_pull"}


async def test_symbols_dropped(plane):
    root, store, cfg = plane

    async def _zero(symbols, source_id=None):
        return 0

    store.upsert_symbols = _zero
    res = await WikiIngestBatchTool(store, root, cfg)._execute(slices=[_slice()])
    assert res.result["symbols_dropped"] == 1
