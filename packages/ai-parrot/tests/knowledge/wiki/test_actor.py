"""Unit tests for parrot.knowledge.wiki.actor (FEAT-569 M2a)."""

import pytest

from parrot.knowledge.wiki.actor import actor_scope, current_actor
from parrot.knowledge.wiki.store import create_wiki_store
from parrot.knowledge.wiki.tools import LedgerOpenTool, WikiRememberTool


def test_default_and_scope():
    assert current_actor() == "agent:mcp"
    with actor_scope("human:x"):
        assert current_actor() == "human:x"
        with actor_scope(None):
            assert current_actor() == "human:x"
    assert current_actor() == "agent:mcp"


@pytest.mark.asyncio
async def test_remember_uses_actor(tmp_path):
    store = create_wiki_store(tmp_path, wiki_name="t", backend="sqlite")
    tool = WikiRememberTool(store)
    with actor_scope("human:alice"):
        result = await tool._execute(fact="remote wins", category="note", title="t1")
    page = await store.get_page(result.result["page_id"])
    assert page["asserted_by"] == "human:alice"


@pytest.mark.asyncio
async def test_remember_defaults_outside_scope(tmp_path):
    store = create_wiki_store(tmp_path, wiki_name="t", backend="sqlite")
    tool = WikiRememberTool(store)
    result = await tool._execute(fact="local default", category="note", title="t2")
    page = await store.get_page(result.result["page_id"])
    assert page["asserted_by"] == "agent:mcp"


@pytest.mark.asyncio
async def test_ledger_open_passes_actor():
    captured = {}

    class _StubLedgerService:
        async def open_issue(self, **kwargs):
            captured.update(kwargs)
            return "issue:1"

    tool = LedgerOpenTool(_StubLedgerService())
    with actor_scope("agent:codex"):
        await tool._execute(title="t", body="b")
    assert captured["actor"] == "agent:codex"
