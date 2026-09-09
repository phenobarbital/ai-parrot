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
        for index, block in enumerate([block for block in markdown.split("\n#") if block.strip()]):
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
    assert await library.catalog.get_delta_token("sharepoint://legal") == ("https://graph.microsoft.com/final")
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
        library=library,
        delta_tool=tool,
        source=SOURCE,
        principal=principal_context(),
        downloader=downloader,
    )
    second = await ingest_delta(
        library=library,
        delta_tool=tool,
        source=SOURCE,
        principal=principal_context(),
        downloader=downloader,
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
        library=library,
        delta_tool=tool,
        source=SOURCE,
        principal=principal_context(),
        downloader=downloader,
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
        library=library,
        delta_tool=tool,
        source=SOURCE,
        principal=principal_context(),
        downloader=downloader,
    )
    # The file changes on disk but keeps its stable item id.
    (documents / "a.md").write_text(MSA + "\n\nRenamed and edited.\n")
    second = await ingest_delta(
        library=library,
        delta_tool=tool,
        source=SOURCE,
        principal=principal_context(),
        downloader=downloader,
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
        library=library,
        delta_tool=tool,
        source=SOURCE,
        principal=principal_context(),
        downloader=downloader,
    )
    result = await ingest_delta(
        library=library,
        delta_tool=tool,
        source=SOURCE,
        principal=principal_context(),
        downloader=downloader,
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
        library=library,
        delta_tool=tool,
        source=SOURCE,
        principal=principal_context(),
        downloader=None,
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
        library=library,
        delta_tool=tool,
        source=SOURCE,
        principal=principal_context(),
        downloader=failing_downloader,
    )

    assert result.durable is False
    assert result.cursor_committed is None
    assert result.cursor_retained == "cursor-1"
    assert await library.catalog.get_delta_token("sharepoint://legal") == "cursor-1"
    assert result.report.added == 1 and result.report.errors == 1

    # Replay: the same batch is safe to re-run.
    replay = await ingest_delta(
        library=library,
        delta_tool=tool,
        source=SOURCE,
        principal=principal_context(),
        downloader=downloader,
    )
    assert replay.durable is True
    assert replay.cursor_committed == "https://graph.microsoft.com/final"


@pytest.mark.asyncio
async def test_a_truncated_enumeration_does_not_commit_a_cursor(workspace):
    library, downloader, _ = workspace
    tool = FakeDeltaTool([page([item("a")], delta_link=None, complete=False, truncated=True)])

    result = await ingest_delta(
        library=library,
        delta_tool=tool,
        source=SOURCE,
        principal=principal_context(),
        downloader=downloader,
    )
    assert result.cursor_committed is None
    assert await library.catalog.get_delta_token("sharepoint://legal") is None


@pytest.mark.asyncio
async def test_a_410_requests_a_rescan_and_retracts_nothing(workspace):
    library, downloader, _ = workspace
    tool = FakeDeltaTool([page([item("a")])])
    await ingest_delta(
        library=library,
        delta_tool=tool,
        source=SOURCE,
        principal=principal_context(),
        downloader=downloader,
    )

    expired = FakeDeltaTool([{"items": [], "tombstones": [], "delta_link": None, "rescan_required": True}])
    result = await ingest_delta(
        library=library,
        delta_tool=expired,
        source=SOURCE,
        principal=principal_context(),
        downloader=downloader,
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
    source = (Path(__file__).resolve().parents[2] / "src" / "parrot_tools" / "contracts" / "jobs.py").read_text()
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
        node.func.attr for node in ast.walk(tree) if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute)
    }
    for forbidden in ("send_result", "send", "notify", "post"):
        assert forbidden not in called, forbidden


