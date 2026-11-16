"""Behavioral acceptance tests for final delivery exposure and trusted tool attribution."""

import asyncio
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import pytest

from parrot.memory.agent_memory.attribution import (
    ToolAttempt,
    bind_tool_event_capture,
    build_tool_signal,
    flush_tool_events,
    note_memory_exposure,
    reset_tool_event_capture,
    validate_citation,
)
from parrot.memory.agent_memory.models import MemoryRequestScope
from parrot.memory.agent_memory.runtime import bind_memory_exposure, reset_memory_exposure
from parrot.memory.dynamics.models import MemoryCitation, MemoryRef
from parrot.memory.episodic.backends.sqlite import SQLiteEpisodeBackend
from parrot.memory.episodic.models import EpisodicMemory, MemoryNamespace
from parrot.memory.episodic.store import EpisodicMemoryStore
from parrot.memory.unified.manager import UnifiedMemoryManager
from parrot.memory.unified.models import MemoryCandidate, MemoryConfig
from parrot.tools.abstract import ToolResult
from parrot.tools.manager import ToolManager, _Observation

NOW = datetime(2026, 1, 2, tzinfo=UTC)


def _scope(*, tenant_id: str = "tenant-a", turn_id: str = "turn-a") -> MemoryRequestScope:
    """Return a deterministic trusted invocation scope."""
    return MemoryRequestScope(
        tenant_id=tenant_id,
        agent_id="agent-a",
        user_id="user-a",
        session_id="session-a",
        turn_id=turn_id,
        identity_provenance="runtime_derived",
    )


def _namespace(*, tenant_id: str = "tenant-a") -> MemoryNamespace:
    """Return the episodic namespace matching the default request scope."""
    return MemoryNamespace(
        tenant_id=tenant_id,
        agent_id="agent-a",
        user_id="user-a",
        session_id="session-a",
    )


def _candidate(memory_id: str, text: str, scope: MemoryRequestScope) -> MemoryCandidate:
    """Build one versioned episodic candidate."""
    return MemoryCandidate(
        scope=scope,
        memory_id=memory_id,
        content_version="v1",
        source="episodic",
        text=text,
        relevance=1.0,
        candidate_type="episodic",
    )


def _episode(memory_id: str, *, error_message: str = "boom") -> EpisodicMemory:
    """Build one deterministic failed episode for real review application."""
    namespace = _namespace()
    return EpisodicMemory(
        episode_id=memory_id,
        tenant_id=namespace.tenant_id,
        agent_id=namespace.agent_id,
        user_id=namespace.user_id,
        session_id=namespace.session_id,
        situation="A tool failed",
        action_taken="Ran the tool",
        outcome="failure",
        error_message=error_message,
        created_at=datetime(2026, 1, 1, tzinfo=UTC),
    )


class _CaptureManager:
    """Collect request-local events without adding shared mutable state."""

    def __init__(self) -> None:
        self.events: list[Any] = []

    async def record_event(self, event: Any) -> None:
        """Collect one flushed event."""
        self.events.append(event)


class _TaskObserver:
    """Record FEAT-538 observer ordering and values."""

    def __init__(self) -> None:
        self.calls: list[tuple[str, Any]] = []

    async def begin(self, tool_name: str) -> str:
        """Record observer entry before the body."""
        self.calls.append(("begin", tool_name))
        return tool_name

    async def finish(self, observed: str, *, value: Any = None, exception: BaseException | None = None) -> None:
        """Record the unchanged body result or exception."""
        self.calls.append(("finish", exception if exception is not None else value))

    async def cancelled(self, observed: str) -> None:
        """Record cancellation without swallowing it."""
        self.calls.append(("cancelled", observed))


