"""Shared fixtures for the A2UI runtime dispatch tests (TASK-2569)."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest
from parrot.outputs.a2ui.catalog import DEFAULT_CATALOG_ID, FunctionDefinition
from parrot.outputs.a2ui.runtime.dispatch import A2UIRuntime
from parrot.outputs.a2ui.runtime.models import (
    A2UICallContext,
    FunctionCallRecord,
    SurfaceState,
)


class FakeExecutor:
    """Programmable: success / forbidden / not_found / raise."""

    def __init__(self, mode="success", functions=None):
        self.mode = mode
        self.calls = []
        self._functions = (
            functions
            if functions is not None
            else [
                FunctionDefinition(
                    name="get_weather",
                    catalog_id=DEFAULT_CATALOG_ID,
                    allowed_callers="rendererOrAgent",
                )
            ]
        )

    async def call(self, name, args, ctx):
        self.calls.append((name, args, ctx))
        if self.mode == "raise":
            raise RuntimeError("secret internal detail")
        from parrot.tools.abstract import ToolResult

        return {
            "success": ToolResult(success=True, status="success", result={"ok": 1}),
            "forbidden": ToolResult(success=False, status="forbidden", result=None, error="denied"),
            "not_found": ToolResult(success=False, status="not_found", result=None, error="missing"),
        }[self.mode]

    def list_functions(self):
        return self._functions


class FakeSurfaces:
    """In-memory SurfaceStateStore."""

    def __init__(self):
        self._store: dict[tuple[str, str], SurfaceState] = {}
        self.put_calls = []
        self.get_calls = []

    async def get(self, session_id, surface_id):
        self.get_calls.append((session_id, surface_id))
        return self._store.get((session_id, surface_id))

    async def put(self, session_id, state):
        self.put_calls.append((session_id, state))
        self._store[(session_id, state.surface_id)] = state

    async def delete(self, session_id, surface_id):
        self._store.pop((session_id, surface_id), None)


class FakePending:
    """In-memory PendingCallRegistry with TTL support."""

    def __init__(self):
        self._store: dict[tuple[str, str], FunctionCallRecord] = {}

    async def add(self, session_id, record):
        self._store[(session_id, record.function_call_id)] = record

    async def resolve(self, session_id, function_call_id, value, error):
        key = (session_id, function_call_id)
        record = self._store.get(key)
        if record is None:
            return None
        expires_at = record.created_at + timedelta(seconds=record.ttl_seconds)
        if datetime.now(UTC) > expires_at:
            del self._store[key]
            return None
        del self._store[key]
        return record


@pytest.fixture
def a2ui_call_ctx():
    return A2UICallContext(
        agent_id="agent-1",
        user_id="u-1",
        session_id="s-1",
        transport="http",
        permission_context=object(),
    )


@pytest.fixture
def fake_executor():
    return FakeExecutor(mode="success")


@pytest.fixture
def fake_surfaces():
    return FakeSurfaces()


@pytest.fixture
def fake_pending():
    return FakePending()


@pytest.fixture
def runtime(fake_executor, fake_surfaces, fake_pending):
    return A2UIRuntime(executor=fake_executor, surfaces=fake_surfaces, pending=fake_pending)


@pytest.fixture
def runtime_forbidden(fake_surfaces, fake_pending):
    return A2UIRuntime(executor=FakeExecutor(mode="forbidden"), surfaces=fake_surfaces, pending=fake_pending)


@pytest.fixture
def runtime_missing(fake_surfaces, fake_pending):
    return A2UIRuntime(executor=FakeExecutor(mode="not_found"), surfaces=fake_surfaces, pending=fake_pending)


@pytest.fixture
def runtime_raises(fake_surfaces, fake_pending):
    return A2UIRuntime(executor=FakeExecutor(mode="raise"), surfaces=fake_surfaces, pending=fake_pending)