@pytest.mark.asyncio
async def test_omitting_the_retrieval_gate_does_not_skip_authorization(workspace):
    """A missing argument must never widen access.

    ``retrieval`` selects *which* gate authorizes the principal; it does
    not decide *whether* one does. Omitting it previously ran the whole
    job — including the tombstone retractions — with no authorization at
    all, so a caller could bypass the gate by leaving out a keyword.
    """
    library, downloader, _ = workspace
    tool = FakeDeltaTool([page([item("a")])])

    from parrot_tools.contracts.retrieval import AuthorizationDenied

    with pytest.raises(AuthorizationDenied):
        await ingest_delta(
            library=library,
            delta_tool=tool,
            source=SOURCE,
            principal=RequestContext(user_id="svc", roles=(), tenant_id="troc"),
            downloader=downloader,
        )

    # Nothing was ingested and the cursor did not move.
    assert await library.catalog.get_delta_token("sharepoint://legal") is None


# --------------------------------------------------------------------------
# Driving a real O365 delta tool, and recovering an expired cursor
# --------------------------------------------------------------------------


#: A whole-drive source. Absence from a complete rescan is only evidence of
#: deletion when the listing covers everything we hold, which a folder-scoped
#: rescan never does.
UNSCOPED = SourceConfig(source="sharepoint://drive", drive_id="drive-1")


class ScriptedDeltaTool:
    """A delta tool whose successive calls return scripted payloads.

    Unlike ``FakeDeltaTool`` this replays a *finite* script and records the
    cursor each call was made with, so a re-enumeration is observable.
    """

    def __init__(self, pages: list[dict[str, Any]]) -> None:
        self.pages = list(pages)
        self.calls: list[dict[str, Any]] = []

    async def enumerate(self, **kwargs):
        self.calls.append(kwargs)
        return self.pages[min(len(self.calls) - 1, len(self.pages) - 1)]


@pytest.mark.asyncio
async def test_a_real_o365_delta_tool_can_actually_be_driven(workspace):
    """The job must drive a real tool through its authenticated surface.

    Regression: `_enumerate` used to read `delta_tool.client`, which no
    `O365Tool` has, and call `_execute_graph_operation(None, ...)` — that
    crashed on `None.graph_client` and skipped authentication entirely. The
    job's other tests never caught it because their doubles expose
    `enumerate()` and take the other branch.
    """
    from unittest.mock import AsyncMock

    from parrot_tools.o365 import DeltaOneDriveFilesTool

    library, downloader, _ = workspace

    class FakeDeltaBuilder:
        def __init__(self, graph):
            self._graph = graph

        def with_url(self, raw_url):
            return self

        async def get(self):
            self._graph.delta_calls += 1
            return type(
                "Resp",
                (),
                {
                    "value": [
                        type(
                            "Item",
                            (),
                            {
                                "id": "a",
                                "name": "a.md",
                                "deleted": None,
                                "folder": None,
                                "file": None,
                                "size": 1,
                                "e_tag": None,
                                "c_tag": None,
                                "web_url": "https://graph.microsoft.com/legal/a.md",
                                "last_modified_date_time": None,
                                "parent_reference": type(
                                    "P", (), {"id": "folder-x", "drive_id": "drive-1", "path": None}
                                )(),
                            },
                        )()
                    ],
                    "odata_next_link": None,
                    "odata_delta_link": ("https://graph.microsoft.com/v1.0/drives/drive-1/items/root/delta?token=z"),
                },
            )()

    class FakeGraph:
        def __init__(self):
            self.delta_calls = 0

        @property
        def drives(self):
            graph = self

            class Drives:
                def by_drive_id(self, drive_id):
                    class Drive:
                        @property
                        def items(self):
                            class Items:
                                def by_drive_item_id(self, item_id):
                                    class Item:
                                        @property
                                        def delta(self):
                                            return FakeDeltaBuilder(graph)

                                        async def get(self):
                                            # folder-path resolution
                                            return type("F", (), {"id": "folder-x"})()

                                    return Item()

                            return Items()

                    return Drive()

            return Drives()

    graph = FakeGraph()
    client = type("C", (), {"graph_client": graph})()

    tool = DeltaOneDriveFilesTool(credentials={"client_id": "x", "tenant_id": "y"})
    # Authentication is the step the old code skipped; assert it is used.
    get_client = AsyncMock(return_value=client)
    tool._get_client = get_client

    result = await ingest_delta(
        library=library,
        delta_tool=tool,
        source=SOURCE,
        principal=principal_context(),
        downloader=downloader,
    )

    get_client.assert_awaited()  # the tool authenticated
    assert graph.delta_calls == 1
    assert result.errors == [], result.errors
    assert result.cursor_committed is not None
    # ...and the item actually made it through, not just the plumbing.
    assert [row.source_uri for row in result.report.items] == ["https://graph.microsoft.com/legal/a.md"]
    stored = await library.catalog.list_source_items("sharepoint://legal")
    assert [entry.item_id for entry in stored] == ["a"]


