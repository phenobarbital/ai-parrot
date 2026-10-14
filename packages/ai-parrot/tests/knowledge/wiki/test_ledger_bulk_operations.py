"""Ledger/bulk/vault operations parity (FEAT-540 M3)."""

import pytest

from parrot.knowledge.wiki.ledger.operations import (
    LedgerClaimInput,
    LedgerCloseInput,
    LedgerContextInput,
    LedgerOpenInput,
    LedgerReadyInput,
    op_ledger_claim,
    op_ledger_close,
    op_ledger_context,
    op_ledger_open,
    op_ledger_ready,
)
from parrot.knowledge.wiki.operations import (
    IngestBatchInput,
    PageHashesInput,
    SourceSlicePayload,
    SyncPagesInput,
    VaultIngestInput,
    op_ingest_batch,
    op_page_hashes,
    op_sync_pull,
    op_sync_push,
    op_vault_ingest,
)
from parrot.knowledge.wiki.project import WikiProjectConfig
from parrot.knowledge.wiki.store import WikiPageRecord, create_wiki_store
from parrot.knowledge.wiki.tools import (
    LedgerClaimTool,
    LedgerCloseTool,
    LedgerContextTool,
    LedgerOpenTool,
    LedgerReadyTool,
    VaultIngestTool,
    WikiIngestBatchTool,
    WikiPageHashesTool,
    WikiSyncPullTool,
    WikiSyncPushTool,
)


class _FakeLedger:
    """Records every call; optionally raises."""

    def __init__(self, fail: bool = False) -> None:
        self.calls: list[tuple] = []
        self.fail = fail

    async def open_issue(self, **kw):
        if self.fail:
            raise RuntimeError("boom")
        self.calls.append(("open", kw))
        return "issue:1"

    async def ready_work(self, kind):
        self.calls.append(("ready", kind))
        return [{"id": "issue:1"}]

    async def claim(self, issue_id, actor):
        self.calls.append(("claim", issue_id, actor))
        return True

    async def close_issue(self, issue_id, reason, actor, **kw):
        self.calls.append(("close", issue_id, reason, actor, kw))
        return True

    async def get_context(self, paths, max_tokens):
        self.calls.append(("context", paths, max_tokens))
        return "ctx"


@pytest.fixture
def plane(tmp_path):
    (tmp_path / ".parrot" / "wiki").mkdir(parents=True)
    store = create_wiki_store(tmp_path / ".parrot" / "wiki", wiki_name="t", backend="sqlite")
    return tmp_path, store, WikiProjectConfig(wiki_name="t")


def _mem(concept_id: str, body: str, updated_at: str) -> WikiPageRecord:
    return WikiPageRecord(
        concept_id=concept_id, title=concept_id, body=body, origin="memory", asserted_by="human:a", updated_at=updated_at
    )


def _slice(path: str = "pkg/a.py") -> SourceSlicePayload:
    page = WikiPageRecord(concept_id=f"file:{path}", title=path, body="x", source_id=f"file:{path}", content_hash="h1")
    return SourceSlicePayload(source_id=f"file:{path}", pages=[page])


async def test_ledger_ops_match_tools():
    svc = _FakeLedger()
    res = await op_ledger_open(
        svc, LedgerOpenInput(title="t", body="b", discovered_from="spec:FEAT-1", about=["sym:a.py#f"])
    )
    assert res.data == {"issue_id": "issue:1"} and not res.is_error
    tool_res = await LedgerOpenTool(_FakeLedger())._execute(title="t", body="b", discovered_from="spec:FEAT-1")
    assert tool_res.result == {"issue_id": "issue:1"}

    assert (await op_ledger_ready(svc, LedgerReadyInput(kind="bug"))).data == {"issues": [{"id": "issue:1"}]}
    assert (await LedgerReadyTool(svc)._execute(kind=None)).result == {"issues": [{"id": "issue:1"}]}
    assert ("ready", "bug") in svc.calls and ("ready", None) in svc.calls

    assert (await op_ledger_claim(svc, LedgerClaimInput(issue_id="i", actor="agent:x"))).data == {"success": True}
    assert (await LedgerClaimTool(svc)._execute("i", actor="agent:y")).result == {"success": True}
    assert [c[2] for c in svc.calls if c[0] == "claim"] == ["agent:x", "agent:y"]

    await op_ledger_close(svc, LedgerCloseInput(issue_id="i", reason="r", resolved_by="commit:abc", actor="agent:x"))
    await LedgerCloseTool(svc)._execute("i", "r")
    closes = [c for c in svc.calls if c[0] == "close"]
    assert closes[0][4] == {"resolved_by": "commit:abc"} and closes[1][4] == {}

    assert (await op_ledger_context(svc, LedgerContextInput(file_paths=["a.py"]))).data == {"context": "ctx"}
    assert (await LedgerContextTool(svc)._execute(["a.py"], 10)).result == {"context": "ctx"}
    assert ("context", ["a.py"], 10) in svc.calls


