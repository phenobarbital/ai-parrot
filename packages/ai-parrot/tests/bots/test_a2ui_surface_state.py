"""``_a2ui_surface_state`` reserved-kwarg tests (FEAT-469 TASK-2575).

Covers the tool-side mechanism (`AbstractTool.execute` pop + ContextVar
fallback + schema hygiene) with real `AbstractTool` instances, and the
bot-side wiring (`AbstractBot.ask` setting the ContextVar) via source
inspection — the same technique already established in this codebase for a
similar wire-contract guard (see
``ai-parrot-server/tests/handlers/test_agent_a2ui_stream.py``), since driving
a full ``ask()`` call requires mocking RAG retrieval/prompt-building/LLM
client construction unrelated to this task's mechanism.
"""

from __future__ import annotations

import asyncio
from datetime import UTC, datetime
from pathlib import Path

from parrot.outputs.a2ui.runtime.models import SurfaceState
from parrot.tools.abstract import (
    _A2UI_SURFACE_STATE_VAR,
    AbstractTool,
    current_a2ui_surface_state,
)

_BASE_SRC = Path(__file__).resolve().parents[2] / "src" / "parrot" / "bots" / "base.py"
_SRC = _BASE_SRC.read_text(encoding="utf-8")


def _surface_state() -> SurfaceState:
    return SurfaceState(
        surface_id="s-1",
        catalog_id="https://parrot.dev/catalogs/v1",
        data_model={"count": 3},
        updated_at=datetime.now(UTC),
    )


class _SpyTool(AbstractTool):
    """Records the surface state seen by its own execution."""

    name = "spy_tool"
    description = "Records the surface state it received."

    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        self.last_surface_state = "UNSET"
        self.observed: list = []

    async def _execute(self, **kwargs):
        # Yield before AND after reading, so two concurrent calls on the
        # SAME shared instance genuinely interleave (regression coverage
        # for the instance-attribute race the ContextVar-only design
        # closes — see `test_concurrent_calls_on_shared_instance_do_not_leak_state`).
        await asyncio.sleep(0)
        state = current_a2ui_surface_state()
        await asyncio.sleep(0)
        self.last_surface_state = state
        self.observed.append(state)
        return "ok"


class _PlainTool(AbstractTool):
    """A tool that never references `_a2ui_surface_state` at all."""

    name = "plain_tool"
    description = "Does not care about A2UI surface state."

    async def _execute(self, **kwargs):
        return "ok"


class TestToolReceivesSurfaceState:
    async def test_tool_receives_explicit_kwarg(self):
        tool = _SpyTool()
        state = _surface_state()
        result = await tool.execute(_a2ui_surface_state=state)
        assert result.success is True
        assert tool.last_surface_state == state

    async def test_tool_receives_contextvar_fallback(self):
        """AbstractBot.ask() sets the ContextVar rather than passing a kwarg
        (tools/manager.py + every LLM client are out of this feature's scope
        for threading a new execute_tool() kwarg — see the module docstring
        on `_A2UI_SURFACE_STATE_VAR`)."""
        tool = _SpyTool()
        state = _surface_state()
        token = _A2UI_SURFACE_STATE_VAR.set(state)
        try:
            result = await tool.execute()
        finally:
            _A2UI_SURFACE_STATE_VAR.reset(token)
        assert result.success is True
        assert tool.last_surface_state == state

    async def test_absent_surface_state_is_none(self):
        tool = _SpyTool()
        result = await tool.execute()
        assert result.success is True
        assert tool.last_surface_state is None

    async def test_tool_without_kwarg_still_executes(self):
        """execute() pops it — a tool that never declared it must not break."""
        tool = _PlainTool()
        result = await tool.execute(_a2ui_surface_state=_surface_state())
        assert result.success is True
        assert result.result == "ok"

    async def test_concurrent_calls_on_shared_instance_do_not_leak_state(self):
        """Two concurrent execute() calls on the SAME shared instance must
        each observe only their own explicit surface state — regression test
        for the race a plain instance attribute would reintroduce (code
        review finding on this feature; a ToolkitTool instance is commonly
        shared and can be awaited concurrently by different sessions).

        Relies on asyncio's per-Task context isolation: `ContextVar.set()`
        inside one Task is never visible to another concurrently-running
        Task, only to code awaited within the SAME Task — which is exactly
        why `current_a2ui_surface_state()` reads a ContextVar instead of a
        `self` attribute shared by both calls.
        """
        tool = _SpyTool()
        state_a = _surface_state()
        state_b = SurfaceState(
            surface_id="s-2",
            catalog_id="https://parrot.dev/catalogs/v1",
            data_model={"count": 99},
            updated_at=datetime.now(UTC),
        )

        results = await asyncio.gather(
            tool.execute(_a2ui_surface_state=state_a),
            tool.execute(_a2ui_surface_state=state_b),
        )
        assert {r.success for r in results} == {True}
        # Each call's _execute() observed exactly its OWN state — neither
        # saw the other's (would fail intermittently pre-fix, when both
        # calls raced to overwrite the same `self` attribute).
        assert {id(s) for s in tool.observed} == {id(state_a), id(state_b)}


class TestSchemaHygiene:
    def test_reserved_kwarg_absent_from_schema(self):
        tool = _SpyTool()
        schema = tool.get_tool_schema()
        assert "_a2ui_surface_state" not in str(schema)

    def test_permission_context_convention_unchanged(self):
        tool = _SpyTool()
        schema = tool.get_tool_schema()
        assert "_permission_context" not in str(schema)


class TestAskWiresContextVar:
    """Bot-side wiring — verified via source inspection (see module docstring)."""

    def test_ask_accepts_a2ui_surface_state_param(self):
        assert "a2ui_surface_state: Optional[Any] = None," in _SRC

    def test_ask_sets_the_contextvar(self):
        assert "_A2UI_SURFACE_STATE_VAR.set(a2ui_surface_state)" in _SRC
        assert "from ..tools.abstract import _A2UI_SURFACE_STATE_VAR" in _SRC
