"""Behavioral acceptance tests for the cooperative AgentMemoryMixin facade."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

import pytest

from parrot.memory.agent_memory.mixin import AgentMemoryMixin
from parrot.memory.agent_memory.models import MemoryEvent, MemoryRequestScope
from parrot.memory.unified.models import MemoryContext


class _HostLifecycle:
    """Model the AbstractBot configure guard and observable host cleanup."""

    def __init__(self, events: list[str] | None = None) -> None:
        """Initialize host lifecycle state."""
        self.name = "facade-agent"
        self.tenant_id = "tenant-1"
        self.app: Any = None
        self.configure_skipped = False
        self.configure_count = 0
        self.events = events if events is not None else []

    async def configure(self, app: Any = None) -> None:
        """Apply the host's same-app idempotency rule."""
        is_noop = self.configure_count >= 1 and (app is None or app is self.app)
        self.configure_count += 1
        self.configure_skipped = is_noop
        if not is_noop:
            self.app = app
            self.events.append("host.configure")

    async def cleanup(self) -> None:
        """Record host resource cleanup."""
        self.events.append("host.cleanup")


class _Facade(AgentMemoryMixin, _HostLifecycle):
    """Concrete cooperative host used by facade acceptance tests."""

    enable_episodic_memory = True

    def __init__(self, events: list[str] | None = None) -> None:
        """Initialize only the concrete host; the mixin has no constructor contract."""
        super().__init__(events)
        self.agent_memory_config = {"storage_path": "/tmp/facade-memory.sqlite3"}


class _RaisingHost(_HostLifecycle):
    """Represent a host whose conversation-memory setup fails before facade acquisition."""

    async def configure(self, app: Any = None) -> None:
        """Raise the original host configuration error unchanged."""
        raise RuntimeError("host conversation memory failed")


class _RaisingFacade(AgentMemoryMixin, _RaisingHost):
    """Concrete facade used to verify host-first acquisition ordering."""

    enable_episodic_memory = True
    agent_memory_config = {"storage_path": "/tmp/facade-memory.sqlite3"}


class _Manager:
    """Observe facade delegation without replacing the host lifecycle."""

    def __init__(self, events: list[str] | None = None, *, fail_configure: bool = False) -> None:
        """Initialize observable manager state."""
        self.events = events if events is not None else []
        self.fail_configure = fail_configure
        self.configure_count = 0
        self.cleanup_count = 0
        self.brain_service: Any = None
        self.episodic = object()

    async def configure(self) -> None:
        """Record configuration and optionally fail after acquisition."""
        self.configure_count += 1
        self.events.append("manager.configure")
        if self.fail_configure:
            raise RuntimeError("manager setup failed")

    async def cleanup(self) -> None:
        """Record owned-resource cleanup."""
        self.cleanup_count += 1
        self.events.append("manager.cleanup")

    async def prepare_context(self, query: str, *, scope: MemoryRequestScope) -> MemoryContext:
        """Return an observable scoped context."""
        return MemoryContext(user_knowledge=f"{scope.tenant_id}:{query}")

    async def record_event(self, event: MemoryEvent) -> object:
        """Record one completed event synchronously with the caller."""
        self.events.append(f"manager.record:{event.event_id}")
        return object()


@pytest.mark.asyncio
async def test_configure_repeat_and_changed_app(monkeypatch: pytest.MonkeyPatch) -> None:
    """Verify repeat skips, changed app rebinds, and partial initialization unwinds."""
    manager = _Manager()
    factory_calls: list[tuple[object, object]] = []

    async def create_manager(config: object, *, namespace: object) -> _Manager:
        factory_calls.append((config, namespace))
        return manager

    monkeypatch.setattr("parrot.memory.agent_memory.mixin.create_memory_manager", create_manager)
    subject = _Facade()
    first_app = object()
    second_app = object()

    await subject.configure(first_app)
    await subject.configure(first_app)
    await subject.configure(second_app)

    assert len(factory_calls) == 1
    assert manager.configure_count == 2
    assert subject.configure_count == 3
    assert subject._memory_manager is manager

    failing_manager = _Manager(fail_configure=True)

    async def create_failing_manager(config: object, *, namespace: object) -> _Manager:
        return failing_manager

    monkeypatch.setattr("parrot.memory.agent_memory.mixin.create_memory_manager", create_failing_manager)
    failing_subject = _Facade()
    with pytest.raises(RuntimeError, match="manager setup failed"):
        await failing_subject.configure(object())
    assert failing_manager.cleanup_count == 1
    assert failing_subject._memory_manager is None

    host_failure_factory_calls = 0

    async def should_not_create_manager(config: object, *, namespace: object) -> _Manager:
        nonlocal host_failure_factory_calls
        host_failure_factory_calls += 1
        return _Manager()

    monkeypatch.setattr("parrot.memory.agent_memory.mixin.create_memory_manager", should_not_create_manager)
    host_failure = _RaisingFacade()
    with pytest.raises(RuntimeError, match="host conversation memory failed"):
        await host_failure.configure(object())
    assert host_failure_factory_calls == 0


