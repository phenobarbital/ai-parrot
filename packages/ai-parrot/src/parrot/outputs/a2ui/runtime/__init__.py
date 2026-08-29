"""A2UI Agent Functions runtime (FEAT-469) — pure protocol, no agent imports.

Receives already-deserialized R->A envelopes, dispatches them, and returns
A->R envelopes. Never imports ``parrot.bots``/``parrot.clients`` (G8): it
receives a ``FunctionExecutor`` and a ``SurfaceStateStore``/
``PendingCallRegistry`` by injection instead (the ``Protocol``s land in
TASK-2569; the concrete adapters over ``ToolManager``/``ConversationMemory``
land in TASK-2570, ``runtime/adapters.py``).
"""

from __future__ import annotations

from parrot.outputs.a2ui.runtime.models import (
    A2UICallContext,
    A2UIErrorCode,
    DispatchResult,
    FunctionCallRecord,
    SurfaceState,
    error_envelope,
)

__all__ = [
    "A2UICallContext",
    "A2UIErrorCode",
    "DispatchResult",
    "FunctionCallRecord",
    "SurfaceState",
    "error_envelope",
]