@pytest.mark.asyncio
async def test_a_tool_reporting_an_error_retains_the_cursor(workspace):
    """A failed enumeration is not an empty one — never advance past it."""
    library, downloader, _ = workspace

    class FailingTool:
        async def run(self, **kwargs):
            return type("R", (), {"status": "error", "error": "Graph is down", "result": None})()

    await library.catalog.set_delta_token("sharepoint://legal", "cursor-1")

    result = await ingest_delta(
        library=library,
        delta_tool=FailingTool(),
        source=SOURCE,
        principal=principal_context(),
        downloader=downloader,
    )

    assert result.cursor_committed is None
    assert result.cursor_retained == "cursor-1"
    assert any("Graph is down" in err for err in result.errors)
    assert await library.catalog.get_delta_token("sharepoint://legal") == "cursor-1"


@pytest.mark.asyncio
async def test_an_expired_cursor_is_recovered_by_re_enumerating(workspace):
    """A tool that only *signals* the expiry must not stall the source.

    Retaining the dead cursor means every subsequent run hits the same 410,
    so ingestion never progresses again.
    """
    library, downloader, _ = workspace
    await library.catalog.set_delta_token("sharepoint://legal", "dead-cursor")

    tool = ScriptedDeltaTool(
        [
            {"items": [], "tombstones": [], "delta_link": None, "rescan_required": True},
            page([item("a")]),
        ]
    )

    result = await ingest_delta(
        library=library,
        delta_tool=tool,
        source=SOURCE,
        principal=principal_context(),
        downloader=downloader,
    )

    assert [call["delta_token"] for call in tool.calls] == ["dead-cursor", None]
    assert result.rescan_performed is True
    assert result.rescan_required is False
    assert result.cursor_committed == "https://graph.microsoft.com/final"


@pytest.mark.asyncio
async def test_a_recovered_rescan_retracts_what_vanished_meanwhile(workspace):
    """The whole point of reconciling after a reset.

    A document deleted while the cursor was expired appears in no delta
    page — the tombstone was consumed by the dead cursor. Only comparing the
    complete rescan against local state can retract it.
    """
    library, downloader, _ = workspace

    first = ScriptedDeltaTool([page([item("a"), item("b")])])
    await ingest_delta(
        library=library,
        delta_tool=first,
        source=UNSCOPED,
        principal=principal_context(),
        downloader=downloader,
    )
    card_b = await library.catalog.list_source_items("sharepoint://drive")
    b_contract = next(entry.contract_id for entry in card_b if entry.item_id == "b")
    assert (await library.catalog.get(b_contract)).active is True

    # "b" was deleted while the cursor was expired: the rescan lists only "a".
    expired = ScriptedDeltaTool(
        [
            {"items": [], "tombstones": [], "delta_link": None, "rescan_required": True},
            page([item("a")]),
        ]
    )
    result = await ingest_delta(
        library=library,
        delta_tool=expired,
        source=UNSCOPED,
        principal=principal_context(),
        downloader=downloader,
    )

    assert result.rescan_performed is True
    assert b_contract in result.reconciled
    assert (await library.catalog.get(b_contract)).active is False
    # "a" is untouched.
    a_contract = next(entry.contract_id for entry in card_b if entry.item_id == "a")
    assert (await library.catalog.get(a_contract)).active is True


