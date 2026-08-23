from unittest.mock import AsyncMock, patch

import pytest
from parrot.knowledge.wiki.tools import (
    WikiNoteTool,
    WikiPageTool,
    WikiQueryTool,
    WikiRelatedTool,
    WikiRememberTool,
    WikiStatusTool,
    create_wiki_tools,
)
from parrot.tools.abstract import ToolResult


@pytest.fixture
def mock_store():
    store = AsyncMock()
    store.search_fts.return_value = [
        {"concept_id": "page-1", "title": "Test Page", "score": 0.9}
    ]
    store.get_page.return_value = {
        "concept_id": "page-1", "title": "Test Page", "body": "Content here"
    }
    store.neighbors.return_value = [
        {"concept_id": "page-2", "title": "Related", "rel": "references"}
    ]
    store.stats.return_value = {"total_pages": 100, "last_build": "2026-08-01"}
    store.upsert_pages.return_value = 1
    store.add_edges.return_value = 1
    return store


class TestWikiQueryTool:
    @pytest.mark.asyncio
    async def test_query_returns_results(self, mock_store):
        tool = WikiQueryTool(mock_store)
        result = await tool._execute(question="test query")
        mock_store.search_fts.assert_called_once()
        assert isinstance(result, str)


class TestWikiPageTool:
    @pytest.mark.asyncio
    async def test_get_page(self, mock_store):
        tool = WikiPageTool(mock_store)
        result = await tool._execute(page_id="page-1")
        mock_store.get_page.assert_called_once_with("page-1", include_body=True)
        assert isinstance(result, ToolResult)
        assert result.success is True
        assert result.result["concept_id"] == "page-1"

    @pytest.mark.asyncio
    async def test_get_page_not_found(self, mock_store):
        mock_store.get_page.return_value = None
        tool = WikiPageTool(mock_store)
        result = await tool._execute(page_id="missing")
        assert isinstance(result, ToolResult)
        assert result.success is False
        assert "not found" in result.error.lower()


class TestWikiRelatedTool:
    @pytest.mark.asyncio
    async def test_get_related(self, mock_store):
        tool = WikiRelatedTool(mock_store)
        result = await tool._execute(page_id="page-1")
        mock_store.neighbors.assert_called_once()
        assert isinstance(result, ToolResult)
        assert result.result["neighbors"] == mock_store.neighbors.return_value


class TestWikiRememberTool:
    @pytest.mark.asyncio
    async def test_remember_saves(self, mock_store):
        tool = WikiRememberTool(mock_store)
        result = await tool._execute(fact="Important finding", category="decision")
        mock_store.upsert_pages.assert_called_once()
        assert isinstance(result, ToolResult)
        assert result.result["category"] == "decision"
        assert result.result["linked"] is False

    @pytest.mark.asyncio
    async def test_remember_links(self, mock_store):
        tool = WikiRememberTool(mock_store)
        result = await tool._execute(
            fact="Important finding", category="decision", link_page_id="page-1"
        )
        mock_store.add_edges.assert_called_once()
        assert result.result["linked"] is True

    @pytest.mark.asyncio
    async def test_remember_logs_to_bookkeeper(self, mock_store, tmp_path):
        tool = WikiRememberTool(mock_store, storage_dir=tmp_path)
        await tool._execute(fact="Important finding", category="decision")
        log_path = tmp_path / "log.md"
        assert log_path.exists()
        assert "[REMEMBER]" in log_path.read_text()

    @pytest.mark.asyncio
    async def test_remember_no_bookkeeper_when_storage_dir_none(self, mock_store):
        # Default (no storage_dir) must not raise and must not write anything.
        tool = WikiRememberTool(mock_store)
        result = await tool._execute(fact="Important finding")
        assert result.success is True

    @pytest.mark.asyncio
    async def test_remember_survives_bookkeeper_failure(self, mock_store, tmp_path):
        # A store write that already succeeded must not be reported as a
        # tool failure just because the audit-log append itself failed.
        tool = WikiRememberTool(mock_store, storage_dir=tmp_path)
        with patch(
            "parrot.knowledge.wiki.tools.WikiBookkeeper.log_operation",
            side_effect=OSError("disk full"),
        ):
            result = await tool._execute(fact="Important finding")
        assert result.success is True
        mock_store.upsert_pages.assert_called_once()