def test_final_packing_controls_citable_refs() -> None:
    """Verify final packing controls citable refs and hides cross-scope details."""
    scope = _scope()
    store = EpisodicMemoryStore(SQLiteEpisodeBackend(":memory:"), default_ttl_days=0)
    manager = UnifiedMemoryManager(
        _namespace(),
        episodic_store=store,
        config=MemoryConfig(max_context_tokens=40),
    )
    context = manager._assembler.assemble_candidates(
        [
            _candidate("delivered", "fits the budget", scope),
            _candidate("trimmed", "x" * 200, scope),
        ],
        scope=scope,
    )
    committed = manager.commit_memory_exposure(context, scope=scope)

    assert context.delivered_refs == ("episodic:delivered:v1",)
    assert committed.exposure_id is not None
    exposure = manager._memory_exposures[committed.exposure_id]
    delivered = MemoryCitation(exposure_id=committed.exposure_id, refs=exposure.refs)
    assert validate_citation(delivered, exposure, scope=scope) == delivered

    trimmed_ref = MemoryRef(
        namespace=_namespace(),
        kind="episode",
        memory_id="trimmed",
        content_version="v1",
    )
    with pytest.raises(ValueError, match="unavailable"):
        validate_citation(
            MemoryCitation(exposure_id=committed.exposure_id, refs=(trimmed_ref,)),
            exposure,
            scope=scope,
        )
    with pytest.raises(ValueError, match="unavailable"):
        validate_citation(delivered, exposure, scope=_scope(tenant_id="tenant-b"))
    with pytest.raises(ValueError, match="unavailable"):
        validate_citation(delivered.model_copy(update={"exposure_id": "stale"}), exposure, scope=scope)


@pytest.mark.asyncio
async def test_guard_denial_and_cancellation_no_success() -> None:
    """Verify bodies that never ran and cancelled providers earn no review."""
    scope = _scope()
    tool_manager = ToolManager()
    capture_manager = _CaptureManager()
    capture_token = bind_tool_event_capture(scope, capture_manager)
    try:
        missing = await tool_manager.execute_tool("missing", {})
        assert isinstance(missing, ToolResult)

        async def cancelled_body() -> None:
            """Simulate cancellation inside a body that did run."""
            raise asyncio.CancelledError

        with pytest.raises(asyncio.CancelledError):
            await tool_manager._observed(None, "cancelled", cancelled_body)
    finally:
        reset_tool_event_capture(capture_token)

    assert capture_manager.events == []

    manager = UnifiedMemoryManager(_namespace(), episodic_store=EpisodicMemoryStore(SQLiteEpisodeBackend(":memory:")))
    context = manager._assembler.assemble_candidates([_candidate("episode-a", "delivered", scope)], scope=scope)
    committed = manager.commit_memory_exposure(context, scope=scope)
    assert committed.exposure_id is not None
    failed_token = bind_tool_event_capture(scope, manager)
    try:
        note_memory_exposure(committed.exposure_id)
    finally:
        reset_tool_event_capture(failed_token)
    assert manager.activate_memory_exposure(committed.exposure_id, scope) is False


@pytest.mark.asyncio
async def test_task_observer_and_memory_capture_coexist() -> None:
    """Verify FEAT-538 observation runs before isolated memory capture."""
    tool_manager = ToolManager()
    observer = _TaskObserver()
    tool_manager.set_invocation_observer(observer)
    capture_manager = _CaptureManager()
    scope = _scope()
    capture_token = bind_tool_event_capture(scope, capture_manager)
    try:
        observation = _Observation()

        async def body() -> str:
            """Return the value both observers must preserve."""
            return "result"

        assert await tool_manager._observed(observation, "lookup", body) == "result"
        await flush_tool_events()
    finally:
        reset_tool_event_capture(capture_token)

    assert observation.executed is True
    assert observer.calls == [("begin", "lookup"), ("finish", "result")]
    assert len(capture_manager.events) == 1
    attempt = capture_manager.events[0].payload["attempt"]
    assert attempt.terminal == "returned"
    assert attempt.first_attempt is True

    async def isolated_call(turn_id: str) -> ToolAttempt:
        """Run one concurrent invocation on the shared manager."""
        local_manager = _CaptureManager()
        local_token = bind_tool_event_capture(_scope(turn_id=turn_id), local_manager)
        try:
            assert await tool_manager._observed(None, "shared", body) == "result"
            await flush_tool_events()
        finally:
            reset_tool_event_capture(local_token)
        return local_manager.events[0].payload["attempt"]

    first, second = await asyncio.gather(isolated_call("turn-1"), isolated_call("turn-2"))
    assert first.first_attempt is True
    assert second.first_attempt is True
    assert first.call_id != second.call_id