@pytest.mark.asyncio
async def test_an_incomplete_rescan_never_retracts_anything(workspace):
    """A partial listing must never be read as mass deletion."""
    library, downloader, _ = workspace

    first = ScriptedDeltaTool([page([item("a"), item("b")])])
    await ingest_delta(
        library=library,
        delta_tool=first,
        source=UNSCOPED,
        principal=principal_context(),
        downloader=downloader,
    )
    known = await library.catalog.list_source_items("sharepoint://drive")
    contracts = [entry.contract_id for entry in known if entry.contract_id]

    truncated = ScriptedDeltaTool(
        [
            {"items": [], "tombstones": [], "delta_link": None, "rescan_required": True},
            # No final cursor: the walk never finished.
            page([], delta_link=None),
        ]
    )
    result = await ingest_delta(
        library=library,
        delta_tool=truncated,
        source=UNSCOPED,
        principal=principal_context(),
        downloader=downloader,
    )

    assert result.rescan_performed is True
    assert result.reconciled == []
    assert result.tombstoned == []
    for contract_id in contracts:
        assert (await library.catalog.get(contract_id)).active is True, "no mass deletion"


@pytest.mark.asyncio
async def test_a_first_run_rescan_has_nothing_to_reconcile(workspace):
    """With no committed cursor there is no local state to compare against."""
    library, downloader, _ = workspace

    from parrot.knowledge.contracts.models import SourceItem

    # A row left behind by an interrupted earlier run: present locally, absent
    # from the rescan, but with no committed cursor there is nothing to
    # reconcile *against* — the guard must leave it alone.
    await library.catalog.upsert_source_item(
        SourceItem(
            source="sharepoint://drive",
            drive_id="drive-1",
            item_id="orphan",
            current_uri="https://graph.microsoft.com/legal/orphan.md",
            contract_id="orphan-contract",
        )
    )

    tool = ScriptedDeltaTool(
        [
            {"items": [], "tombstones": [], "delta_link": None, "rescan_required": True},
            page([item("a")]),
        ]
    )
    result = await ingest_delta(
        library=library,
        delta_tool=tool,
        source=UNSCOPED,
        principal=principal_context(),
        downloader=downloader,
    )

    assert await library.catalog.get_delta_token("sharepoint://drive") is not None
    assert result.reconciled == []
    assert result.tombstoned == []
    assert result.cursor_committed == "https://graph.microsoft.com/final"


@pytest.mark.asyncio
async def test_a_tool_that_recovered_the_410_itself_is_also_reconciled(workspace):
    """Some tools rescan internally and report `reset_performed`."""
    library, downloader, _ = workspace

    first = ScriptedDeltaTool([page([item("a"), item("b")])])
    await ingest_delta(
        library=library,
        delta_tool=first,
        source=UNSCOPED,
        principal=principal_context(),
        downloader=downloader,
    )
    known = await library.catalog.list_source_items("sharepoint://drive")
    b_contract = next(e.contract_id for e in known if e.item_id == "b")

    self_healing = ScriptedDeltaTool([page([item("a")], reset_performed=True)])
    result = await ingest_delta(
        library=library,
        delta_tool=self_healing,
        source=UNSCOPED,
        principal=principal_context(),
        downloader=downloader,
    )

    assert len(self_healing.calls) == 1  # it did not need a second call
    assert result.rescan_performed is True
    assert b_contract in result.reconciled


@pytest.mark.asyncio
async def test_source_config_can_carry_the_exact_folder_id(workspace):
    """folder_id is forwarded when set, so scoping need not guess."""
    library, downloader, _ = workspace
    tool = ScriptedDeltaTool([page([item("a")])])
    scoped = SourceConfig(
        source="sharepoint://legal",
        drive_id="drive-1",
        folder_path="legal",
        folder_id="folder-x",
    )

    await ingest_delta(
        library=library,
        delta_tool=tool,
        source=scoped,
        principal=principal_context(),
        downloader=downloader,
    )

    assert tool.calls[0]["folder_id"] == "folder-x"
    # Absent from the config -> not sent at all, so third-party tools that
    # do not accept the argument are unaffected.
    plain = ScriptedDeltaTool([page([item("a")])])
    await ingest_delta(
        library=library,
        delta_tool=plain,
        source=SOURCE,
        principal=principal_context(),
        downloader=downloader,
    )
    assert "folder_id" not in plain.calls[0]


