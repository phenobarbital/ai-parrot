"""A2UI Agent Functions runtime (FEAT-469) — pure protocol, no agent imports.

Receives already-deserialized R->A envelopes, dispatches them, and returns
A->R envelopes. Never imports ``parrot.bots``/``parrot.clients``/
``parrot.tools``/``parrot.memory`` at module level (G8): it receives a
``FunctionExecutor`` and a ``SurfaceStateStore``/``PendingCallRegistry`` by
injection instead. The concrete adapters over ``ToolManager``/
``ConversationMemory`` land in TASK-2570 (``runtime/adapters.py``).
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any, Protocol, runtime_checkable

from parrot.outputs.a2ui.runtime.models import (
    A2UICallContext,
    A2UIErrorCode,
    DispatchResult,
    FunctionCallRecord,
    SurfaceState,
    error_envelope,
)

if TYPE_CHECKING:  # pragma: no cover - import-rule guard (G8)
    from parrot.outputs.a2ui.catalog.base import FunctionDefinition
    from parrot.tools.abstract import ToolResult

__all__ = [
    "A2UICallContext",
    "A2UIErrorCode",
    "A2UIRuntime",
    "DispatchResult",
    "FunctionCallRecord",
    "FunctionExecutor",
    "PendingCallRegistry",
    "SurfaceState",
    "SurfaceStateStore",
    "error_envelope",
]


@runtime_checkable
class FunctionExecutor(Protocol):
    """Adapter over an agent's tool registry (production: ``ToolManagerExecutor``)."""

    async def call(self, name: str, args: dict[str, Any], ctx: A2UICallContext) -> ToolResult:
        """Execute a registered function by name and return its ``ToolResult``."""
        ...

    def list_functions(self) -> list[FunctionDefinition]:
        """Return the catalog-shaped definitions of every callable function."""
        ...


@runtime_checkable
class SurfaceStateStore(Protocol):
    """Adapter storing the last known ``dataModel`` per surface."""

    async def get(self, session_id: str, surface_id: str) -> SurfaceState | None:
        """Return the stored :class:`SurfaceState`, if any."""
        ...

    async def put(self, session_id: str, state: SurfaceState) -> None:
        """Persist (overwrite) a surface's state."""
        ...

    async def delete(self, session_id: str, surface_id: str) -> None:
        """Remove a surface's stored state."""
        ...


@runtime_checkable
class PendingCallRegistry(Protocol):
    """Adapter tracking agent->renderer calls awaiting correlation."""

    async def add(self, session_id: str, record: FunctionCallRecord) -> None:
        """Register a pending call."""
        ...

    async def resolve(
        self,
        session_id: str,
        function_call_id: str,
        value: Any,
        error: dict | None,
    ) -> FunctionCallRecord | None:
        """Resolve (and remove) a pending call. ``None`` if unknown/expired."""
        ...


# Imported after the Protocols so `dispatch.py`'s own TYPE_CHECKING-guarded
# references to `FunctionExecutor`/`SurfaceStateStore`/`PendingCallRegistry`
# resolve against real names when this package is fully initialized.
from parrot.outputs.a2ui.runtime.dispatch import A2UIRuntime
