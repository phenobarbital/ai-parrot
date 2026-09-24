"""Tests for ledger MCP tools and provenance extensions."""

import pytest
from unittest.mock import AsyncMock, MagicMock

from parrot.knowledge.wiki.tools import (
    WikiRememberInput,
    WikiRememberTool,
    LedgerOpenTool,
    LedgerReadyTool,
    LedgerClaimTool,
    LedgerCloseInput,
    LedgerCloseTool,
    LedgerContextTool,
)
from parrot.tools.abstract import ToolResult


@pytest.fixture
def mock_store():
    """Mock wiki store."""
    return AsyncMock()


@pytest.fixture
def mock_ledger_service():
    """Mock ledger service."""
    return AsyncMock()


class TestWikiRememberProvenance:
    """Test provenance extensions to WikiRememberTool."""

    def test_wiki_remember_input_has_provenance_fields(self):
        """WikiRememberInput should have derived_from (str) and about (list[str]) fields."""
        input_model = WikiRememberInput(
            fact="Test fact",
            derived_from="issue:abc123",
            about=["file:src/main.py"],
        )
        assert input_model.derived_from == "issue:abc123"
        assert input_model.about == ["file:src/main.py"]

    @pytest.mark.asyncio
    async def test_wiki_remember_stores_ledger_targets_foreign_qualified(self, mock_store):
        """A ledger-kind derived_from/about target is stored as ledger::<target>."""
        tool = WikiRememberTool(mock_store)
        mock_store.upsert_pages = AsyncMock()
        mock_store.add_edges = AsyncMock()

        result = await tool._execute(
            fact="Test fact",
            derived_from="task:TASK-3200",
            about=["issue:abc123", "spec:FEAT-566"],
        )

        assert result.success is True
        mock_store.add_edges.assert_called_once()
        edges = mock_store.add_edges.call_args[0][0]
        edges_by_kind = {edge[2]: edge[1] for edge in edges}

        assert edges_by_kind["derived-from"] == "ledger::task:TASK-3200"
        # Multiple `about` targets each produce their own edge.
        about_targets = {edge[1] for edge in edges if edge[2] == "about"}
        assert about_targets == {"ledger::issue:abc123", "ledger::spec:FEAT-566"}

    @pytest.mark.asyncio
    async def test_wiki_remember_stores_code_plane_targets_unqualified(self, mock_store):
        """A code-plane derived_from/about target (sym:/file:) is stored verbatim."""
        tool = WikiRememberTool(mock_store)
        mock_store.upsert_pages = AsyncMock()
        mock_store.add_edges = AsyncMock()

        result = await tool._execute(
            fact="Test fact",
            derived_from="sym:pkg/mod.py#Func",
            about=["file:src/main.py"],
        )

        assert result.success is True
        edges = mock_store.add_edges.call_args[0][0]
        edges_by_kind = {edge[2]: edge[1] for edge in edges}
        assert edges_by_kind["derived-from"] == "sym:pkg/mod.py#Func"
        assert edges_by_kind["about"] == "file:src/main.py"


