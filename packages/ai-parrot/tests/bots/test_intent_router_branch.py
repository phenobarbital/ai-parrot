"""Tests for IntentRouterMixin ContextEnvelope branch logic (FEAT-159 TASK-1091).

Tests that _run_graph_pageindex correctly branches on ContextEnvelope states:
- state="ok" with graph_context or vector_context → format + return with provenance
- state="ok" with empty/None context → fall back to unscoped PageIndex
- state="ambiguous" → format clarification message
- state="denied" → format denial message
- state="entity_not_found" → format not-found message
- state="auth_required" → format auth URL message
- state="render_error" / "tool_failed" → format error message
- state="disabled" / "not_configured" → fall through to PageIndex
- Non-ContextEnvelope result → str(result) fallback
"""
from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pytest

from parrot.bots.mixins.intent_router import IntentRouterMixin
from parrot.knowledge.ontology.schema import (
    ContextEnvelope,
    EnrichedContext,
    ResolvedIntent,
)


# ---------------------------------------------------------------------------
# Infrastructure
# ---------------------------------------------------------------------------


class MockBot:
    """Minimal base class simulating a bot."""

    def __init__(self, **kwargs: object) -> None:
        self.logger = MagicMock()

    async def conversation(self, prompt: str, **kwargs: object) -> str:
        return f"base: {prompt}"

    async def ask(self, prompt: str, **kwargs: object) -> str:
        return f"ask: {prompt}"

    async def invoke(self, prompt: str, **kwargs: object) -> MagicMock:
        return MagicMock(output=None)


class RouterBot(IntentRouterMixin, MockBot):
    """Concrete test class combining mixin with mock bot."""

    pass


def _make_bot(
    ontology_process_result: object = None,
    pageindex_retriever_result: str | None = None,
    tenant_id: str = "test",
) -> RouterBot:
    """Create a RouterBot with mocked ontology_process and retriever."""
    bot = RouterBot()
    bot._tenant_id = tenant_id

    if ontology_process_result is not None:
        bot.ontology_process = AsyncMock(return_value=ontology_process_result)
    else:
        bot.ontology_process = None  # type: ignore[assignment]

    if pageindex_retriever_result is not None:
        retriever = AsyncMock()
        retriever.retrieve = AsyncMock(return_value=pageindex_retriever_result)
        bot._pageindex_retriever = retriever
    else:
        bot._pageindex_retriever = None  # type: ignore[assignment]

    return bot


def _make_resolved_intent(pattern: str = "find_dept") -> ResolvedIntent:
    return ResolvedIntent(
        action="graph_query",
        pattern=pattern,
        source="fast_path",
    )


def _make_ok_envelope(
    graph_context: list | None = None,
    vector_context: list | None = None,
    source: str = "ontology",
) -> ContextEnvelope:
    return ContextEnvelope(
        state="ok",
        context=EnrichedContext(
            source=source,
            graph_context=graph_context,
            vector_context=vector_context,
            intent=_make_resolved_intent(),
        ),
    )


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


