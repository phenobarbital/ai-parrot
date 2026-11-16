"""Deterministic ownership regressions for detached user-memory extraction."""

from __future__ import annotations

import asyncio
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import pytest

from parrot.clients.models import LLMConfig
from parrot.memory.agent_memory.factory import create_memory_manager
from parrot.memory.agent_memory.mixin import AgentMemoryMixin
from parrot.memory.agent_memory.models import AgentMemoryConfig, MemoryEvent, MemoryRequestScope
from parrot.memory.episodic.models import MemoryNamespace


class _Lifecycle:
    """Observe whether owned writes finish before the host is closed."""

    async def cleanup(self) -> None:
        """Mark host resource shutdown."""
        self.closed = True


class _Host(AgentMemoryMixin, _Lifecycle):
    """Minimal cooperative host using a real independently owned memory manager."""

    def __init__(self, manager: Any) -> None:
        """Retain the manager and an unrelated live response client."""
        self._memory_manager = manager
        self._llm = object()
        self.closed = False
        self.draining = asyncio.Event()

    async def _drain_memory_writes(self) -> None:
        """Signal shutdown admission before awaiting owned writes."""
        self.draining.set()
        await super()._drain_memory_writes()


def _event(user: str) -> MemoryEvent:
    """Make a scoped, retry-stable completed turn."""
    scope = MemoryRequestScope(
        tenant_id="tenant", agent_id="agent", user_id=user, turn_id="turn", identity_provenance="server_resolved"
    )
    return MemoryEvent(
        event_id=scope.response_event_id(),
        kind="response",
        scope=scope,
        observed_at=datetime.now(UTC),
        payload={"query": user, "response": "ok"},
    )


@pytest.mark.asyncio
@pytest.mark.parametrize("cancel_cleanup", [False, True])
async def test_concurrent_extraction_owns_clients_and_cleanup_drains(tmp_path: Path, cancel_cleanup: bool) -> None:
    """Responses return while distinct clients are blocked, and cleanup closes resources only after both finish."""
    manager = await create_memory_manager(
        AgentMemoryConfig(enable_user_memory=True, storage_path=str(tmp_path / "memory.db")),
        namespace=MemoryNamespace(tenant_id="tenant", agent_id="agent"),
    )
    host = _Host(manager)
    entered = asyncio.Event()
    release = asyncio.Event()
    clients: list[Any] = []

    class Client:
        """Hold extraction until both requests have entered independent client contexts."""

        def __init__(self, **kwargs: Any) -> None:
            """Capture construction so resolved configuration is exercised."""
            self.options = kwargs
            self.closed = False
            self.exited = False
            clients.append(self)

        async def __aenter__(self) -> Client:
            """Return this independently owned client."""
            return self

        async def __aexit__(self, *args: Any) -> None:
            """Context exit alone does not own provider SDK cleanup."""
            self.exited = True

        async def close(self) -> None:
            """Close the independently owned SDK resources after context exit."""
            assert self.exited
            self.closed = True

        async def ask(self, prompt: str, **kwargs: Any) -> str:
            """Propose one explicit user fact once both calls are outstanding."""
            if len(clients) == 2:
                entered.set()
            await release.wait()
            return '[{"kind":"fact","value":"likes tea","provenance":"explicit"}]'

    host._llm_config = LLMConfig(client_class=Client, model="offline", extra={"custom": "kept"})
    events = [_event("alice"), _event("bob")]
    cleanup: asyncio.Task[None] | None = None
    try:
        for event in events:
            await asyncio.wait_for(host.complete_memory(event), 1)
        await asyncio.wait_for(entered.wait(), 1)
        assert len(clients) == 2 and clients[0] is not clients[1]
        assert all(c.options["model"] == "offline" and c.options["custom"] == "kept" for c in clients)
        assert manager.extraction_client is None
        cleanup = asyncio.create_task(host.cleanup())
        await asyncio.wait_for(host.draining.wait(), 1)
        assert not host.closed
        if cancel_cleanup:
            cleanup.cancel()
        release.set()
        if cancel_cleanup:
            with pytest.raises(asyncio.CancelledError):
                await asyncio.wait_for(cleanup, 1)
        else:
            await asyncio.wait_for(cleanup, 1)
        assert host.closed and all(c.closed for c in clients)
        assert not host.__dict__["_memory_write_tasks"]
    finally:
        release.set()
        if cleanup is not None:
            await asyncio.gather(cleanup, return_exceptions=True)
        await manager.cleanup()


@pytest.mark.asyncio
async def test_factory_cannot_borrow_response_client(tmp_path: Path) -> None:
    """A misconfigured factory is rejected before entering the response client's context."""
    manager = await create_memory_manager(
        AgentMemoryConfig(enable_user_memory=True, storage_path=str(tmp_path / "memory.db")),
        namespace=MemoryNamespace(tenant_id="tenant", agent_id="agent"),
    )
    host = _Host(manager)
    host.memory_extraction_client_factory = lambda: host._llm
    host._bind_extraction_client(manager)
    with pytest.raises(ValueError, match="independent client"):
        manager.extraction_client_factory()
    receipt = await manager.record_event(_event("alice"))
    assert receipt.failures == ("user_extraction:ValueError",)
    await host.cleanup()


@pytest.mark.asyncio
@pytest.mark.parametrize("fail_entry", [False, True])
async def test_real_abstract_client_closes_sdk_pool_and_partial_session(tmp_path: Path, fail_entry: bool) -> None:
    """Real AbstractClient keeps SDK pools beyond __aexit__; owned extraction must close both resource layers."""
    from parrot.clients.base import AbstractClient

    class SDK:
        """Observe a provider SDK pool closing without network access."""

        closed = False

        async def close(self) -> None:
            """Close the fake provider transport."""
            self.closed = True

    sdk = SDK()

    class Client(AbstractClient):
        """Use real AbstractClient acquisition and teardown with an offline provider."""

        async def get_client(self) -> SDK:
            """Optionally fail after the base has already opened its aiohttp session."""
            if fail_entry:
                raise RuntimeError("provider setup failed")
            return sdk

        async def ask(self, prompt: str, **kwargs: Any) -> str:
            """No durable knowledge in this fixture."""
            return "[]"

        async def ask_stream(self, prompt: str, **kwargs: Any) -> Any:
            """Provide an unused streaming implementation for the abstract contract."""
            yield "[]"

        async def invoke(self, *args: Any, **kwargs: Any) -> str:
            """Provide an unused invocation implementation for the abstract contract."""
            return "[]"

        async def resume(self, *args: Any, **kwargs: Any) -> str:
            """Provide an unused resume implementation for the abstract contract."""
            return "[]"

    client = Client(model="offline", use_session=True)
    manager = await create_memory_manager(
        AgentMemoryConfig(enable_user_memory=True, storage_path=str(tmp_path / "sdk.db")),
        namespace=MemoryNamespace(tenant_id="tenant", agent_id="agent"),
    )
    manager.extraction_client_factory = lambda: client
    try:
        receipt = await manager.record_event(_event("alice"))
        assert not client._clients_by_loop
        assert client.session.closed
        assert sdk.closed is not fail_entry
        assert bool(receipt.failures) is fail_entry
    finally:
        await client.close()
        if client.session is not None:
            await client.session.close()
        await manager.cleanup()