class TestWikiNoteTool:
    @pytest.mark.asyncio
    async def test_note_appends(self, mock_store):
        tool = WikiNoteTool(mock_store)
        result = await tool._execute(page_id="page-1", text="A note")
        mock_store.get_page.assert_called_once()
        mock_store.upsert_pages.assert_called_once()
        assert result.result["status"] == "noted"

    @pytest.mark.asyncio
    async def test_note_page_not_found(self, mock_store):
        mock_store.get_page.return_value = None
        tool = WikiNoteTool(mock_store)
        result = await tool._execute(page_id="missing", text="A note")
        assert result.success is False
        mock_store.upsert_pages.assert_not_called()

    @pytest.mark.asyncio
    async def test_note_logs_to_bookkeeper(self, mock_store, tmp_path):
        tool = WikiNoteTool(mock_store, storage_dir=tmp_path)
        await tool._execute(page_id="page-1", text="A note")
        log_path = tmp_path / "log.md"
        assert log_path.exists()
        assert "[NOTE]" in log_path.read_text()

    @pytest.mark.asyncio
    async def test_note_survives_bookkeeper_failure(self, mock_store, tmp_path):
        tool = WikiNoteTool(mock_store, storage_dir=tmp_path)
        with patch(
            "parrot.knowledge.wiki.tools.WikiBookkeeper.log_operation",
            side_effect=OSError("disk full"),
        ):
            result = await tool._execute(page_id="page-1", text="A note")
        assert result.success is True
        mock_store.upsert_pages.assert_called_once()


class TestWikiStatusTool:
    @pytest.mark.asyncio
    async def test_status_returns_stats(self, mock_store):
        tool = WikiStatusTool(mock_store)
        result = await tool._execute()
        mock_store.stats.assert_called_once()
        assert result.result["total_pages"] == 100


class TestFactory:
    def test_create_wiki_tools(self, mock_store):
        tools = create_wiki_tools(mock_store)
        assert len(tools) == 6
        names = {t.name for t in tools}
        assert names == {"wiki_query", "wiki_page", "wiki_related",
                         "wiki_remember", "wiki_note", "wiki_status"}

    def test_create_wiki_tools_wires_storage_dir_for_bookkeeping(self, mock_store, tmp_path):
        from parrot.knowledge.wiki.project import WikiProjectConfig

        config = WikiProjectConfig(wiki_name="test")
        tools = create_wiki_tools(mock_store, root=tmp_path, config=config)
        by_name = {t.name: t for t in tools}
        assert by_name["wiki_remember"]._storage_dir == config.storage_path(tmp_path)
        assert by_name["wiki_note"]._storage_dir == config.storage_path(tmp_path)


class TestNamespaceArgument:
    """FEAT-450 — the optional ``namespace`` argument on the read tools."""

    @pytest.fixture
    async def federated(self, tmp_path):
        """A real FederatedWikiStore over two temp planes."""
        from parrot.knowledge.wiki.federation import (
            FederatedWikiStore,
            NamespaceHandle,
        )
        from parrot.knowledge.wiki.project import WikiNamespaceConfig
        from parrot.knowledge.wiki.store import SQLiteWikiStore, WikiPageRecord

        local = SQLiteWikiStore(tmp_path / "local" / "wiki.db")
        await local.upsert_pages([
            WikiPageRecord(
                concept_id="file:a.py", title="a", summary="alpha local",
                body="alpha local",
            )
        ])
        writable_other = SQLiteWikiStore(tmp_path / "other" / "wiki.db")
        await writable_other.upsert_pages([
            WikiPageRecord(
                concept_id="file:b.py", title="b", summary="alpha other",
                body="alpha other",
            )
        ])
        await writable_other.add_edges([("file:b.py", "file:a.py", "references")])
        other = SQLiteWikiStore(tmp_path / "other" / "wiki.db", read_only=True)
        return FederatedWikiStore(
            local=local,
            local_name="local",
            handles=[
                NamespaceHandle(
                    name="other",
                    store=other,
                    config=WikiNamespaceConfig(store=str(tmp_path / "other")),
                    origin="repo",
                    storage_dir=tmp_path / "other",
                )
            ],
        )

    @pytest.mark.asyncio
    async def test_query_broadcasts_by_default(self, federated):
        text = await WikiQueryTool(federated)._execute(question="alpha")
        assert "file:a.py" in text
        assert "other::file:b.py" in text

    @pytest.mark.asyncio
    async def test_query_scoped_to_one_namespace(self, federated):
        text = await WikiQueryTool(federated)._execute(
            question="alpha", namespace="other"
        )
        assert "other::file:b.py" in text
        assert "[file:a.py]" not in text

    @pytest.mark.asyncio
    async def test_query_local_only(self, federated):
        text = await WikiQueryTool(federated)._execute(
            question="alpha", namespace="local"
        )
        assert "file:a.py" in text
        assert "other::" not in text

    @pytest.mark.asyncio
    async def test_query_unknown_namespace(self, federated):
        text = await WikiQueryTool(federated)._execute(
            question="alpha", namespace="ghost"
        )
        assert "Unknown namespace" in text
        assert "other" in text

    @pytest.mark.asyncio
    async def test_page_accepts_qualified_id(self, federated):
        result = await WikiPageTool(federated)._execute(
            page_id="other::file:b.py"
        )
        assert result.success
        assert result.result["concept_id"] == "other::file:b.py"

    @pytest.mark.asyncio
    async def test_page_unknown_namespace(self, federated):
        result = await WikiPageTool(federated)._execute(
            page_id="file:b.py", namespace="ghost"
        )
        assert result.success is False
        assert "Unknown namespace" in result.error

    @pytest.mark.asyncio
    async def test_related_returns_qualified_neighbours(self, federated):
        result = await WikiRelatedTool(federated)._execute(
            page_id="other::file:b.py"
        )
        assert result.success
        neighbours = result.result["neighbors"]
        assert neighbours
        assert all(n["concept_id"].startswith("other::") for n in neighbours)

    @pytest.mark.asyncio
    async def test_related_unknown_namespace(self, federated):
        result = await WikiRelatedTool(federated)._execute(
            page_id="file:b.py", namespace="ghost"
        )
        assert result.success is False
        assert "Unknown namespace" in result.error

    @pytest.mark.asyncio
    async def test_status_exposes_namespaces(self, federated):
        result = await WikiStatusTool(federated)._execute()
        assert "other" in result.result["namespaces"]
        assert result.result["skipped"] == []

    @pytest.mark.asyncio
    async def test_plain_store_ignores_namespace(self, mock_store):
        """An AsyncMock has a `scoped` attribute — it must not be used."""
        await WikiQueryTool(mock_store)._execute(
            question="test", namespace="whatever"
        )
        mock_store.search_fts.assert_called_once()
        mock_store.scoped.assert_not_called()

        page = await WikiPageTool(mock_store)._execute(
            page_id="page-1", namespace="whatever"
        )
        assert page.success
        related = await WikiRelatedTool(mock_store)._execute(
            page_id="page-1", namespace="whatever"
        )
        assert related.success

    def test_input_schemas_expose_namespace(self):
        from parrot.knowledge.wiki.tools import (
            WikiPageInput,
            WikiQueryInput,
            WikiRelatedInput,
        )

        for model in (WikiQueryInput, WikiPageInput, WikiRelatedInput):
            assert "namespace" in model.model_fields
            assert model.model_fields["namespace"].default is None


