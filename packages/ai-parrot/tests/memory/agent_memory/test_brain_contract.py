"""Behavioral acceptance tests for the lazy sibling brain-service boundary."""

from __future__ import annotations

import sys
from datetime import UTC, datetime
from typing import Any

import pytest

from parrot.memory.agent_memory.mixin import AgentMemoryMixin
from parrot.memory.agent_memory.models import MemoryEvent, MemoryRequestScope
from parrot.memory.unified.models import MemoryContext

class _Host:
    """Provide the cooperative lifecycle contract used by the facade."""

    def __init__(self, events: list[str] | None = None) -> None:
        """Initialize lifecycle state."""
        self.name = "brain-agent"
        self.tenant_id = "tenant-1"
        self.app: Any = None
        self.configure_skipped = False
        self.configure_count = 0
        self.events = events if events is not None else []

    async def configure(self, app: Any = None) -> None:
        """Skip only repeated configuration for the same application."""
        is_noop = self.configure_count >= 1 and (app is None or app is self.app)
        self.configure_count += 1
        self.configure_skipped = is_noop
        if not is_noop:
            self.app = app
            self.events.append("host.configure")

    async def cleanup(self) -> None:
        """Record host cleanup."""
        self.events.append("host.cleanup")


class _BrainFacade(AgentMemoryMixin, _Host):
    """Concrete brain-enabled cooperative facade."""

    enable_brain = True

    def __init__(self, events: list[str] | None = None) -> None:
        """Initialize the host and persistent-memory path."""
        super().__init__(events)
        self.agent_memory_config = {"storage_path": "/tmp/brain-memory.sqlite3"}


class _Manager:
    """Observe manager lifecycle and brain-service injection."""

    def __init__(self, events: list[str]) -> None:
        """Initialize manager state."""
        self.events = events
        self.configure_count = 0
        self.cleanup_count = 0
        self.episodic = object()
        self.brain_service: Any = None

    async def configure(self) -> None:
        """Record manager configuration."""
        self.configure_count += 1
        self.events.append("manager.configure")

    async def cleanup(self) -> None:
        """Record manager cleanup."""
        self.cleanup_count += 1
        self.events.append("manager.cleanup")


class _BrainService:
    """Injected fake matching only the future sibling's public service boundary."""

    def __init__(self, events: list[str]) -> None:
        """Initialize service counters."""
        self.events = events
        self.start_count = 0
        self.stop_count = 0

    async def start(self) -> None:
        """Record idempotent startup requests."""
        self.start_count += 1
        self.events.append("brain.start")

    async def stop(self) -> None:
        """Record idempotent shutdown requests."""
        self.stop_count += 1
        self.events.append("brain.stop")

    async def search(self, query: str, tenant_id: str, max_tokens: int = 600) -> str:
        """Return tenant-bound fake content."""
        return f"{tenant_id}:{query}:{max_tokens}"

    async def forget_derived(self, tenant_id: str, episodes: list[object]) -> list[str]:
        """Return fake deleted derivative identifiers."""
        return [f"{tenant_id}:{len(episodes)}"]


class _FailingBrainService(_BrainService):
    """Simulate a partially started sibling service that must be stopped."""

    async def start(self) -> None:
        """Acquire observable state and then fail startup."""
        await super().start()
        raise RuntimeError("brain startup failed")


@pytest.mark.asyncio
async def test_configure_repeat_and_changed_app(monkeypatch: pytest.MonkeyPatch) -> None:
    """Verify one brain instance starts once while a changed app rebinds the manager."""
    events: list[str] = []
    manager = _Manager(events)
    brain = _BrainService(events)

    async def create_manager(config: object, *, namespace: object) -> _Manager:
        return manager

    monkeypatch.setattr("parrot.memory.agent_memory.mixin.create_memory_manager", create_manager)
    subject = _BrainFacade(events)
    subject.brain_service = brain
    first_app = object()
    second_app = object()

    await subject.configure(first_app)
    await subject.configure(first_app)
    await subject.configure(second_app)

    assert subject.brain_service is brain
    assert manager.brain_service is brain
    assert brain.start_count == 1
    assert manager.configure_count == 2