@pytest.mark.asyncio
async def test_structural_recovery_and_citation_channel(tmp_path: Path) -> None:
    """Verify only explicit or raised cited failures produce one durable AGAIN review."""
    default_result = ToolResult(result="ok")
    explicit_failure = ToolResult(success=False, error="  BOOM  ", result=None)
    returned_attempt = ToolAttempt(
        tool_name="lookup",
        call_id="returned-a",
        terminal="returned",
        observed_at=NOW,
        first_attempt=True,
        correction_count=0,
        returned=default_result,
    )
    failure_attempt = returned_attempt.__class__(
        tool_name="lookup",
        call_id="failure-a",
        terminal="returned",
        observed_at=NOW,
        first_attempt=False,
        correction_count=0,
        returned=explicit_failure,
    )
    incomplete = build_tool_signal(
        returned_attempt,
        scope=_scope(),
        evidence_ref="chatstorage/v1/tenant-a/agent-a/user-a/session-a/turn-a",
    )
    failed = build_tool_signal(
        failure_attempt,
        scope=_scope(),
        evidence_ref="chatstorage/v1/tenant-a/agent-a/user-a/session-a/turn-a",
    )
    assert incomplete is not None and incomplete.outcome == "incomplete" and not incomplete.can_review
    assert failed is not None and failed.outcome == "failure"
    assert failed.error_signature == "boom"
    assert failed.passed_check_ids == ()
    empty_error = build_tool_signal(
        failure_attempt.__class__(
            tool_name="lookup",
            call_id="failure-empty",
            terminal="returned",
            observed_at=NOW,
            first_attempt=False,
            correction_count=1,
            returned=ToolResult(success=False, error=" ", result=None),
        ),
        scope=_scope(),
        evidence_ref="chatstorage/v1/tenant-a/agent-a/user-a/session-a/turn-a",
    )
    assert empty_error is not None and empty_error.error_signature == "success"
    status_failure = build_tool_signal(
        failure_attempt.__class__(
            tool_name="lookup",
            call_id="failure-status",
            terminal="returned",
            observed_at=NOW,
            first_attempt=False,
            correction_count=1,
            returned=ToolResult(status="failed", result=None),
        ),
        scope=_scope(),
        evidence_ref="chatstorage/v1/tenant-a/agent-a/user-a/session-a/turn-a",
    )
    dict_result = build_tool_signal(
        returned_attempt.__class__(
            tool_name="lookup",
            call_id="dict-result",
            terminal="returned",
            observed_at=NOW,
            first_attempt=False,
            correction_count=1,
            returned={"success": False, "error": "boom"},
        ),
        scope=_scope(),
        evidence_ref="chatstorage/v1/tenant-a/agent-a/user-a/session-a/turn-a",
    )
    assert status_failure is not None and status_failure.error_signature == "failed"
    assert dict_result is not None and dict_result.outcome == "incomplete"

    backend = SQLiteEpisodeBackend(tmp_path / "attribution.sqlite")
    await backend.configure()
    store = EpisodicMemoryStore(backend, default_ttl_days=0)
    manager = UnifiedMemoryManager(_namespace(), episodic_store=store)
    scope = _scope()
    try:
        await backend.store(_episode("episode-a"))
        context = manager._assembler.assemble_candidates(
            [_candidate("episode-a", "Use the cited recovery", scope)],
            scope=scope,
        )
        committed = manager.commit_memory_exposure(context, scope=scope)
        assert committed.exposure_id is not None
        await store.cite(["episode-a"], namespace=_namespace(), exposure_id=committed.exposure_id)

        capture_token = bind_tool_event_capture(scope, manager)
        exposure_token = bind_memory_exposure(committed.exposure_id)
        try:
            note_memory_exposure(committed.exposure_id)
            tool_manager = ToolManager()

            async def raises() -> None:
                """Produce the exact stored failure signature."""
                raise RuntimeError("boom")

            with pytest.raises(RuntimeError, match="boom"):
                await tool_manager._observed(None, "lookup", raises)
            await flush_tool_events()
        finally:
            reset_memory_exposure(exposure_token)
            reset_tool_event_capture(capture_token)

        assert backend._db is not None
        cursor = await backend._db.execute("SELECT COUNT(*) FROM reviews")
        assert (await cursor.fetchone())[0] == 1
        assert manager.activate_memory_exposure(committed.exposure_id, scope) is False
        assert "episode-a" not in context.to_prompt_string()
        assert committed.exposure_id not in context.to_prompt_string()
    finally:
        await backend.close()
