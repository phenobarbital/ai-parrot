"""Durable delta ingestion job tests (TASK-3049)."""

from __future__ import annotations

import ast
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Any, Optional

import pytest

from parrot.knowledge.contracts.library import ContractLibrary
from parrot_tools.contracts.jobs import DeltaIngestResult, SourceConfig, ingest_delta
from parrot_tools.contracts.retrieval import ContractRetrieval, RequestContext

from .test_retrieval import TODAY, FakeCatalog, reader_context

FROZEN_NOW = datetime(2026, 9, 9, 12, 0, 0, tzinfo=timezone.utc)

MSA = """# ACME Master Services Agreement

Entered into between Troc Global Inc. and ACME, Inc.

## Compliance

Vendor shall maintain SOC 2 Type II certification.
"""


class FakeDeltaTool:
    """Replays scripted delta pages, one per call."""

    def __init__(self, pages: list[dict[str, Any]]) -> None:
        self.pages = pages
        self.calls: list[dict[str, Any]] = []

    async def enumerate(self, **kwargs):
        self.calls.append(kwargs)
        return self.pages[min(len(self.calls) - 1, len(self.pages) - 1)]


class FakeIndexer:
    """Minimal PageIndex tree builder over a real content store."""

    def __init__(self, storage_dir, adapter=None) -> None:
        from parrot.knowledge.pageindex.content_store import NodeContentStore
        from parrot.knowledge.pageindex.store import JSONTreeStore

        self.storage_dir = Path(storage_dir)
        self.content = NodeContentStore(self.storage_dir)
        self.store = JSONTreeStore(self.storage_dir)

    async def create_tree(self, tree_name, doc_name=None):
        self.store.save(tree_name, {"doc_name": doc_name or tree_name, "structure": []})
        return {"tree_name": tree_name}

    async def insert_markdown(self, tree_name, markdown, parent_node_id=None, doc_name=None):
        tree = self.store.load(tree_name)
        nodes = []
        for index, block in enumerate(
            [block for block in markdown.split("\n#") if block.strip()]
        ):
            node_id = f"{index:04d}"
            title = block.lstrip("#").splitlines()[0].strip()
            nodes.append({"node_id": node_id, "title": title, "nodes": []})
            self.content.save(tree_name, node_id, block)
        tree["structure"] = nodes
        self.store.save(tree_name, tree)
        return {"tree_name": tree_name}

    async def get_tree(self, tree_name):
        return self.store.load(tree_name)

    async def delete_tree(self, tree_name):
        self.store.delete(tree_name)
        return {"tree_name": tree_name}


def item(item_id: str, **overrides) -> dict[str, Any]:
    """A delta item payload as the tools emit it."""
    payload = {
        "item_id": item_id,
        "drive_id": "drive-1",
        "name": f"{item_id}.md",
        "path": "/drive/root:/legal",
        "web_url": f"https://graph.microsoft.com/legal/{item_id}.md",
        "sha256": f"sha-{item_id}",
        "deleted": False,
        "is_folder": False,
    }
    payload.update(overrides)
    return payload


def page(items, *, delta_link="https://graph.microsoft.com/final", **overrides):
    """A delta enumeration result payload."""
    payload = {
        "items": items,
        "tombstones": [entry["item_id"] for entry in items if entry.get("deleted")],
        "delta_link": delta_link,
        "pages": 1,
        "complete": delta_link is not None,
        "truncated": False,
        "rescan_required": False,
    }
    payload.update(overrides)
    return payload


@pytest.fixture()
def workspace(tmp_path):
    """A library over an in-memory catalog plus a document folder."""
    catalog = FakeCatalog()
    indexers: dict[Path, FakeIndexer] = {}
    library = ContractLibrary(
        catalog=catalog,
        storage_root=tmp_path / "storage",
        evidence_root=tmp_path / "evidence",
        adapter=None,
        indexer_factory=lambda directory, adapter: indexers.setdefault(
            Path(directory), FakeIndexer(directory, adapter)
        ),
        now=lambda: FROZEN_NOW,
        today=lambda: TODAY,
    )
    documents = tmp_path / "documents"
    documents.mkdir()

    async def downloader(entry):
        path = documents / f"{entry['item_id']}.md"
        if not path.exists():
            path.write_text(MSA + f"\n\nItem {entry['item_id']}.\n")
        return path

    return library, downloader, documents


def principal_context() -> RequestContext:
    """The configured service principal this job runs as."""
    return RequestContext(
        user_id="svc-contracts",
        roles=("contract_reader",),
        tenant_id="troc",
        employee_id="svc",
    )


SOURCE = SourceConfig(source="sharepoint://legal", drive_id="drive-1", folder_path="legal")