@pytest.mark.asyncio
async def test_lazy_missing_brain_and_public_service(monkeypatch: pytest.MonkeyPatch) -> None:
    """Verify an unavailable enabled service is invalid while disabled mode imports nothing."""
    disabled_events: list[str] = []
    disabled_manager = _Manager(disabled_events)

    async def create_disabled_manager(config: object, *, namespace: object) -> _Manager:
        return disabled_manager

    monkeypatch.setattr("parrot.memory.agent_memory.mixin.create_memory_manager", create_disabled_manager)
    disabled = _BrainFacade(disabled_events)
    disabled.enable_brain = False
    await disabled.configure(object())
    assert disabled.brain_service is None

    enabled_events: list[str] = []
    enabled_manager = _Manager(enabled_events)

    async def create_enabled_manager(config: object, *, namespace: object) -> _Manager:
        return enabled_manager

    monkeypatch.setattr("parrot.memory.agent_memory.mixin.create_memory_manager", create_enabled_manager)
    monkeypatch.setitem(sys.modules, "parrot.memory.dream.service", None)
    enabled = _BrainFacade(enabled_events)

    with pytest.raises(ValueError, match="invalid_configuration: brain service is unavailable"):
        await enabled.configure(object())
    assert enabled_manager.cleanup_count == 1
    assert enabled._memory_manager is None

    startup_events: list[str] = []
    startup_manager = _Manager(startup_events)

    async def create_startup_manager(config: object, *, namespace: object) -> _Manager:
        return startup_manager

    monkeypatch.setattr("parrot.memory.agent_memory.mixin.create_memory_manager", create_startup_manager)
    startup_failure = _BrainFacade(startup_events)
    failing_brain = _FailingBrainService(startup_events)
    startup_failure.brain_service = failing_brain
    with pytest.raises(RuntimeError, match="brain startup failed"):
        await startup_failure.configure(object())
    assert startup_events[-3:] == ["brain.start", "brain.stop", "manager.cleanup"]
    assert failing_brain.stop_count == 1


@pytest.mark.asyncio
async def test_stop_drain_before_host_cleanup(monkeypatch: pytest.MonkeyPatch) -> None:
    """Verify brain stop and manager drain both precede host resource cleanup."""
    events: list[str] = []
    manager = _Manager(events)
    brain = _BrainService(events)

    async def create_manager(config: object, *, namespace: object) -> _Manager:
        return manager

    monkeypatch.setattr("parrot.memory.agent_memory.mixin.create_memory_manager", create_manager)
    subject = _BrainFacade(events)
    subject.brain_service = brain

    await subject.configure(object())
    await subject.cleanup()
    await subject.cleanup()

    assert events[-4:] == ["brain.stop", "manager.cleanup", "host.cleanup", "host.cleanup"]
    assert brain.stop_count == 1
    assert not hasattr(subject, "brain_admin_toolkit")


@pytest.mark.asyncio
async def test_facade_keeps_scope_and_response_event_at_the_public_boundary() -> None:
    """Verify the facade relays one immutable tenant scope and response event unchanged."""
    subject = _BrainFacade()
    manager = _Manager([])
    scopes: list[MemoryRequestScope] = []
    events: list[MemoryEvent] = []

    async def prepare_context(query: str, *, scope: MemoryRequestScope) -> MemoryContext:
        """Observe the scope supplied by the public facade."""
        scopes.append(scope)
        return MemoryContext(semantic_knowledge=f"{scope.tenant_id}:{query}")

    async def record_event(event: MemoryEvent) -> None:
        """Observe the event supplied by the public facade."""
        events.append(event)

    manager.prepare_context = prepare_context
    manager.record_event = record_event
    subject._memory_manager = manager
    scope = MemoryRequestScope(
        tenant_id="tenant-1",
        agent_id="brain-agent",
        user_id="user-1",
        session_id="session-1",
        turn_id="turn-1",
        identity_provenance="server_resolved",
    )
    context = await subject.prepare_memory("question", scope=scope)
    event = MemoryEvent(
        event_id=scope.response_event_id(),
        kind="response",
        scope=scope,
        observed_at=datetime.now(UTC),
        payload={"query": "question", "response": "answer"},
    )
    await subject.complete_memory(event)

    assert context.semantic_knowledge == "tenant-1:question"
    assert scopes == [scope]
    assert events == [event]
