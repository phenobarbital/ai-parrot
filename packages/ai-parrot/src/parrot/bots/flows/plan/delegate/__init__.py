"""Tool-call delegate for ExecutionPlans (FEAT-590).

Protocol symbols import eagerly; the node and the backends resolve lazily so
importing the plan package never pulls ``needle`` or opens sockets (AC14).
"""

from __future__ import annotations

import importlib
from typing import Any

from .protocol import (
    DelegateBackendError,
    DelegateTrace,
    DelegateTraceSink,
    JsonlTraceSink,
    ToolCallDelegate,
    ToolCallProposal,
    ToolSpec,
    tool_specs,
)

_LAZY = {
    "DelegateToolNode": ".node",
    "DelegateRejectedError": ".node",
    "DelegateEscalation": ".node",
    "make_delegate_node_factory": ".node",
    "LlamaCppDelegate": ".llamacpp",
    "NeedleDelegate": ".needle",
}

__all__ = (
    "DelegateBackendError",
    "DelegateTrace",
    "DelegateTraceSink",
    "JsonlTraceSink",
    "ToolCallDelegate",
    "ToolCallProposal",
    "ToolSpec",
    "tool_specs",
    *_LAZY,
)


def __getattr__(name: str) -> Any:
    """Resolve node/backend symbols on first access."""
    module = _LAZY.get(name)
    if module is None:
        raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
    return getattr(importlib.import_module(module, __name__), name)
