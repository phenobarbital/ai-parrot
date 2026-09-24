from pathlib import Path

import pytest

from parrot.knowledge.wiki.federation import FederatedWikiStore, NamespaceHandle
from parrot.knowledge.wiki.mcp_server import create_wiki_mcp_server
from parrot.knowledge.wiki.project import WikiNamespaceConfig, WikiProjectConfig, save_project_config
from parrot.knowledge.wiki.schema.store import SchemaStore
from parrot.knowledge.wiki.store import SQLiteWikiStore, WikiPageRecord, create_wiki_store


BASE_TOOLS = {
    "wiki_query",
    "wiki_page",
    "wiki_related",
    "wiki_remember",
    "wiki_note",
    "wiki_status",
    "wiki_symbol_lookup",
    "wiki_code_outline",
    "wiki_blast_radius",
    "wiki_decisions_for_symbol",
    "wiki_decision_why",
}


def _save_project(root: Path, *, git_backed: bool = False) -> WikiProjectConfig:
    """Create a minimal wiki project configuration."""
    if git_backed:
        (root / ".git").mkdir()
    config = WikiProjectConfig(wiki_name="mount-test")
    save_project_config(root, config)
    return config


def _initialize_local_store(root: Path, config: WikiProjectConfig) -> None:
    """Create the local wiki directory used by the MCP server."""
    config.storage_path(root).mkdir(parents=True, exist_ok=True)
    create_wiki_store(config.storage_path(root), wiki_name=config.wiki_name, backend=config.backend)


def test_no_schema_plane_keeps_tool_surface_unchanged(tmp_path: Path) -> None:
    """A bare project does not create or expose the optional schema plane."""
    config = _save_project(tmp_path)
    _initialize_local_store(tmp_path, config)

    server = create_wiki_mcp_server(tmp_path)

    assert set(server.tools) == BASE_TOOLS
    assert not any(name.startswith("wiki_schema_") for name in server.tools)
    assert not (tmp_path / ".parrot" / "schema").exists()


def test_schema_plane_mounts_handle_and_four_tools(tmp_path: Path) -> None:
    """An existing schema plane is mounted read-only and contributes four tools."""
    config = _save_project(tmp_path, git_backed=True)
    _initialize_local_store(tmp_path, config)
    schema_dir = config.schema_path(tmp_path)
    schema_dir.mkdir(parents=True)
    SchemaStore(schema_dir / "schema.db")

    server = create_wiki_mcp_server(tmp_path)

    assert {name for name in server.tools if name.startswith("wiki_schema_")} == {
        "wiki_schema_lookup",
        "wiki_schema_search",
        "wiki_schema_neighbors",
        "wiki_schema_sources",
    }
    assert len([name for name in server.tools if name.startswith("wiki_schema_")]) == 4
    read_store = server.tools["wiki_query"].tool._store
    assert isinstance(read_store, FederatedWikiStore)
    assert read_store.namespaces["schema"].read_only is True
    assert read_store.namespaces["schema"].config.overlay_prefixes == ["source", "schema", "table"]


@pytest.mark.asyncio
async def test_two_overlays_cross_kind_neighbors() -> None:
    """Schema and ledger overlays hydrate cross-kind references in both directions."""
    from tempfile import TemporaryDirectory

    with TemporaryDirectory() as directory:
        root = Path(directory)
        local = SQLiteWikiStore(root / "wiki.db", wiki_name="w")
        await local.upsert_pages([WikiPageRecord(concept_id="sym:m.py#Model", title="Model", category="symbol")])
        await local.add_edges([("sym:m.py#Model", "table:x/a.b", "maps_to")])

        schema = SchemaStore(root / "schema.db")
        await schema.upsert_pages(
            [
                WikiPageRecord(concept_id="table:x/a.b", title="a.b", category="table"),
                WikiPageRecord(concept_id="table:x/a.c", title="a.c", category="table"),
            ]
        )
        await schema.add_edges([("table:x/a.b", "table:x/a.c", "references")])

        ledger = SQLiteWikiStore(root / "ledger.db", wiki_name="ledger")
        handles = [
            NamespaceHandle(
                name="ledger",
                store=ledger,
                config=WikiNamespaceConfig(store=str(root), overlay_prefixes=["issue"]),
                origin="repo",
                storage_dir=root,
                read_only=True,
            ),
            NamespaceHandle(
                name="schema",
                store=schema,
                config=WikiNamespaceConfig(store=str(root), overlay_prefixes=["source", "schema", "table"]),
                origin="repo",
                storage_dir=root,
                read_only=True,
            ),
        ]
        federated = FederatedWikiStore(local, "w", handles, [])

        from_symbol = await federated.neighbors("sym:m.py#Model")
        from_table = await federated.neighbors("table:x/a.b")

        assert any(row["concept_id"].endswith("table:x/a.b") for row in from_symbol)
        assert any(row["concept_id"].endswith("sym:m.py#Model") for row in from_table)