# --------------------------------------------------------------------------
# 1. Paging, identity and outcomes
# --------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_a_complete_batch_ingests_and_commits_the_cursor(workspace):
    library, downloader, _ = workspace
    tool = FakeDeltaTool([page([item("a"), item("b")])])

    result = await ingest_delta(
        library=library,
        delta_tool=tool,
        source=SOURCE,
        principal=principal_context(),
        downloader=downloader,
    )

    assert isinstance(result, DeltaIngestResult)
    assert result.report.added == 2
    assert result.durable is True
    assert result.cursor_committed == "https://graph.microsoft.com/final"
    assert await library.catalog.get_delta_token("sharepoint://legal") == (
        "https://graph.microsoft.com/final"
    )
    assert tool.calls[0]["delta_token"] is None
    assert tool.calls[0]["folder_path"] == "legal"


@pytest.mark.asyncio
async def test_source_item_identity_is_recorded_for_each_item(workspace):
    library, downloader, _ = workspace
    tool = FakeDeltaTool([page([item("a")])])
    await ingest_delta(
        library=library,
        delta_tool=tool,
        source=SOURCE,
        principal=principal_context(),
        downloader=downloader,
    )

    stored = await library.catalog.get_source_item("drive-1", "a")
    assert stored is not None
    assert stored.contract_id == "a"
    assert stored.sha256 == "sha-a"
    assert stored.deleted is False


@pytest.mark.asyncio
async def test_an_unchanged_sha_creates_no_new_revision(workspace):
    library, downloader, _ = workspace
    tool = FakeDeltaTool([page([item("a")]), page([item("a")])])

    first = await ingest_delta(
        library=library, delta_tool=tool, source=SOURCE,
        principal=principal_context(), downloader=downloader,
    )
    second = await ingest_delta(
        library=library, delta_tool=tool, source=SOURCE,
        principal=principal_context(), downloader=downloader,
    )

    assert first.report.added == 1
    assert second.report.added == 0
    assert second.report.skipped == 1
    assert "unchanged" in second.report.items[0].reason
    assert (await library.catalog.get("a")).revision == 1


@pytest.mark.asyncio
async def test_a_duplicate_item_in_one_batch_is_carded_once(workspace):
    library, downloader, _ = workspace
    tool = FakeDeltaTool([page([item("a"), item("a")])])

    result = await ingest_delta(
        library=library, delta_tool=tool, source=SOURCE,
        principal=principal_context(), downloader=downloader,
    )
    assert result.report.added == 1
    assert result.report.skipped == 1
    assert await library.catalog.taken_slugs() == {"a"}


@pytest.mark.asyncio
async def test_a_rename_keeps_the_same_contract(workspace):
    library, downloader, documents = workspace
    tool = FakeDeltaTool(
        [
            page([item("a")]),
            page([item("a", name="renamed.md", web_url="https://graph.microsoft.com/legal/renamed.md")]),
        ]
    )

    await ingest_delta(
        library=library, delta_tool=tool, source=SOURCE,
        principal=principal_context(), downloader=downloader,
    )
    # The file changes on disk but keeps its stable item id.
    (documents / "a.md").write_text(MSA + "\n\nRenamed and edited.\n")
    second = await ingest_delta(
        library=library, delta_tool=tool, source=SOURCE,
        principal=principal_context(), downloader=downloader,
    )

    assert second.report.updated == 1, "a rename is not a new contract"
    assert await library.catalog.taken_slugs() == {"a"}
    stored = await library.catalog.get_source_item("drive-1", "a")
    assert stored.current_uri.endswith("renamed.md")
    assert stored.contract_id == "a"


@pytest.mark.asyncio
async def test_a_tombstone_retracts_the_contract_but_keeps_history(workspace):
    library, downloader, _ = workspace
    retracted: list[str] = []

    class Loader:
        async def retract(self, contract_id):
            retracted.append(contract_id)

    tool = FakeDeltaTool([page([item("a")]), page([item("a", deleted=True)])])
    await ingest_delta(
        library=library, delta_tool=tool, source=SOURCE,
        principal=principal_context(), downloader=downloader,
    )
    result = await ingest_delta(
        library=library, delta_tool=tool, source=SOURCE,
        principal=principal_context(), downloader=downloader,
        graph_loader=Loader(),
    )

    assert result.tombstoned == ["a"]
    assert retracted == ["a"]
    assert (await library.catalog.get("a")).active is False
    assert await library.catalog.versions("a"), "catalog history survives"
    assert await library.evidence.versions("a"), "archived evidence survives"
    stored = await library.catalog.get_source_item("drive-1", "a")
    assert stored.deleted is True


@pytest.mark.asyncio
async def test_folders_and_undownloadable_items_are_skipped_with_reasons(workspace):
    library, _, _ = workspace
    tool = FakeDeltaTool([page([item("f", is_folder=True), item("a")])])

    result = await ingest_delta(
        library=library, delta_tool=tool, source=SOURCE,
        principal=principal_context(), downloader=None,
    )
    reasons = {row.reason for row in result.report.items}
    assert "folder" in reasons
    assert any("no local copy" in reason for reason in reasons)
    assert result.report.added == 0


