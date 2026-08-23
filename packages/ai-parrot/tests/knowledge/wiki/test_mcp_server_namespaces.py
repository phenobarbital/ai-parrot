"""Tests: federated namespaces reach the wikitoolkit MCP server (FEAT-450).

``create_wiki_mcp_server`` resolves the project's declared namespaces and
injects one ``FederatedWikiStore`` into ``create_wiki_tools``, so the
``wiki_*`` tools become namespace-aware without any per-tool wiring.
"""

from pathlib import Path

import pytest
from parrot.knowledge.wiki.federation import FederatedWikiStore
from parrot.knowledge.wiki.mcp_server import create_wiki_mcp_server
from parrot.knowledge.wiki.project import (
    WikiNamespaceConfig,
    WikiProjectConfig,
    save_project_config,
)
from parrot.knowledge.wiki.store import WikiPageRecord, create_wiki_store

BASE_TOOLS = {
    "wiki_query", "wiki_page", "wiki_related",
    "wiki_remember", "wiki_note", "wiki_status",
}


async def _seed(root: Path, config: WikiProjectConfig, concept_id: str) -> None:
    """Build a one-page plane for ``root``."""
    save_project_config(root, config)
    storage = config.storage_path(root)
    storage.mkdir(parents=True, exist_ok=True)
    store = create_wiki_store(
        storage_dir=storage, wiki_name=config.wiki_name, backend=config.backend
    )
    await store.upsert_pages([
        WikiPageRecord(
            concept_id=concept_id,
            title=concept_id,
            summary="alpha content",
            body="alpha content",
            category="concept",
        )
    ])


@pytest.fixture
async def two_projects(tmp_path: Path) -> tuple[Path, Path]:
    """A local project declaring one ``other`` namespace, both built."""
    other = tmp_path / "other"
    other.mkdir()
    await _seed(other, WikiProjectConfig(wiki_name="other"), "file:other.py")

    local = tmp_path / "local"
    local.mkdir()
    await _seed(
        local,
        WikiProjectConfig(
            wiki_name="local",
            namespaces={"other": WikiNamespaceConfig(path=str(other))},
        ),
        "file:local.py",
    )
    return local, other


class TestFederatedInjection:
    def test_no_namespaces_keeps_a_plain_store(self, tmp_path: Path):
        save_project_config(tmp_path, WikiProjectConfig(wiki_name="plain"))
        server = create_wiki_mcp_server(tmp_path)
        assert set(server.tools) == BASE_TOOLS
        query = server.tools["wiki_query"]
        assert not isinstance(query.tool._store, FederatedWikiStore)

    @pytest.mark.asyncio
    async def test_namespace_is_injected(self, two_projects):
        local, _other = two_projects
        server = create_wiki_mcp_server(local)
        assert set(server.tools) == BASE_TOOLS
        store = server.tools["wiki_query"].tool._store
        assert isinstance(store, FederatedWikiStore)
        assert set(store.namespaces) == {"other"}
        assert "other" in server.config.description

    @pytest.mark.asyncio
    async def test_wiki_query_returns_qualified_ids(self, two_projects):
        local, _other = two_projects
        server = create_wiki_mcp_server(local)
        text = await server.tools["wiki_query"].tool._execute(question="alpha")
        assert "file:local.py" in text
        assert "other::file:other.py" in text

    @pytest.mark.asyncio
    async def test_wiki_page_reads_a_foreign_page(self, two_projects):
        local, _other = two_projects
        server = create_wiki_mcp_server(local)
        result = await server.tools["wiki_page"].tool._execute(
            page_id="other::file:other.py"
        )
        assert result.success
        assert result.result["namespace"] == "other"

    @pytest.mark.asyncio
    async def test_wiki_status_lists_namespaces(self, two_projects):
        local, _other = two_projects
        server = create_wiki_mcp_server(local)
        result = await server.tools["wiki_status"].tool._execute()
        assert result.result["namespaces"]["other"]["status"] == "ok"
        assert result.result["skipped"] == []

    @pytest.mark.asyncio
    async def test_unbuilt_namespace_is_skipped_not_fatal(
        self, tmp_path: Path
    ):
        empty = tmp_path / "empty"
        empty.mkdir()
        local = tmp_path / "local"
        local.mkdir()
        await _seed(
            local,
            WikiProjectConfig(
                wiki_name="local",
                namespaces={"empty": WikiNamespaceConfig(path=str(empty))},
            ),
            "file:local.py",
        )
        server = create_wiki_mcp_server(local)
        store = server.tools["wiki_query"].tool._store
        assert isinstance(store, FederatedWikiStore)
        assert store.namespaces == {}
        assert [s.reason for s in store.skipped] == ["unbuilt"]
        text = await server.tools["wiki_query"].tool._execute(question="alpha")
        assert "file:local.py" in text
