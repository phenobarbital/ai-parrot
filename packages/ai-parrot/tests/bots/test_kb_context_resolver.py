"""Regression tests for resolver-aware legacy knowledge-base context."""

from __future__ import annotations

import logging
from typing import Any

import pytest

from parrot.bots.abstract import AbstractBot
from parrot.bots.agent import BasicAgent
from parrot.stores.kb import AbstractKnowledgeBase


class _FakeKnowledgeBase(AbstractKnowledgeBase):
    """Deterministic knowledge base used to pin legacy rendering."""

    def __init__(self, name: str, content: str, *, priority: int) -> None:
        """Initialize a permanently active fake knowledge base."""
        super().__init__(name=name, category="test", always_active=True, priority=priority)
        self.content = content

    async def should_activate(self, query: str, context: dict[str, Any]) -> tuple[bool, float]:
        """Always activate with a stable confidence score."""
        return True, 1.0

    async def search(
        self,
        query: str,
        k: int = 5,
        score_threshold: float = 0.6,
        user_id: str | None = None,
        session_id: str | None = None,
        ctx: Any = None,
        **kwargs: Any,
    ) -> list[dict[str, str]]:
        """Return one deterministic result for legacy formatting."""
        return [{"content": self.content}]


class _FakeResolver:
    """Resolver double recording handle checks, searches, and invalidations."""

    def __init__(self, *, has_kb: bool, result: tuple[str, dict[str, Any]] | None = None) -> None:
        """Initialize the resolver double with a fixed handle state and result."""
        self.has_kb = has_kb
        self.result = result or ("resolver context", {"activated_kbs": [{"name": "Resolver", "confidence": 1.0}]})
        self.handle_checks: list[str] = []
        self.search_calls: list[tuple[AbstractBot, str, str | None, str | None, Any]] = []
        self.invalidations = 0

    def has_handle(self, kind: str) -> bool:
        """Record and answer a source-handle check."""
        self.handle_checks.append(kind)
        return self.has_kb

    async def search_kb(
        self,
        bot: AbstractBot,
        question: str,
        *,
        user_id: str | None = None,
        session_id: str | None = None,
        ctx: Any = None,
    ) -> tuple[str, dict[str, Any]]:
        """Record a delegated search and return the configured result unchanged."""
        self.search_calls.append((bot, question, user_id, session_id, ctx))
        return self.result

    def invalidate(self) -> None:
        """Record cache invalidation."""
        self.invalidations += 1


def _legacy_bot() -> AbstractBot:
    """Build the smallest bot state needed by the legacy KB path."""
    bot = BasicAgent.__new__(BasicAgent)
    bot.knowledge_bases = [
        _FakeKnowledgeBase("Primary", "primary answer", priority=20),
        _FakeKnowledgeBase("Secondary", "secondary answer", priority=10),
    ]
    bot.use_kb = False
    bot.kb_store = None
    bot.use_kb_selector = False
    bot.logger = logging.getLogger(__name__)
    return bot


@pytest.mark.asyncio
async def test_build_kb_context_legacy_path_unchanged() -> None:
    """Pin the exact pre-FEAT-778 legacy context and metadata output."""
    bot = _legacy_bot()

    result = await bot._build_kb_context("What is pinned?", user_id="user", session_id="session")

    assert result == (
        "## Primary:\n* primary answer\n\n## Secondary:\n* secondary answer",
        {
            "activated_kbs": [
                {"name": "Primary", "confidence": 1.0},
                {"name": "Secondary", "confidence": 1.0},
            ]
        },
    )


@pytest.mark.asyncio
async def test_build_kb_context_delegates_to_resolver() -> None:
    """Delegate once and preserve the resolver's return value and call context."""
    bot = _legacy_bot()
    expected = ("delegated", {"activated_kbs": [{"name": "Delegated", "confidence": 0.9}]})
    resolver = _FakeResolver(has_kb=True, result=expected)
    bot.knowledge_resolver = resolver
    request_context = object()

    result = await bot._build_kb_context(
        "Delegate this",
        user_id="user",
        session_id="session",
        ctx=request_context,
    )

    assert result is expected
    assert resolver.handle_checks == ["kb"]
    assert resolver.search_calls == [(bot, "Delegate this", "user", "session", request_context)]


@pytest.mark.asyncio
async def test_resolver_without_kb_handle_uses_legacy() -> None:
    """Keep the pinned legacy behavior when the resolver has no KB handle."""
    bot = _legacy_bot()
    resolver = _FakeResolver(has_kb=False)
    bot.knowledge_resolver = resolver

    result = await bot._build_kb_context("What is pinned?", user_id="user", session_id="session")

    assert result == (
        "## Primary:\n* primary answer\n\n## Secondary:\n* secondary answer",
        {
            "activated_kbs": [
                {"name": "Primary", "confidence": 1.0},
                {"name": "Secondary", "confidence": 1.0},
            ]
        },
    )
    assert resolver.handle_checks == ["kb"]
    assert resolver.search_calls == []


@pytest.mark.asyncio
async def test_legacy_wrapper_bypasses_resolver() -> None:
    """Bypass resolver dispatch in the recursion-safe legacy wrapper."""
    bot = _legacy_bot()
    resolver = _FakeResolver(has_kb=True)
    bot.knowledge_resolver = resolver

    result = await bot._legacy_build_kb_context("What is pinned?", "user", "session", None)

    assert result[0] == "## Primary:\n* primary answer\n\n## Secondary:\n* secondary answer"
    assert resolver.handle_checks == []
    assert resolver.search_calls == []


def test_register_kb_invalidates_resolver() -> None:
    """Invalidate resolver state after registering and sorting a new KB."""
    bot = _legacy_bot()
    resolver = _FakeResolver(has_kb=True)
    bot.knowledge_resolver = resolver
    new_kb = _FakeKnowledgeBase("Highest", "highest answer", priority=30)

    bot.register_kb(new_kb)

    assert resolver.invalidations == 1
    assert bot.knowledge_bases[0] is new_kb

    del bot.knowledge_resolver
    bot.register_kb(_FakeKnowledgeBase("Lowest", "lowest answer", priority=0))
    assert resolver.invalidations == 1


@pytest.mark.asyncio
async def test_plain_yaml_agent_unaffected() -> None:
    """Keep a plain BasicAgent without expert attributes on the pinned KB path."""
    bot = _legacy_bot()

    assert not hasattr(bot, "knowledge_resolver")
    assert await bot._build_kb_context("What is pinned?", user_id="user", session_id="session") == (
        "## Primary:\n* primary answer\n\n## Secondary:\n* secondary answer",
        {
            "activated_kbs": [
                {"name": "Primary", "confidence": 1.0},
                {"name": "Secondary", "confidence": 1.0},
            ]
        },
    )
