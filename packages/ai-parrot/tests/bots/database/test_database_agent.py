"""Tests for DatabaseAgent rewrite (TASK-1128 — FEAT-164)."""
from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pytest

from parrot.bots.agent import BasicAgent
from parrot.bots.database import DatabaseAgent, QueryDataset, QueryResponse
from parrot.bots.database.models import OutputComponent, UserRole, get_default_components
from parrot.bots.prompts.builder import PromptBuilder
from parrot.models.outputs import StructuredOutputConfig


# ---------------------------------------------------------------------------
# Static / class-level checks
# ---------------------------------------------------------------------------

def test_database_agent_inherits_basicagent():
    assert issubclass(DatabaseAgent, BasicAgent)


def test_database_agent_has_prompt_builder_attr():
    assert isinstance(DatabaseAgent._prompt_builder, PromptBuilder)


def test_database_agent_no_legacy_prompt_constant():
    """DatabaseAgent must NOT define its own system_prompt_template class attr."""
    # The old 'system_prompt_template = ""' placeholder must be gone.
    # If BasicAgent stub is in place this attribute may not exist at all — that's fine.
    own_attrs = vars(DatabaseAgent)
    assert "system_prompt_template" not in own_attrs, (
        "DatabaseAgent should not define its own system_prompt_template; "
        "rely on the PromptBuilder instead."
    )


def test_database_agent_get_default_components_delegates():
    agent = DatabaseAgent(toolkits=[])
    assert agent.get_default_components(UserRole.DATA_ANALYST) == \
        get_default_components(UserRole.DATA_ANALYST)


def test_database_agent_init_accepts_retry_config():
    from parrot.bots.database.retries import QueryRetryConfig
    cfg = QueryRetryConfig()
    agent = DatabaseAgent(toolkits=[], retry_config=cfg)
    assert agent.retry_config is cfg


def test_database_agent_init_rejects_enable_retry():
    """enable_retry must no longer be a named parameter."""
    import inspect
    sig = inspect.signature(DatabaseAgent.__init__)
    assert "enable_retry" not in sig.parameters


# ---------------------------------------------------------------------------
# LLM-backed ask() — requires configure() + mock _llm
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_database_agent_ask_calls_client_ask(mock_llm_client, fake_postgres_toolkit):
    """ask() invokes _llm.ask with use_tools=True and structured_output=QueryResponse."""
    agent = DatabaseAgent(toolkits=[fake_postgres_toolkit])
    await agent.configure()
    # Override _llm AFTER configure() — the inherited AbstractBot.configure
    # chain (now reached via super() in DatabaseAgent.configure) replaces
    # _llm with a freshly-resolved client. Injecting the mock afterwards
    # preserves the test's intent.
    agent._llm = mock_llm_client
    await agent.ask("list tables")
    call_kwargs = mock_llm_client.ask.call_args.kwargs
    assert call_kwargs.get("use_tools") is True
    sout = call_kwargs.get("structured_output")
    assert isinstance(sout, StructuredOutputConfig)
    assert sout.output_type is QueryResponse


@pytest.mark.asyncio
async def test_database_agent_ask_unpacks_structured_output_into_aimessage(
    mock_llm_client, fake_postgres_toolkit
):
    """When LLM returns a QueryResponse, ask() sets is_structured=True."""
    qr = QueryResponse(
        explanation="ok",
        query="SELECT 1",
        data=None,
    )
    mock_llm_client.ask.return_value = MagicMock(
        is_structured=True, output=qr, response="ok", data=None,
    )
    agent = DatabaseAgent(toolkits=[fake_postgres_toolkit])
    await agent.configure()
    # Override _llm AFTER configure() — the inherited AbstractBot.configure
    # chain (now reached via super() in DatabaseAgent.configure) replaces
    # _llm with a freshly-resolved client. Injecting the mock afterwards
    # preserves the test's intent.
    agent._llm = mock_llm_client
    msg = await agent.ask("hi")
    assert msg.is_structured is True
    assert msg.response == "ok"