async def test_ledger_errors_become_error_results():
    res = await op_ledger_open(_FakeLedger(fail=True), LedgerOpenInput(title="t", body="b", discovered_from="x"))
    assert res.is_error and res.text == "boom"
    tool_res = await LedgerOpenTool(_FakeLedger(fail=True))._execute(title="t", body="b", discovered_from="x")
    assert tool_res.success is False and tool_res.error == "boom"


async def test_page_hashes_and_ingest_parity(plane):
    root, store, cfg = plane
    res = await op_ingest_batch(
        store, IngestBatchInput(slices=[_slice(), _slice("pkg/b.py")], batch_id="b"), root=root, config=cfg
    )
    assert res.data["slices_applied"] == 2
    hashes = await op_page_hashes(store, PageHashesInput(concept_ids=["file:pkg/a.py", "file:nope"]))
    assert hashes.data == {"hashes": {"file:pkg/a.py": "h1", "file:nope": None}}
    tool_hashes = await WikiPageHashesTool(store)._execute(["file:pkg/a.py", "file:nope"])
    assert tool_hashes.result == hashes.data
    deleted = await WikiIngestBatchTool(store, root, cfg)._execute(slices=[], deleted_source_ids=["file:pkg/b.py"])
    assert deleted.result["slices_deleted"] == 1 and await store.get_page("file:pkg/b.py") is None


async def test_ingest_limits_are_error_results(plane):
    root, store, cfg = plane
    too_many = IngestBatchInput(slices=[_slice(f"p/{i}.py") for i in range(201)])
    res = await op_ingest_batch(store, too_many, root=root, config=cfg)
    assert res.is_error and "at most 200" in res.text
    assert await store.get_page("file:p/0.py") is None
    assert (await op_page_hashes(store, PageHashesInput(concept_ids=["i"] * 2001))).is_error


async def test_sync_push_pull_parity(plane):
    root, store, _cfg = plane
    await store.upsert_pages([_mem("memory:x", "server-new", "2026-02-01T00:00:00+00:00")])
    old = SyncPagesInput(pages=[_mem("memory:x", "old", "2026-01-01T00:00:00+00:00")])
    report = await op_sync_push(store, old, wiki_name="t")
    assert report.data["skipped_older"] == 1 and report.data["env"] == "t"
    newer = [_mem("memory:x", "newer", "2026-03-01T00:00:00+00:00")]
    tool_report = await WikiSyncPushTool(store, "t")._execute(pages=newer)
    assert tool_report.result["updated"] == 1
    assert (await store.get_page("memory:x"))["body"] == "newer"

    pulled = await op_sync_pull(store, SyncPagesInput(limit=10))
    tool_pulled = await WikiSyncPullTool(store)._execute(limit=10)
    assert pulled.data == tool_pulled.result
    assert [p["concept_id"] for p in pulled.data["pages"]] == ["memory:x"]


async def test_vault_ingest_no_vault_is_error(plane):
    root, store, cfg = plane
    res = await op_vault_ingest(store, VaultIngestInput(), root=root, config=cfg)
    assert res.is_error and "No Obsidian vault found" in res.text
    tool_res = await VaultIngestTool(store, root, cfg)._execute()
    assert tool_res.success is False and tool_res.error == res.text


def test_ops_modules_do_not_import_parrot_tools():
    import parrot.knowledge.wiki.ledger.operations as ledger_ops
    import parrot.knowledge.wiki.operations as ops

    for mod in (ledger_ops, ops):
        with open(mod.__file__, encoding="utf-8") as fh:
            assert "parrot.tools" not in fh.read()
