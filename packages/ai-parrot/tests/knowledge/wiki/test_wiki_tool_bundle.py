"""Tests for wiki MCP tool-bundle assembly (FEAT-569)."""

import asyncio
from pathlib import Path
from typing import Any

import pytest

from parrot.knowledge.wiki import mcp_server
from parrot.knowledge.wiki.mcp_server import (
    WikiToolBundle,
    abuild_wiki_tools,
    build_wiki_tools,
    close_bundle,
    create_wiki_mcp_server,
)
from parrot.knowledge.wiki.project import WikiProjectConfig, load_effective_config, save_project_config
from parrot.knowledge.wiki.store import WikiPageRecord, create_wiki_store

BASE = {
    "wiki_query",
    "wiki_page",
    "wiki_related",
    "wiki_remember",
    "wiki_note",
    "wiki_status",
    "wiki_symbol_lookup",
    "wiki_code_outline",
    "wiki_blast_radius",
}
BULK = {"wiki_page_hashes", "wiki_ingest_batch", "wiki_sync_push", "wiki_sync_pull"}


@pytest.fixture
def repo(tmp_path: Path) -> Path:
    """Create a built, minimal wiki repository."""
    config = WikiProjectConfig(wiki_name="t")
    (tmp_path / ".parrot").mkdir()
    save_project_config(tmp_path, config)
    store = create_wiki_store(config.storage_path(tmp_path), wiki_name="t", backend="sqlite")
    asyncio.run(store.upsert_pages([WikiPageRecord(concept_id="c", title="c", body="b")]))
    return tmp_path


def test_parity_and_flags(repo: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Keep stdio tools stable while enabling the server-only flags."""
    server = create_wiki_mcp_server(repo)
    assert BASE <= set(server.tools)
    assert not BULK & set(server.tools)

    from parrot.knowledge.wiki import project

    config = load_effective_config(repo).config
    monkeypatch.setattr(
        project,
        "find_shared_root",
        lambda root: (_ for _ in ()).throw(AssertionError("unexpected root discovery")),
    )
    bundle = build_wiki_tools(
        repo,
        config,
        include_bulk_tools=True,
        read_repair=False,
        ledger_dir=repo / "srv" / ".parrot" / "ledger",
    )
    assert BULK <= {tool.name for tool in bundle.tools}
    assert bundle.ledger_service.shared_root == (repo / "srv").resolve()
    structural_tool = next(tool for tool in bundle.tools if tool.name == "wiki_symbol_lookup")
    assert structural_tool._service_factory(None)._read_repair is False


async def test_async_builder_no_transient_loop(repo: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Use the serving loop directly instead of the stdio sync helper."""
    monkeypatch.setattr(
        mcp_server,
        "_run_sync",
        lambda coro: (_ for _ in ()).throw(AssertionError("transient loop")),
    )
    bundle = await abuild_wiki_tools(repo, load_effective_config(repo).config)
    await close_bundle(bundle)


async def test_close_bundle_closes_available_stores() -> None:
    """Close asynchronous stores and tolerate stores without close methods."""
    closed: list[str] = []

    class AsyncStore:
        """Record asynchronous close calls."""

        async def close(self) -> None:
            closed.append("async")

    class SyncStore:
        """Record synchronous close calls."""

        def close(self) -> None:
            closed.append("sync")

    class Handle:
        """Minimal namespace handle for lifecycle testing."""

        def __init__(self, store: Any) -> None:
            self.store = store

    class Ledger:
        """Minimal ledger service for lifecycle testing."""

        def __init__(self, store: Any) -> None:
            self.store = store

    bundle = WikiToolBundle(
        tools=[],
        vault_tools=[],
        description="test",
        store=AsyncStore(),
        read_store=object(),
        ledger_service=Ledger(SyncStore()),
        namespace_handles=[Handle(object())],
    )
    await close_bundle(bundle)
    assert closed == ["async", "sync"]