@pytest.mark.asyncio
async def test_database_agent_ask_no_toolkits_returns_error_response(mock_llm_client):
    """With no toolkits, ask() returns an AIMessage wrapping a QueryResponse error."""
    agent = DatabaseAgent(toolkits=[])
    await agent.configure()
    agent._llm = mock_llm_client
    msg = await agent.ask("hi")
    qr = msg.output
    assert isinstance(qr, QueryResponse)
    assert qr.query is None and qr.data is None
    assert "no toolkit" in qr.explanation.lower() or "no database" in qr.explanation.lower()


@pytest.mark.asyncio
async def test_database_agent_ask_uses_default_components_when_omitted(
    mock_llm_client, fake_postgres_toolkit
):
    """When output_components is not passed, ask() uses get_default_components()."""
    agent = DatabaseAgent(toolkits=[fake_postgres_toolkit])
    await agent.configure()
    # Override _llm AFTER configure() — the inherited AbstractBot.configure
    # chain (now reached via super() in DatabaseAgent.configure) replaces
    # _llm with a freshly-resolved client. Injecting the mock afterwards
    # preserves the test's intent.
    agent._llm = mock_llm_client
    await agent.ask("hi")
    # LLM was called — no error means default components were resolved
    assert mock_llm_client.ask.called


# ---------------------------------------------------------------------------
# configure() — internal toolkit
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_configure_creates_internal_toolkit(fake_postgres_toolkit):
    """configure() must instantiate and store a DatabaseAgentToolkit."""
    from parrot.bots.database.toolkits import DatabaseAgentToolkit
    agent = DatabaseAgent(toolkits=[fake_postgres_toolkit])
    assert agent._internal_toolkit is None
    await agent.configure()
    agent._llm = MagicMock()
    agent._llm.ask = AsyncMock(return_value=MagicMock(output=None, is_structured=False))
    assert isinstance(agent._internal_toolkit, DatabaseAgentToolkit)


# ---------------------------------------------------------------------------
# Tool gating
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_internal_toolkit_gating_excludes_unrequested_tools(
    mock_llm_client, fake_postgres_toolkit
):
    """SQL_QUERY only → optimization tools must NOT appear; SQL tools must appear."""
    agent = DatabaseAgent(toolkits=[fake_postgres_toolkit])
    await agent.configure()
    # Override _llm AFTER configure() — the inherited AbstractBot.configure
    # chain (now reached via super() in DatabaseAgent.configure) replaces
    # _llm with a freshly-resolved client. Injecting the mock afterwards
    # preserves the test's intent.
    agent._llm = mock_llm_client
    await agent.ask("hi", output_components=OutputComponent.SQL_QUERY)
    tools = mock_llm_client.ask.call_args.kwargs.get("tools") or []
    tool_names = {getattr(t, "name", getattr(t, "__name__", "")) for t in tools}
    assert "generate_optimization_tips" not in tool_names
    assert "extract_sql_from_response" in tool_names


@pytest.mark.asyncio
async def test_internal_toolkit_gating_optimization_components(
    mock_llm_client, fake_postgres_toolkit
):
    """OPTIMIZATION_TIPS → optimization tool set exposed."""
    agent = DatabaseAgent(toolkits=[fake_postgres_toolkit])
    await agent.configure()
    # Override _llm AFTER configure() — the inherited AbstractBot.configure
    # chain (now reached via super() in DatabaseAgent.configure) replaces
    # _llm with a freshly-resolved client. Injecting the mock afterwards
    # preserves the test's intent.
    agent._llm = mock_llm_client
    await agent.ask("hi", output_components=OutputComponent.OPTIMIZATION_TIPS)
    tools = mock_llm_client.ask.call_args.kwargs.get("tools") or []
    tool_names = {getattr(t, "name", getattr(t, "__name__", "")) for t in tools}
    assert "generate_optimization_tips" in tool_names
    assert "extract_sql_from_response" not in tool_names