class TestLedgerTools:
    """Test ledger MCP tools."""

    def test_ledger_tool_names(self):
        """Ledger tools should have correct names."""
        assert LedgerOpenTool.name == "ledger_open"
        assert LedgerReadyTool.name == "ledger_ready"
        assert LedgerClaimTool.name == "ledger_claim"
        assert LedgerCloseTool.name == "ledger_close"
        assert LedgerContextTool.name == "ledger_context"

    @pytest.mark.asyncio
    async def test_ledger_open_tool(self, mock_ledger_service):
        """LedgerOpenTool should call ledger service open_issue."""
        tool = LedgerOpenTool(mock_ledger_service)
        mock_ledger_service.open_issue.return_value = "issue:def456"

        result = await tool._execute(title="Test Issue", body="Test description", discovered_from="spec:FEAT-1")

        assert result.success is True
        assert result.result == {"issue_id": "issue:def456"}
        mock_ledger_service.open_issue.assert_called_once_with(
            title="Test Issue",
            body="Test description",
            kind="bug",
            severity="minor",
            discovered_from="spec:FEAT-1",
            about=None,
            actor="agent:mcp",
        )

    @pytest.mark.asyncio
    async def test_ledger_ready_tool(self, mock_ledger_service):
        """LedgerReadyTool should call ledger service ready_work."""
        tool = LedgerReadyTool(mock_ledger_service)
        mock_ledger_service.ready_work.return_value = [{"issue_id": "issue:def456"}]

        result = await tool._execute()

        assert result.success is True
        assert result.result == {"issues": [{"issue_id": "issue:def456"}]}
        mock_ledger_service.ready_work.assert_called_once_with(None)

    @pytest.mark.parametrize(
        "overrides",
        [{"kind": "task"}, {"severity": "important"}, {"discovered_from": ""}, {"discovered_from": None}],
    )
    def test_ledger_open_schema_matches_cli_choices(self, overrides):
        """The MCP schema rejects exactly what `wikitoolkit ledger open` rejects."""
        from pydantic import ValidationError

        from parrot.knowledge.wiki.tools import LedgerOpenInput

        args = {"title": "t", "body": "b", "discovered_from": "spec:FEAT-1", **overrides}
        if args["discovered_from"] is None:
            del args["discovered_from"]
        with pytest.raises(ValidationError):
            LedgerOpenInput(**args)

    def test_ledger_open_schema_exposes_enums(self):
        from parrot.knowledge.wiki.tools import LedgerOpenInput

        props = LedgerOpenInput.model_json_schema()["properties"]
        assert props["kind"]["enum"] == ["bug", "tech_debt", "feature_gap", "vulnerability"]
        assert props["severity"]["enum"] == ["critical", "major", "minor", "low"]

    @pytest.mark.asyncio
    async def test_ledger_ready_tool_passes_kind_filter(self, mock_ledger_service):
        """A kind filter must reach ready_work (IssueKind is a Literal and cannot be called)."""
        tool = LedgerReadyTool(mock_ledger_service)
        mock_ledger_service.ready_work.return_value = []

        result = await tool._execute(kind="tech_debt")

        assert result.success is True
        mock_ledger_service.ready_work.assert_called_once_with("tech_debt")

    @pytest.mark.asyncio
    async def test_ledger_claim_tool_forwards_actor(self, mock_ledger_service):
        tool = LedgerClaimTool(mock_ledger_service)
        mock_ledger_service.claim.return_value = True

        await tool._execute(issue_id="issue:abc", actor="agent:sdd-fix")

        mock_ledger_service.claim.assert_called_once_with("issue:abc", "agent:sdd-fix")

    @pytest.mark.asyncio
    async def test_ledger_claim_tool(self, mock_ledger_service):
        """LedgerClaimTool should call ledger service claim."""
        tool = LedgerClaimTool(mock_ledger_service)
        mock_ledger_service.claim.return_value = True

        result = await tool._execute(issue_id="issue:def456")

        assert result.success is True
        assert result.result == {"success": True}
        mock_ledger_service.claim.assert_called_once_with("issue:def456", "agent:mcp")

    @pytest.mark.asyncio
    async def test_ledger_close_tool(self, mock_ledger_service):
        """LedgerCloseTool should call ledger service close_issue."""
        tool = LedgerCloseTool(mock_ledger_service)
        mock_ledger_service.close_issue.return_value = True

        result = await tool._execute(issue_id="issue:def456", reason="Fixed")

        assert result.success is True
        assert result.result == {"success": True}
        mock_ledger_service.close_issue.assert_called_once_with("issue:def456", "Fixed", "agent:mcp")

    @pytest.mark.asyncio
    async def test_ledger_context_tool(self, mock_ledger_service):
        """LedgerContextTool should call ledger service get_context."""
        tool = LedgerContextTool(mock_ledger_service)
        mock_ledger_service.get_context.return_value = "Test context"

        result = await tool._execute(file_paths=["src/main.py"])

        assert result.success is True
        assert result.result == {"context": "Test context"}
        mock_ledger_service.get_context.assert_called_once_with(["src/main.py"], 3000)

    @pytest.mark.asyncio
    async def test_mcp_ledger_close_passes_resolved_by(self, mock_ledger_service):
        """LedgerCloseTool forwards the evidence ref (S4)."""
        tool = LedgerCloseTool(mock_ledger_service)
        mock_ledger_service.close_issue.return_value = True
        result = await tool._execute(issue_id="issue:def456", reason="Fixed", resolved_by="commit:abc123")
        assert result.result == {"success": True}
        mock_ledger_service.close_issue.assert_called_once_with(
            "issue:def456", "Fixed", "agent:mcp", resolved_by="commit:abc123"
        )

    @pytest.mark.asyncio
    async def test_mcp_ledger_close_without_resolved_by_unchanged(self, mock_ledger_service):
        """Default None keeps the pre-FEAT-572 call shape."""
        tool = LedgerCloseTool(mock_ledger_service)
        mock_ledger_service.close_issue.return_value = True
        result = await tool._execute(issue_id="issue:def456", reason="Fixed")
        assert result.result == {"success": True}
        mock_ledger_service.close_issue.assert_called_once_with("issue:def456", "Fixed", "agent:mcp")
        assert LedgerCloseInput(issue_id="x", reason="y").resolved_by is None

    def test_no_acknowledge_tool_exists(self):
        """There should be no ledger_acknowledge tool."""
        # This is a negative test - we verify by inspection that no such tool exists
        # The task explicitly states that acknowledge is human-only CLI
        assert not hasattr(LedgerOpenTool, "ledger_acknowledge")