# --------------------------------------------------------------------------
# Reconciliation must never withdraw a contract on weak evidence
# --------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_a_folder_scoped_rescan_reports_instead_of_retracting(workspace):
    """A folder-scoped listing only ever sees part of the drive.

    An item outside the folder is absent for reasons that have nothing to do
    with deletion, so absence is not evidence and must not withdraw a
    contract. It is reported for an operator instead.
    """
    library, downloader, _ = workspace

    first = ScriptedDeltaTool([page([item("a"), item("b")])])
    await ingest_delta(
        library=library,
        delta_tool=first,
        source=SOURCE,  # folder_path="legal"
        principal=principal_context(),
        downloader=downloader,
    )
    known = await library.catalog.list_source_items("sharepoint://legal")
    contracts = [e.contract_id for e in known if e.contract_id]

    narrowed = ScriptedDeltaTool(
        [
            {"items": [], "tombstones": [], "delta_link": None, "rescan_required": True},
            page([item("a")]),
        ]
    )
    result = await ingest_delta(
        library=library,
        delta_tool=narrowed,
        source=SOURCE,
        principal=principal_context(),
        downloader=downloader,
    )

    assert result.rescan_performed is True
    assert result.reconciled == []
    assert result.tombstoned == []
    assert result.suspected_deletions == ["b"]
    for contract_id in contracts:
        assert (await library.catalog.get(contract_id)).active is True


@pytest.mark.asyncio
async def test_a_rescan_of_one_drive_never_retracts_another_drive(workspace):
    """One source name may span drives; a rescan of one says nothing about the rest."""
    library, downloader, _ = workspace

    first = ScriptedDeltaTool([page([item("a"), item("b", drive_id="drive-2")])])
    await ingest_delta(
        library=library,
        delta_tool=first,
        source=UNSCOPED,  # drive-1
        principal=principal_context(),
        downloader=downloader,
    )
    known = await library.catalog.list_source_items("sharepoint://drive")
    other_drive = next(e for e in known if e.drive_id == "drive-2")
    assert (await library.catalog.get(other_drive.contract_id)).active is True

    rescan = ScriptedDeltaTool(
        [
            {"items": [], "tombstones": [], "delta_link": None, "rescan_required": True},
            page([item("a")]),
        ]
    )
    result = await ingest_delta(
        library=library,
        delta_tool=rescan,
        source=UNSCOPED,
        principal=principal_context(),
        downloader=downloader,
    )

    assert result.reconciled == []
    assert (await library.catalog.get(other_drive.contract_id)).active is True


@pytest.mark.asyncio
async def test_a_contract_backed_by_another_live_file_is_not_retracted(workspace):
    """Identical files deduplicate onto one card.

    One of them disappearing does not mean the contract is gone.
    """
    library, downloader, _documents = workspace
    from parrot.knowledge.contracts.models import SourceItem

    first = ScriptedDeltaTool([page([item("a")])])
    await ingest_delta(
        library=library,
        delta_tool=first,
        source=UNSCOPED,
        principal=principal_context(),
        downloader=downloader,
    )
    known = await library.catalog.list_source_items("sharepoint://drive")
    shared = next(e.contract_id for e in known if e.item_id == "a")

    # A second file that deduplicated onto the same card. Built directly so
    # the test pins THIS guard rather than the library's dedup heuristics.
    await library.catalog.upsert_source_item(
        SourceItem(
            source="sharepoint://drive",
            drive_id="drive-1",
            item_id="b",
            current_uri="https://graph.microsoft.com/legal/b.md",
            contract_id=shared,
        )
    )

    # "b" vanishes from the rescan; "a" still backs the card.
    rescan = ScriptedDeltaTool(
        [
            {"items": [], "tombstones": [], "delta_link": None, "rescan_required": True},
            page([item("a")]),
        ]
    )
    result = await ingest_delta(
        library=library,
        delta_tool=rescan,
        source=UNSCOPED,
        principal=principal_context(),
        downloader=downloader,
    )

    assert result.reconciled == []
    assert result.tombstoned == []
    assert (await library.catalog.get(shared)).active is True, "still backed by 'a'"


