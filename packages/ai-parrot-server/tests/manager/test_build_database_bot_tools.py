"""Tests for BotManager._build_database_bot — normalized tools= / agent_mcp_servers=.

FEAT-593 TASK-3653. The DB load path used to pass ``available_tools=bot_model.tools``
(manager.py:515), a kwarg ``AbstractBot`` never consumed, so DB agents never actually
registered their ``tools`` column. This verifies the replacement: the constructed bot
now receives ``tools=`` (plain tool names + ``ToolkitSpec`` entries merged via
``normalize_tooling``) and ``agent_mcp_servers=``, and ``available_tools`` is gone.
"""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest
from parrot.manager.manager import BotManager
from parrot.tools.spec import ToolkitSpec


class _Captured:
    """Fake bot class capturing every kwarg passed by ``_build_database_bot``."""

    kwargs = None

    def __init__(self, **kwargs):
        _Captured.kwargs = kwargs
        self.configure = AsyncMock()
        self.store = MagicMock()
        self.llm_client = MagicMock()


def _make_manager() -> BotManager:
    """Build a bare ``BotManager`` with every collaborator ``_build_database_bot`` calls stubbed."""
    mgr = BotManager.__new__(BotManager)
    mgr.logger = MagicMock()
    mgr._resolve_database_bot_class = MagicMock(return_value=_Captured)
    mgr._normalize_database_bot_permissions = MagicMock(return_value={})
    mgr._apply_prompt_config = MagicMock()
    mgr.registry = MagicMock()
    mgr.registry.register_db_bot_policies = MagicMock(return_value=0)
    return mgr


def _make_bot_model(**overrides) -> SimpleNamespace:
    """Return a ``bot_model``-shaped ``SimpleNamespace`` with every attribute the builder reads."""
    base = dict(
        chatbot_id="chatbot-1",
        name="db-agent",
        description="A DB-origin agent",
        prompt_config={},
        llm="openai:gpt-4o-mini",
        model_config={},
        role="assistant",
        goal="help",
        backstory="",
        rationale="",
        capabilities=[],
        system_prompt_template=None,
        human_prompt_template=None,
        pre_instructions=None,
        use_vector=False,
        vector_store_config={},
        context_search_limit=5,
        context_score_threshold=0.5,
        tools_enabled=True,
        auto_tool_detection=False,
        tool_threshold=0.7,
        tools=["jira", "weather"],
        toolkit_config={"jira": {"params": {}}},
        mcp_servers=[],
        operation_mode="default",
        memory_type="in_memory",
        memory_config={},
        max_context_turns=10,
        use_conversation_history=True,
        permissions=None,
        language="en",
        disclaimer=None,
        reranker_config={},
        parent_searcher_config={},
    )
    base.update(overrides)
    return SimpleNamespace(**base)


@pytest.mark.asyncio
async def test_tools_passed(monkeypatch):
    """The normalized ``tools=``/``agent_mcp_servers=`` kwargs replace the dead ``available_tools=``."""
    monkeypatch.setattr("parrot.manager.manager.create_reranker", MagicMock(return_value=None))
    monkeypatch.setattr("parrot.manager.manager.create_parent_searcher", MagicMock(return_value=None))

    mgr = _make_manager()
    bot_model = _make_bot_model()

    await mgr._build_database_bot(bot_model, app=MagicMock())

    assert "available_tools" not in _Captured.kwargs
    assert "weather" in _Captured.kwargs["tools"]
    assert any(isinstance(t, ToolkitSpec) for t in _Captured.kwargs["tools"])
    assert _Captured.kwargs["agent_mcp_servers"] == []


@pytest.mark.asyncio
async def test_toolkit_spec_carries_slug(monkeypatch):
    """The toolkit spec produced by ``toolkit_config`` keeps its slug and params."""
    monkeypatch.setattr("parrot.manager.manager.create_reranker", MagicMock(return_value=None))
    monkeypatch.setattr("parrot.manager.manager.create_parent_searcher", MagicMock(return_value=None))

    mgr = _make_manager()
    bot_model = _make_bot_model()

    await mgr._build_database_bot(bot_model, app=MagicMock())

    toolkit_specs = [t for t in _Captured.kwargs["tools"] if isinstance(t, ToolkitSpec)]
    assert len(toolkit_specs) == 1
    assert toolkit_specs[0].slug == "jira"


@pytest.mark.asyncio
async def test_agent_mcp_servers_normalized(monkeypatch):
    """Agent-level MCP server dicts on the bot_model become ``AgentMCPServerSpec`` entries."""
    monkeypatch.setattr("parrot.manager.manager.create_reranker", MagicMock(return_value=None))
    monkeypatch.setattr("parrot.manager.manager.create_parent_searcher", MagicMock(return_value=None))

    mgr = _make_manager()
    bot_model = _make_bot_model(
        mcp_servers=[{"name": "search-mcp", "transport": "http", "url": "https://example.test/mcp"}]
    )

    await mgr._build_database_bot(bot_model, app=MagicMock())

    mcp_servers = _Captured.kwargs["agent_mcp_servers"]
    assert len(mcp_servers) == 1
    assert mcp_servers[0].name == "search-mcp"