class TestContextEnvelopeOkState:
    """Tests for state="ok" ContextEnvelope handling."""

    @pytest.mark.asyncio
    async def test_ok_with_graph_context_returns_formatted_string(self) -> None:
        """state="ok" with graph_context → returns formatted string with source label."""
        envelope = _make_ok_envelope(
            graph_context=[{"title": "Sales Policy", "_id": "docs/1"}],
            source="graph:primary",
        )
        bot = _make_bot(ontology_process_result=envelope)

        result = await bot._run_graph_pageindex("what is the commission policy", [])

        assert result is not None
        assert "[Source: graph:primary]" in result
        assert "Graph context:" in result

    @pytest.mark.asyncio
    async def test_ok_with_vector_context_returns_formatted_string(self) -> None:
        """state="ok" with vector_context → returns formatted string with source label."""
        envelope = _make_ok_envelope(
            vector_context=[{"content": "Commission rules", "doc_id": "p1"}],
            source="vector:filtered",
        )
        bot = _make_bot(ontology_process_result=envelope)

        result = await bot._run_graph_pageindex("tell me about commissions", [])

        assert result is not None
        assert "[Source: vector:filtered]" in result
        assert "Vector context:" in result

    @pytest.mark.asyncio
    async def test_ok_with_empty_context_falls_back_to_pageindex(self) -> None:
        """state="ok" with empty context (vector_only shell) → falls back to PageIndex."""
        envelope = ContextEnvelope(
            state="ok",
            context=EnrichedContext(
                source="vector_only",
                graph_context=None,
                vector_context=None,
            ),
        )
        bot = _make_bot(
            ontology_process_result=envelope,
            pageindex_retriever_result="PageIndex result",
        )

        result = await bot._run_graph_pageindex("some query", [])

        assert result == "PageIndex result"
        bot._pageindex_retriever.retrieve.assert_called_once_with("some query")

    @pytest.mark.asyncio
    async def test_ok_with_none_context_falls_back_to_pageindex(self) -> None:
        """state="ok" with context=None → falls back to PageIndex retriever."""
        envelope = ContextEnvelope(state="ok", context=None)
        bot = _make_bot(
            ontology_process_result=envelope,
            pageindex_retriever_result="fallback result",
        )

        result = await bot._run_graph_pageindex("query", [])

        assert result == "fallback result"

    @pytest.mark.asyncio
    async def test_ok_with_empty_context_no_retriever_returns_none(self) -> None:
        """state="ok" with empty context and no PageIndex retriever → returns None."""
        envelope = ContextEnvelope(state="ok", context=None)
        bot = _make_bot(ontology_process_result=envelope)

        result = await bot._run_graph_pageindex("query", [])

        assert result is None

    @pytest.mark.asyncio
    async def test_ok_with_graph_and_tool_result(self) -> None:
        """state="ok" with graph_context AND tool_result → both appear in output."""
        envelope = ContextEnvelope(
            state="ok",
            context=EnrichedContext(
                source="graph:primary",
                graph_context=[{"title": "Doc1"}],
            ),
            tool_result={"issues": [{"id": "TROC-1"}]},
        )
        bot = _make_bot(ontology_process_result=envelope)

        result = await bot._run_graph_pageindex("issues?", [])

        assert result is not None
        assert "Tool result:" in result


class TestContextEnvelopeNonOkStates:
    """Tests for non-ok ContextEnvelope states."""

    @pytest.mark.asyncio
    async def test_ambiguous_returns_clarification_message(self) -> None:
        """state="ambiguous" → returns formatted clarification; does NOT call PageIndex."""
        envelope = ContextEnvelope(
            state="ambiguous",
            clarification={
                "rule": "topic",
                "mention": "commissions",
                "candidates": [
                    {"_id": "d/1", "name": "Sales Commissions"},
                    {"_id": "d/2", "name": "Broker Commissions"},
                ],
            },
        )
        bot = _make_bot(
            ontology_process_result=envelope,
            pageindex_retriever_result="should not be called",
        )

        result = await bot._run_graph_pageindex("what about commissions?", [])

        assert result is not None
        assert "commissions" in result
        assert "Sales Commissions" in result or "Broker Commissions" in result
        bot._pageindex_retriever.retrieve.assert_not_called()

    @pytest.mark.asyncio
    async def test_denied_returns_denial_message(self) -> None:
        """state="denied" → returns denial message; does NOT call PageIndex."""
        envelope = ContextEnvelope(
            state="denied",
            denial_reason="User does not have hr_manager role",
        )
        bot = _make_bot(
            ontology_process_result=envelope,
            pageindex_retriever_result="should not be called",
        )

        result = await bot._run_graph_pageindex("show me all salaries", [])

        assert result is not None
        assert "Access denied" in result
        assert "hr_manager" in result
        bot._pageindex_retriever.retrieve.assert_not_called()

    @pytest.mark.asyncio
    async def test_entity_not_found_returns_message(self) -> None:
        """state="entity_not_found" → returns not-found message."""
        envelope = ContextEnvelope(
            state="entity_not_found",
            error="topic not found",
        )
        bot = _make_bot(ontology_process_result=envelope)

        result = await bot._run_graph_pageindex("policy for unknown_topic?", [])

        assert result is not None
        assert "topic not found" in result

    @pytest.mark.asyncio
    async def test_auth_required_returns_auth_url(self) -> None:
        """state="auth_required" → returns auth URL message."""
        envelope = ContextEnvelope(
            state="auth_required",
            auth_prompt={
                "auth_url": "https://jira.example.com/auth",
                "provider": "jira",
                "scopes": ["read:jira-work"],
            },
        )
        bot = _make_bot(ontology_process_result=envelope)

        result = await bot._run_graph_pageindex("show my jira issues", [])

        assert result is not None
        assert "jira" in result
        assert "https://jira.example.com/auth" in result

    @pytest.mark.asyncio
    async def test_render_error_returns_error_message(self) -> None:
        """state="render_error" → returns error message."""
        envelope = ContextEnvelope(
            state="render_error",
            error="Undefined variable in template: ctx.unknown",
        )
        bot = _make_bot(ontology_process_result=envelope)

        result = await bot._run_graph_pageindex("query", [])

        assert result is not None
        assert "Undefined variable" in result

    @pytest.mark.asyncio
    async def test_tool_failed_returns_error_message(self) -> None:
        """state="tool_failed" → returns error message."""
        envelope = ContextEnvelope(
            state="tool_failed",
            error="Jira API returned 500",
        )
        bot = _make_bot(ontology_process_result=envelope)

        result = await bot._run_graph_pageindex("jira issues", [])

        assert result is not None
        assert "500" in result