@pytest.mark.asyncio
async def test_an_error_shaped_dict_payload_never_reconciles(workspace):
    """A dict carrying an error must not pass as a successful empty scan."""
    library, downloader, _ = workspace

    first = ScriptedDeltaTool([page([item("a"), item("b")])])
    await ingest_delta(
        library=library,
        delta_tool=first,
        source=UNSCOPED,
        principal=principal_context(),
        downloader=downloader,
    )
    known = await library.catalog.list_source_items("sharepoint://drive")
    contracts = [e.contract_id for e in known if e.contract_id]

    poisoned = ScriptedDeltaTool(
        [
            {
                "status": "error",
                "error": "Graph refused",
                "items": [],
                "tombstones": [],
                "delta_link": "https://graph.microsoft.com/final",
                "complete": True,
                "reset_performed": True,
            }
        ]
    )
    result = await ingest_delta(
        library=library,
        delta_tool=poisoned,
        source=UNSCOPED,
        principal=principal_context(),
        downloader=downloader,
    )

    assert result.reconciled == []
    assert result.cursor_committed is None
    assert any("Graph refused" in err for err in result.errors)
    for contract_id in contracts:
        assert (await library.catalog.get(contract_id)).active is True


@pytest.mark.asyncio
async def test_a_rescan_without_a_final_cursor_never_reconciles(workspace):
    """`complete` without the cursor that proves it is not proof."""
    library, downloader, _ = workspace

    first = ScriptedDeltaTool([page([item("a"), item("b")])])
    await ingest_delta(
        library=library,
        delta_tool=first,
        source=UNSCOPED,
        principal=principal_context(),
        downloader=downloader,
    )
    known = await library.catalog.list_source_items("sharepoint://drive")
    contracts = [e.contract_id for e in known if e.contract_id]

    liar = ScriptedDeltaTool(
        [
            {
                "items": [],
                "tombstones": [],
                "delta_link": None,
                "complete": True,
                "reset_performed": True,
            }
        ]
    )
    result = await ingest_delta(
        library=library,
        delta_tool=liar,
        source=UNSCOPED,
        principal=principal_context(),
        downloader=downloader,
    )

    assert result.reconciled == []
    for contract_id in contracts:
        assert (await library.catalog.get(contract_id)).active is True


@pytest.mark.asyncio
async def test_an_item_written_after_the_snapshot_is_not_retracted(workspace):
    """A concurrent run's write must not look like an absence."""
    library, downloader, _ = workspace
    from datetime import timedelta

    from parrot.knowledge.contracts.models import SourceItem

    first = ScriptedDeltaTool([page([item("a"), item("b")])])
    await ingest_delta(
        library=library,
        delta_tool=first,
        source=UNSCOPED,
        principal=principal_context(),
        downloader=downloader,
    )
    known = await library.catalog.list_source_items("sharepoint://drive")
    b_entry = next(e for e in known if e.item_id == "b")

    # Simulate another run touching "b" *after* our enumeration begins.
    await library.catalog.upsert_source_item(
        SourceItem(
            source="sharepoint://drive",
            drive_id=b_entry.drive_id,
            item_id="b",
            current_uri=b_entry.current_uri,
            contract_id=b_entry.contract_id,
            last_seen_at=datetime.now(timezone.utc) + timedelta(hours=1),
        )
    )

    rescan = ScriptedDeltaTool(
        [
            {"items": [], "tombstones": [], "delta_link": None, "rescan_required": True},
            page([item("a")]),
        ]
    )
    result = await ingest_delta(
        library=library,
        delta_tool=rescan,
        source=UNSCOPED,
        principal=principal_context(),
        downloader=downloader,
    )

    assert result.reconciled == []
    assert (await library.catalog.get(b_entry.contract_id)).active is True