class TestForeignPageWrites:
    """M4 — writes to a namespaced page fail cleanly, never mid-write."""

    @pytest.fixture
    async def federated(self, tmp_path):
        from parrot.knowledge.wiki.federation import (
            FederatedWikiStore,
            NamespaceHandle,
        )
        from parrot.knowledge.wiki.project import WikiNamespaceConfig
        from parrot.knowledge.wiki.store import SQLiteWikiStore, WikiPageRecord

        local = SQLiteWikiStore(tmp_path / "local" / "wiki.db")
        await local.upsert_pages(
            [WikiPageRecord(concept_id="file:a.py", title="a", body="local")]
        )
        writable = SQLiteWikiStore(tmp_path / "other" / "wiki.db")
        await writable.upsert_pages(
            [WikiPageRecord(concept_id="file:b.py", title="b", body="other")]
        )
        other = SQLiteWikiStore(tmp_path / "other" / "wiki.db", read_only=True)
        return FederatedWikiStore(
            local=local,
            local_name="local",
            handles=[
                NamespaceHandle(
                    name="other",
                    store=other,
                    config=WikiNamespaceConfig(store=str(tmp_path / "other")),
                    origin="repo",
                    storage_dir=tmp_path / "other",
                )
            ],
        )

    @pytest.mark.asyncio
    async def test_note_on_a_foreign_page_returns_a_tool_error(
        self, federated, tmp_path
    ):
        result = await WikiNoteTool(
            federated, storage_dir=tmp_path / "local"
        )._execute(page_id="other::file:b.py", text="hi")
        assert result.success is False
        assert "other" in result.error
        assert "--ns other" in result.error

    @pytest.mark.asyncio
    async def test_note_on_a_local_page_still_works(self, federated, tmp_path):
        result = await WikiNoteTool(
            federated, storage_dir=tmp_path / "local"
        )._execute(page_id="file:a.py", text="hi")
        assert result.success is True

    @pytest.mark.asyncio
    async def test_remember_with_a_foreign_link_writes_nothing(
        self, federated, tmp_path
    ):
        result = await WikiRememberTool(
            federated, storage_dir=tmp_path / "local"
        )._execute(
            fact="zebra fact", title="ZZZ", link_page_id="other::file:b.py"
        )
        assert result.success is False
        assert "--ns other" in result.error
        # Nothing was written — the validation happens before the upsert.
        pages = await federated.local.list_pages(limit=50)
        assert not [p for p in pages if str(p["concept_id"]).startswith("mem-")]

    @pytest.mark.asyncio
    async def test_remember_with_a_local_link_still_works(
        self, federated, tmp_path
    ):
        result = await WikiRememberTool(
            federated, storage_dir=tmp_path / "local"
        )._execute(fact="ok fact", title="OK", link_page_id="file:a.py")
        assert result.success is True
        assert result.result["linked"] is True