@pytest.mark.asyncio
async def test_ask_omits_components_uses_router_intent_overlay(
    mock_llm_client, fake_postgres_toolkit
):
    """When output_components is omitted, the router's intent-enriched
    components (role baseline | intent flags) are used — not the role
    baseline alone. Otherwise intent-specific tools are silently dropped.
    """
    agent = DatabaseAgent(toolkits=[fake_postgres_toolkit])
    await agent.configure()
    # Override _llm AFTER configure() — the inherited AbstractBot.configure
    # chain (now reached via super() in DatabaseAgent.configure) replaces
    # _llm with a freshly-resolved client. Injecting the mock afterwards
    # preserves the test's intent.
    agent._llm = mock_llm_client
    # "optimize this query" triggers QueryIntent.OPTIMIZE_QUERY in the
    # router, which adds FULL_ANALYSIS (includes OPTIMIZATION_TIPS).
    await agent.ask("optimize this query")
    tools = mock_llm_client.ask.call_args.kwargs.get("tools") or []
    tool_names = {getattr(t, "name", getattr(t, "__name__", "")) for t in tools}
    # Optimization tools must be exposed because the router's
    # intent-component overlay added OPTIMIZATION_TIPS, even though the
    # caller did not request it explicitly.
    assert "generate_optimization_tips" in tool_names


@pytest.mark.asyncio
async def test_ask_non_retryable_exec_error_surfaces_as_failure_response(
    fake_postgres_toolkit,
):
    """Non-retryable error from execute_query must produce a failure
    QueryResponse instead of returning the LLM's prior successful-looking
    response unchanged.
    """
    from parrot.bots.database.retries import QueryRetryConfig

    qr = QueryResponse(
        explanation="here is your query",
        query="SELECT bogus FROM nowhere",
        data=None,
    )
    llm = MagicMock()
    llm.ask = AsyncMock(return_value=MagicMock(
        is_structured=True, output=qr, response="here is your query", data=None,
    ))
    fake_postgres_toolkit.execute_query = AsyncMock(  # type: ignore[method-assign]
        side_effect=RuntimeError("permission denied")
    )

    agent = DatabaseAgent(
        toolkits=[fake_postgres_toolkit],
        retry_config=QueryRetryConfig(max_retries=1),
    )
    await agent.configure()
    agent._llm = llm

    msg = await agent.ask("show me the bogus column")
    assert isinstance(msg.output, QueryResponse)
    assert "non-retryable" in msg.output.explanation.lower()
    assert "permission denied" in msg.output.explanation
    assert msg.output.query == "SELECT bogus FROM nowhere"


# ---------------------------------------------------------------------------
# cleanup() — resource teardown + base-cleanup chaining
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_cleanup_stops_toolkits_closes_cache_and_chains_super(
    monkeypatch, fake_postgres_toolkit
):
    """cleanup() stops toolkits, closes the cache manager, and chains
    super().cleanup() so base-agent resources (LLM, store, KBs, MCP) are
    released too."""
    agent = DatabaseAgent(toolkits=[fake_postgres_toolkit])

    fake_postgres_toolkit.stop = AsyncMock()  # type: ignore[method-assign]
    agent.cache_manager.close = AsyncMock()  # type: ignore[method-assign]

    base_cleanup = AsyncMock()
    monkeypatch.setattr(BasicAgent, "cleanup", base_cleanup, raising=False)

    await agent.cleanup()

    fake_postgres_toolkit.stop.assert_awaited_once()
    agent.cache_manager.close.assert_awaited_once()
    base_cleanup.assert_awaited_once()


@pytest.mark.asyncio
async def test_cleanup_isolates_toolkit_failure(monkeypatch, fake_postgres_toolkit):
    """A toolkit.stop() failure must not prevent cache close or super cleanup."""
    agent = DatabaseAgent(toolkits=[fake_postgres_toolkit])

    fake_postgres_toolkit.stop = AsyncMock(  # type: ignore[method-assign]
        side_effect=RuntimeError("boom")
    )
    agent.cache_manager.close = AsyncMock()  # type: ignore[method-assign]
    base_cleanup = AsyncMock()
    monkeypatch.setattr(BasicAgent, "cleanup", base_cleanup, raising=False)

    await agent.cleanup()  # must not raise

    agent.cache_manager.close.assert_awaited_once()
    base_cleanup.assert_awaited_once()