class TestDisabledAndNotConfigured:
    """Tests for disabled/not_configured — should fall through to PageIndex."""

    @pytest.mark.asyncio
    async def test_disabled_falls_through_to_pageindex(self) -> None:
        """state="disabled" → falls through to PageIndex retriever."""
        envelope = ContextEnvelope(state="disabled")
        bot = _make_bot(
            ontology_process_result=envelope,
            pageindex_retriever_result="pageindex result",
        )

        result = await bot._run_graph_pageindex("query", [])

        assert result == "pageindex result"
        bot._pageindex_retriever.retrieve.assert_called_once()

    @pytest.mark.asyncio
    async def test_not_configured_falls_through_to_pageindex(self) -> None:
        """state="not_configured" → falls through to PageIndex retriever."""
        envelope = ContextEnvelope(state="not_configured")
        bot = _make_bot(
            ontology_process_result=envelope,
            pageindex_retriever_result="pageindex result 2",
        )

        result = await bot._run_graph_pageindex("query", [])

        assert result == "pageindex result 2"


class TestLegacyFallback:
    """Tests for legacy (non-ContextEnvelope) ontology_process results."""

    @pytest.mark.asyncio
    async def test_non_envelope_result_returns_str(self) -> None:
        """Non-ContextEnvelope result → str(result) fallback."""
        bot = _make_bot(ontology_process_result="some legacy string result")

        result = await bot._run_graph_pageindex("query", [])

        assert result == "some legacy string result"

    @pytest.mark.asyncio
    async def test_no_ontology_process_uses_pageindex(self) -> None:
        """No ontology_process attribute → falls through to PageIndex."""
        bot = RouterBot()
        bot._tenant_id = "test"
        bot._pageindex_retriever = AsyncMock()
        bot._pageindex_retriever.retrieve = AsyncMock(return_value="index result")

        result = await bot._run_graph_pageindex("query", [])

        assert result == "index result"


class TestFormatHelpers:
    """Tests for _format_envelope_context and _format_non_ok_envelope helpers."""

    def test_format_envelope_context_includes_source_label(self) -> None:
        """_format_envelope_context includes [Source: ...] label."""
        envelope = _make_ok_envelope(
            graph_context=[{"title": "Doc A"}],
            source="graph:secondary",
        )
        bot = RouterBot()
        result = bot._format_envelope_context(envelope)

        assert "[Source: graph:secondary]" in result
        assert "Doc A" in result

    def test_format_envelope_context_none_context_returns_empty(self) -> None:
        """_format_envelope_context with context=None → empty string."""
        envelope = ContextEnvelope(state="ok", context=None)
        bot = RouterBot()
        result = bot._format_envelope_context(envelope)
        assert result == ""

    def test_format_non_ok_ambiguous(self) -> None:
        """_format_non_ok_envelope for ambiguous state."""
        envelope = ContextEnvelope(
            state="ambiguous",
            clarification={
                "rule": "topic",
                "mention": "pto",
                "candidates": [{"name": "PTO Policy"}, {"name": "PTO Rules"}],
            },
        )
        result = IntentRouterMixin._format_non_ok_envelope(envelope)
        assert "pto" in result
        assert "PTO Policy" in result

    def test_format_non_ok_denied(self) -> None:
        """_format_non_ok_envelope for denied state."""
        envelope = ContextEnvelope(
            state="denied",
            denial_reason="requires admin role",
        )
        result = IntentRouterMixin._format_non_ok_envelope(envelope)
        assert "Access denied" in result
        assert "admin role" in result

    def test_format_non_ok_auth_required(self) -> None:
        """_format_non_ok_envelope for auth_required state."""
        envelope = ContextEnvelope(
            state="auth_required",
            auth_prompt={
                "auth_url": "https://auth.example.com",
                "provider": "google",
                "scopes": [],
            },
        )
        result = IntentRouterMixin._format_non_ok_envelope(envelope)
        assert "google" in result
        assert "https://auth.example.com" in result