@pytest.mark.asyncio
async def test_lazy_missing_brain_and_public_service(monkeypatch: pytest.MonkeyPatch) -> None:
    """Verify disabled brain needs no sibling service and the facade export remains lazy."""
    manager = _Manager()

    async def create_manager(config: object, *, namespace: object) -> _Manager:
        return manager

    monkeypatch.setattr("parrot.memory.agent_memory.mixin.create_memory_manager", create_manager)
    subject = _Facade()
    subject.enable_episodic_memory = False
    subject.agent_memory_config = None

    await subject.configure(object())

    scope = MemoryRequestScope(
        tenant_id="tenant-1",
        agent_id=subject.name,
        turn_id="turn-lazy",
        identity_provenance="server_resolved",
    )
    context = await subject.prepare_memory("remember this", scope=scope)

    from parrot.memory.agent_memory import AgentMemoryMixin as PublicAgentMemoryMixin

    assert PublicAgentMemoryMixin is AgentMemoryMixin
    assert subject.brain_service is None
    assert manager.brain_service is None
    assert context.user_knowledge == "tenant-1:remember this"


@pytest.mark.asyncio
async def test_stop_drain_before_host_cleanup(monkeypatch: pytest.MonkeyPatch) -> None:
    """Verify completed writes drain and manager cleanup precedes host cleanup."""
    events: list[str] = []
    manager = _Manager(events)

    async def create_manager(config: object, *, namespace: object) -> _Manager:
        return manager

    monkeypatch.setattr("parrot.memory.agent_memory.mixin.create_memory_manager", create_manager)
    subject = _Facade(events)
    await subject.configure(object())
    scope = MemoryRequestScope(
        tenant_id="tenant-1",
        agent_id=subject.name,
        user_id="user-1",
        session_id="session-1",
        turn_id="turn-1",
        identity_provenance="server_resolved",
    )
    event = MemoryEvent(
        event_id=scope.response_event_id(),
        kind="response",
        scope=scope,
        observed_at=datetime(2026, 11, 16, tzinfo=UTC),
        payload={"query": "hello", "response": "world"},
    )

    await subject.complete_memory(event)
    await subject.cleanup()

    assert events[-3:] == [f"manager.record:{event.event_id}", "manager.cleanup", "host.cleanup"]
    assert subject._memory_manager is None


class _RecordingToolManager:
    """Observe tool registration without a real ToolManager."""

    def __init__(self) -> None:
        self.registered: list[str] = []
        self.unregistered: list[str] = []

    def register_tool(self, tool: Any) -> None:
        self.registered.append(tool.name)

    def unregister_tool(self, name: str) -> bool:
        self.unregistered.append(name)
        return True


class _ToolFacade(_Facade):
    """Host that owns a tool manager and an LLM client, like a real bot."""

    def __init__(self, events: list[str] | None = None) -> None:
        super().__init__(events)
        self.tool_manager = _RecordingToolManager()
        self.client_calls = 0

    def get_client(self) -> object:
        self.client_calls += 1
        return self._client

    _client = object()


class _ToolManagerManager(_Manager):
    """Manager double that exposes what the toolkit and extraction wiring read."""

    def __init__(self, events: list[str] | None = None) -> None:
        super().__init__(events)
        from types import SimpleNamespace

        from parrot.memory.episodic.models import MemoryNamespace

        self.namespace = MemoryNamespace(tenant_id="tenant-1", agent_id="facade-agent")
        self.config = SimpleNamespace(enable_user_memory=True)
        self.extraction_client: object | None = None


@pytest.mark.asyncio
async def test_episodic_tools_register_once_and_are_removed_on_cleanup(monkeypatch: pytest.MonkeyPatch) -> None:
    """Configure registers the agent-facing episodic tools exactly once, and cleanup removes them again."""
    manager = _ToolManagerManager()

    async def create_manager(config: object, *, namespace: object) -> _ToolManagerManager:
        return manager

    monkeypatch.setattr("parrot.memory.agent_memory.mixin.create_memory_manager", create_manager)
    subject = _ToolFacade()

    await subject.configure(object())
    registered = list(subject.tool_manager.registered)
    await subject.configure(subject.app)

    assert registered and len(registered) == len(set(registered))
    assert any(name.endswith("cite_memory") for name in registered)
    assert subject.tool_manager.registered == registered

    await subject.cleanup()

    assert sorted(subject.tool_manager.unregistered) == sorted(registered)


@pytest.mark.asyncio
async def test_completion_binds_a_separate_extraction_factory(monkeypatch: pytest.MonkeyPatch) -> None:
    """User extraction binds its factory once and never borrows the response client."""
    manager = _ToolManagerManager()

    async def create_manager(config: object, *, namespace: object) -> _ToolManagerManager:
        return manager

    monkeypatch.setattr("parrot.memory.agent_memory.mixin.create_memory_manager", create_manager)
    subject = _ToolFacade()
    extraction_client = object()
    subject.memory_extraction_client_factory = lambda: extraction_client
    await subject.configure(object())
    scope = MemoryRequestScope(
        tenant_id="tenant-1", agent_id="facade-agent", turn_id="turn-1", identity_provenance="runtime_derived"
    )
    event = MemoryEvent(
        event_id="event-1", kind="response", scope=scope, observed_at=datetime.now(UTC), payload={"response": "ok"}
    )

    await subject.complete_memory(event)
    await subject._drain_memory_writes()  # extraction writes are detached and drained, never inline

    assert manager.extraction_client is None
    assert manager.extraction_client_factory() is extraction_client
    assert subject.client_calls == 0
    assert "manager.record:event-1" in manager.events

    manager.extraction_client = None

    def failing_client() -> object:
        raise RuntimeError("no client configured")

    subject.get_client = failing_client  # type: ignore[method-assign]
    await subject.complete_memory(event)
    await subject._drain_memory_writes()

    assert manager.extraction_client is None
    assert manager.events.count("manager.record:event-1") == 2