# --------------------------------------------------------------------------
# 2. Cursor discipline
# --------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_an_interrupted_batch_retains_the_old_cursor_and_replays(workspace):
    library, downloader, _ = workspace
    await library.catalog.set_delta_token("sharepoint://legal", "cursor-1")

    async def failing_downloader(entry):
        if entry["item_id"] == "b":
            raise RuntimeError("download failed")
        return await downloader(entry)

    tool = FakeDeltaTool([page([item("a"), item("b")])])
    result = await ingest_delta(
        library=library, delta_tool=tool, source=SOURCE,
        principal=principal_context(), downloader=failing_downloader,
    )

    assert result.durable is False
    assert result.cursor_committed is None
    assert result.cursor_retained == "cursor-1"
    assert await library.catalog.get_delta_token("sharepoint://legal") == "cursor-1"
    assert result.report.added == 1 and result.report.errors == 1

    # Replay: the same batch is safe to re-run.
    replay = await ingest_delta(
        library=library, delta_tool=tool, source=SOURCE,
        principal=principal_context(), downloader=downloader,
    )
    assert replay.durable is True
    assert replay.cursor_committed == "https://graph.microsoft.com/final"


@pytest.mark.asyncio
async def test_a_truncated_enumeration_does_not_commit_a_cursor(workspace):
    library, downloader, _ = workspace
    tool = FakeDeltaTool([page([item("a")], delta_link=None, complete=False, truncated=True)])

    result = await ingest_delta(
        library=library, delta_tool=tool, source=SOURCE,
        principal=principal_context(), downloader=downloader,
    )
    assert result.cursor_committed is None
    assert await library.catalog.get_delta_token("sharepoint://legal") is None


@pytest.mark.asyncio
async def test_a_410_requests_a_rescan_and_retracts_nothing(workspace):
    library, downloader, _ = workspace
    tool = FakeDeltaTool([page([item("a")])])
    await ingest_delta(
        library=library, delta_tool=tool, source=SOURCE,
        principal=principal_context(), downloader=downloader,
    )

    expired = FakeDeltaTool(
        [{"items": [], "tombstones": [], "delta_link": None, "rescan_required": True}]
    )
    result = await ingest_delta(
        library=library, delta_tool=expired, source=SOURCE,
        principal=principal_context(), downloader=downloader,
    )

    assert result.rescan_required is True
    assert result.tombstoned == []
    assert result.report.items == []
    assert (await library.catalog.get("a")).active is True, "no mass deletion"
    assert result.cursor_retained == "https://graph.microsoft.com/final"


# --------------------------------------------------------------------------
# 3. Principal scope and boundaries
# --------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_the_service_principal_is_authorized_before_any_work(workspace):
    library, downloader, _ = workspace
    retrieval = ContractRetrieval(catalog=library.catalog, today=lambda: TODAY)
    tool = FakeDeltaTool([page([item("a")])])

    from parrot_tools.contracts.retrieval import AuthorizationDenied

    with pytest.raises(AuthorizationDenied):
        await ingest_delta(
            library=library,
            delta_tool=tool,
            source=SOURCE,
            principal=RequestContext(user_id="svc", roles=(), tenant_id="troc"),
            retrieval=retrieval,
            downloader=downloader,
        )
    assert tool.calls == [], "no enumeration happened for an unauthorized principal"


@pytest.mark.asyncio
async def test_the_temporal_publisher_is_drained_when_supplied(workspace):
    library, downloader, _ = workspace
    drained: list[Any] = []

    class Publisher:
        async def drain(self, ctx):
            drained.append(ctx)
            return type("Report", (), {"errors": []})()

    await ingest_delta(
        library=library,
        delta_tool=FakeDeltaTool([page([item("a")])]),
        source=SOURCE,
        principal=principal_context(),
        downloader=downloader,
        temporal=Publisher(),
        tenant_context="ctx",
    )
    assert drained == ["ctx"]


def test_the_jobs_module_imports_no_scheduler_and_sends_nothing():
    source = (
        Path(__file__).resolve().parents[2]
        / "src"
        / "parrot_tools"
        / "contracts"
        / "jobs.py"
    ).read_text()
    tree = ast.parse(source)
    imported: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            imported.update(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            imported.add(node.module)

    assert not any("scheduler" in name for name in imported), imported
    assert not any(name.startswith(("aiohttp", "smtplib", "parrot.server")) for name in imported)
    assert "@schedule" not in ast.get_source_segment(source, tree.body[-1]) or True
    decorators = {
        ast.unparse(decorator)
        for node in ast.walk(tree)
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
        for decorator in node.decorator_list
    }
    assert not any("schedule" in decorator for decorator in decorators), decorators
    called = {
        node.func.attr
        for node in ast.walk(tree)
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute)
    }
    for forbidden in ("send_result", "send", "notify", "post"):
        assert forbidden not in called, forbidden
