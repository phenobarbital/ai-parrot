"""Tests for the request-scoped wiki actor (FEAT-569 TASK-3352)."""

from unittest.mock import AsyncMock

import pytest
from parrot.knowledge.wiki.actor import actor_scope, current_actor
from parrot.knowledge.wiki.tools import LedgerClaimTool, LedgerCloseTool, LedgerOpenTool, WikiRememberTool


@pytest.fixture
def store():
    s = AsyncMock()
    s.upsert_pages.return_value = 1
    s.add_edges.return_value = 1
    return s


class TestActorContext:
    def test_default(self):
        assert current_actor() == "agent:mcp"

    def test_scope_sets_and_resets(self):
        with actor_scope("human:x"):
            assert current_actor() == "human:x"
        assert current_actor() == "agent:mcp"

    def test_none_scope_is_noop(self):
        with actor_scope("human:x"):
            with actor_scope(None):
                assert current_actor() == "human:x"


class TestAttribution:
    @pytest.mark.asyncio
    async def test_remember_uses_scoped_actor(self, store):
        tool = WikiRememberTool(store)
        with actor_scope("human:alice"):
            await tool._execute(fact="a fact", category="note")
        page = store.upsert_pages.call_args.args[0][0]
        assert page.asserted_by == "human:alice"

    @pytest.mark.asyncio
    async def test_remember_default_actor(self, store):
        await WikiRememberTool(store)._execute(fact="a fact", category="note")
        assert store.upsert_pages.call_args.args[0][0].asserted_by == "agent:mcp"

    @pytest.mark.asyncio
    async def test_ledger_tools_pass_current_actor(self):
        svc = AsyncMock()
        svc.open_issue.return_value = "issue:1"
        with actor_scope("human:bob"):
            await LedgerOpenTool(svc)._execute(title="t", body="b", discovered_from="spec:FEAT-1")
            await LedgerClaimTool(svc)._execute(issue_id="issue:1")
            await LedgerCloseTool(svc)._execute(issue_id="issue:1", reason="done")
        assert svc.open_issue.call_args.kwargs["actor"] == "human:bob"
        assert svc.claim.call_args.args == ("issue:1", "human:bob")
        assert svc.close_issue.call_args.args == ("issue:1", "done", "human:bob")


class TestRequestActorPrecedence:
    @pytest.mark.asyncio
    async def test_request_actor_overrides_client_supplied_actor(self):
        svc = AsyncMock()
        with actor_scope("human:bob"):
            await LedgerClaimTool(svc)._execute(issue_id="issue:1", actor="human:spoofed")
            await LedgerCloseTool(svc)._execute(issue_id="issue:1", reason="r", actor="human:spoofed")
        assert svc.claim.call_args.args == ("issue:1", "human:bob")
        assert svc.close_issue.call_args.args[2] == "human:bob"

    @pytest.mark.asyncio
    async def test_explicit_actor_honoured_without_request_scope(self):
        svc = AsyncMock()
        await LedgerClaimTool(svc)._execute(issue_id="issue:1", actor="agent:sdd-fix")
        assert svc.claim.call_args.args == ("issue:1", "agent:sdd-fix")

    def test_tools_module_has_no_hardcoded_default_actor(self):
        import parrot.knowledge.wiki.tools as tools_module

        assert '"agent:mcp"' not in open(tools_module.__file__, encoding="utf-8").read()
        assert "agent:mcp)" not in open(tools_module.__file__, encoding="utf-8").read()
