"""Golden tool surfaces for local and server wiki MCP modes (FEAT-569)."""

from __future__ import annotations

import pytest

pytest.importorskip("parrot.mcp.transports.streamable_http")

from parrot.knowledge.wiki.mcp_server import build_wiki_tools, create_wiki_mcp_server
from parrot.knowledge.wiki.project import WikiProjectConfig, load_effective_config, save_project_config
from parrot.knowledge.wiki.store import WikiPageRecord, create_wiki_store

LOCAL_NO_LEDGER = sorted(
    [
        "wiki_query",
        "wiki_page",
        "wiki_related",
        "wiki_remember",
        "wiki_note",
        "wiki_status",
        "wiki_symbol_lookup",
        "wiki_code_outline",
        "wiki_blast_radius",
        "wiki_decision_why",
        "wiki_decisions_for_symbol",
        "wiki_lint",
        "wiki_standup",
    ]
)
LEDGER = sorted(["ledger_open", "ledger_ready", "ledger_claim", "ledger_close", "ledger_context"])
BULK = sorted(["wiki_page_hashes", "wiki_ingest_batch", "wiki_sync_push", "wiki_sync_pull"])


@pytest.fixture
def repo(tmp_path):
    """Create a configured SQLite wiki without a git root or ledger."""
    (tmp_path / ".parrot").mkdir()
    config = WikiProjectConfig(wiki_name="golden")
    save_project_config(tmp_path, config)
    store = create_wiki_store(config.storage_path(tmp_path), wiki_name="golden", backend="sqlite")
    import asyncio

    asyncio.run(store.upsert_pages([WikiPageRecord(concept_id="c", title="c", body="body")]))
    return tmp_path


def test_local_stdio_surface(repo):
    """Local stdio intentionally excludes server-only bulk and ledger tools."""
    assert sorted(create_wiki_mcp_server(repo).tools) == LOCAL_NO_LEDGER


def test_server_surface(repo):
    """Server bundles expose the frozen local, ledger, and bulk inventories."""
    bundle = build_wiki_tools(
        repo,
        load_effective_config(repo).config,
        ledger_dir=repo / ".parrot" / "ledger",
        read_repair=False,
        include_bulk_tools=True,
    )
    assert sorted(tool.name for tool in bundle.tools) == sorted(LOCAL_NO_LEDGER + LEDGER + BULK)