@pytest.mark.asyncio
async def test_a_rescan_with_item_errors_never_reconciles(workspace):
    """A gap caused by a failure is not evidence of deletion."""
    library, _downloader, _documents = workspace

    good = ScriptedDeltaTool([page([item("a"), item("b")])])

    # First run with a working downloader to establish state.
    _lib, working_downloader, _docs = workspace
    await ingest_delta(
        library=library,
        delta_tool=good,
        source=UNSCOPED,
        principal=principal_context(),
        downloader=working_downloader,
    )
    known = await library.catalog.list_source_items("sharepoint://drive")
    contracts = [e.contract_id for e in known if e.contract_id]

    async def failing(entry):
        raise RuntimeError("download failed")

    rescan = ScriptedDeltaTool(
        [
            {"items": [], "tombstones": [], "delta_link": None, "rescan_required": True},
            page([item("a")]),
        ]
    )
    result = await ingest_delta(
        library=library,
        delta_tool=rescan,
        source=UNSCOPED,
        principal=principal_context(),
        downloader=failing,
    )

    assert result.durable is False
    assert result.reconciled == []
    assert result.cursor_committed is None
    for contract_id in contracts:
        assert (await library.catalog.get(contract_id)).active is True


@pytest.mark.asyncio
async def test_a_contract_backed_by_a_live_file_in_another_source_survives(workspace):
    """Dedup crosses source boundaries, so the reference check must too.

    Identical bytes ingested under a *different* `SourceConfig` share one
    card. Reconciling this source must not withdraw a contract that another
    source's still-live file backs.
    """
    library, downloader, _ = workspace
    from parrot.knowledge.contracts.models import SourceItem

    first = ScriptedDeltaTool([page([item("a")])])
    await ingest_delta(
        library=library,
        delta_tool=first,
        source=UNSCOPED,
        principal=principal_context(),
        downloader=downloader,
    )
    known = await library.catalog.list_source_items("sharepoint://drive")
    shared = next(e.contract_id for e in known if e.item_id == "a")

    # The same card, reached through a completely different configured source.
    await library.catalog.upsert_source_item(
        SourceItem(
            source="sharepoint://archive",
            drive_id="drive-9",
            item_id="mirror",
            current_uri="https://graph.microsoft.com/archive/a.md",
            contract_id=shared,
        )
    )

    # "a" disappears from this source's rescan.
    rescan = ScriptedDeltaTool(
        [
            {"items": [], "tombstones": [], "delta_link": None, "rescan_required": True},
            page([]),
        ]
    )
    result = await ingest_delta(
        library=library,
        delta_tool=rescan,
        source=UNSCOPED,
        principal=principal_context(),
        downloader=downloader,
    )

    assert result.reconciled == []
    assert result.tombstoned == []
    assert (await library.catalog.get(shared)).active is True, "still backed by a live file in sharepoint://archive"


@pytest.mark.asyncio
async def test_a_failed_recovery_reports_the_expiry_as_unrecovered(workspace):
    """If the re-enumeration itself fails, the cursor really is stuck."""
    library, downloader, _ = workspace
    await library.catalog.set_delta_token("sharepoint://drive", "dead-cursor")

    class ExpiredThenBroken:
        def __init__(self):
            self.calls = 0

        async def enumerate(self, **kwargs):
            self.calls += 1
            if self.calls == 1:
                return {
                    "items": [],
                    "tombstones": [],
                    "delta_link": None,
                    "rescan_required": True,
                }
            return {"status": "error", "error": "Graph refused the rescan"}

    tool = ExpiredThenBroken()
    result = await ingest_delta(
        library=library,
        delta_tool=tool,
        source=UNSCOPED,
        principal=principal_context(),
        downloader=downloader,
    )

    assert tool.calls == 2
    assert result.rescan_required is True, "the expiry was not recovered"
    assert result.rescan_performed is False
    assert result.cursor_retained == "dead-cursor"
    assert any("Graph refused the rescan" in err for err in result.errors)
