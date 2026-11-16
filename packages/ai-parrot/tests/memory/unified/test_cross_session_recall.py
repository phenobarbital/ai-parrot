"""Factory-to-store-to-prompt cross-session proof without network calls."""

import json
from datetime import datetime, timezone
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest

from parrot.memory.agent_memory.factory import create_memory_manager
from parrot.memory.agent_memory.models import AgentMemoryConfig, MemoryEvent, MemoryRequestScope
from parrot.memory.episodic.models import MemoryNamespace
from parrot.memory.unified.manager import UnifiedMemoryManager


class FakeExtractionClient:
    """Return fixed explicit knowledge and record extraction prompts."""

    model = "fixture"

    def __init__(self) -> None:
        """Initialize the recorded extraction-call list."""
        self.calls: list[dict[str, Any]] = []

    async def ask(self, prompt: str, **kwargs: Any) -> SimpleNamespace:
        """Return a deterministic Spanish preference without network access."""
        self.calls.append({"prompt": prompt, **kwargs})
        return SimpleNamespace(
            output=json.dumps(
                [
                    {
                        "kind": "preference",
                        "normalized_key": "response_length",
                        "value": "Prefiere respuestas cortas",
                        "provenance": "explicit",
                    }
                ]
            )
        )


def _scope(tenant_id: str, user_id: str, session_id: str, turn_id: str) -> MemoryRequestScope:
    """Build an explicit immutable runtime scope for one test turn."""
    return MemoryRequestScope(
        tenant_id=tenant_id,
        agent_id="memory-test-agent",
        user_id=user_id,
        session_id=session_id,
        turn_id=turn_id,
        identity_provenance="runtime_derived",
    )


async def _manager(path: Path, tenant_id: str) -> UnifiedMemoryManager:
    """Build the production manager against a shared SQLite file."""
    return await create_memory_manager(
        AgentMemoryConfig(
            enable_episodic_memory=True,
            enable_user_memory=True,
            storage_path=str(path),
            max_episodic_warnings=0,
        ),
        namespace=MemoryNamespace(tenant_id=tenant_id, agent_id="memory-test-agent"),
    )


def _response_event(event_id: str, scope: MemoryRequestScope, query: str) -> MemoryEvent:
    """Create one UTC response event that records both memory planes."""
    return MemoryEvent(
        event_id=event_id,
        kind="response",
        scope=scope,
        observed_at=datetime(2026, 11, 16, tzinfo=timezone.utc),
        payload={"query": query, "response": "La respuesta fue guardada para la próxima sesión."},
    )


@pytest.mark.asyncio
async def test_user_knowledge_reaches_new_session(tmp_path: Path) -> None:
    """Reopened managers deliver learned preferences for unrelated questions."""
    database = tmp_path / "memory.sqlite3"
    session_a = _scope("acme", "alice", "session-a", "turn-a")
    extractor = FakeExtractionClient()
    first_manager = await _manager(database, "acme")
    first_manager.extraction_client = extractor
    try:
        receipt = await first_manager.record_event(
            _response_event("event-a", session_a, "Me gustan las respuestas cortas.")
        )
        assert receipt.knowledge_ids
        assert extractor.calls
        system_prompt = extractor.calls[0]["system_prompt"]
        assert "Record only lasting statements about the user as a person." in system_prompt
        assert "Write every value in the language the user used." in system_prompt
    finally:
        await first_manager.cleanup()

    second_manager = await _manager(database, "acme")
    try:
        context = await second_manager.prepare_context(
            "¿Cuál es la capital de Australia?", scope=_scope("acme", "alice", "session-b", "turn-b")
        )
        assert "Prefiere respuestas cortas" in context.user_knowledge
    finally:
        await second_manager.cleanup()


@pytest.mark.asyncio
async def test_episode_from_earlier_session_is_recalled(tmp_path: Path) -> None:
    """New-session queries recall the earlier matching interaction."""
    database = tmp_path / "memory.sqlite3"
    session_a = _scope("acme", "alice", "session-a", "turn-a")
    query = "La capital de Australia es Canberra"
    first_manager = await _manager(database, "acme")
    first_manager.extraction_client = FakeExtractionClient()
    try:
        receipt = await first_manager.record_event(_response_event("event-a", session_a, query))
        assert len(receipt.episode_ids) == 1
        episode_id = receipt.episode_ids[0]
    finally:
        await first_manager.cleanup()

    second_manager = await _manager(database, "acme")
    try:
        context = await second_manager.prepare_context(
            query, scope=_scope("acme", "alice", "session-b", "turn-b")
        )
        assert query in context.episodic_recall
        assert f"episodic:{episode_id}:v1" in context.delivered_refs
        assert any(ref.memory_id == episode_id for ref in context.memory_refs)
    finally:
        await second_manager.cleanup()


@pytest.mark.asyncio
async def test_same_session_episode_is_not_recalled(tmp_path: Path) -> None:
    """The originating session excludes its own interaction."""
    manager = await _manager(tmp_path / "memory.sqlite3", "acme")
    manager.extraction_client = FakeExtractionClient()
    scope = _scope("acme", "alice", "session-a", "turn-a")
    query = "La capital de Australia es Canberra"
    try:
        receipt = await manager.record_event(_response_event("event-a", scope, query))
        context = await manager.prepare_context(query, scope=scope)
        assert context.episodic_recall == ""
        assert f"episodic:{receipt.episode_ids[0]}:v1" not in context.delivered_refs
    finally:
        await manager.cleanup()


@pytest.mark.asyncio
async def test_other_user_sees_nothing(tmp_path: Path) -> None:
    """Another user or tenant receives neither private facts nor episodes."""
    database = tmp_path / "memory.sqlite3"
    source_manager = await _manager(database, "acme")
    source_manager.extraction_client = FakeExtractionClient()
    query = "La capital de Australia es Canberra"
    try:
        await source_manager.record_event(
            _response_event("event-a", _scope("acme", "alice", "session-a", "turn-a"), query)
        )
    finally:
        await source_manager.cleanup()

    other_user_manager = await _manager(database, "acme")
    try:
        other_user_context = await other_user_manager.prepare_context(
            query, scope=_scope("acme", "bob", "session-b", "turn-b")
        )
        assert other_user_context.user_knowledge == ""
        assert other_user_context.episodic_recall == ""
    finally:
        await other_user_manager.cleanup()

    other_tenant_manager = await _manager(database, "globex")
    try:
        other_tenant_context = await other_tenant_manager.prepare_context(
            query, scope=_scope("globex", "alice", "session-c", "turn-c")
        )
        assert other_tenant_context.user_knowledge == ""
        assert other_tenant_context.episodic_recall == ""
    finally:
        await other_tenant_manager.cleanup()
