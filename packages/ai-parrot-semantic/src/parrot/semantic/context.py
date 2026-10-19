"""Per-call subject ContextVar for the semantic toolkit (never stored on the instance)."""

from __future__ import annotations

import contextvars
from typing import Any

from parrot.auth import PermissionContext

_semantic_pctx_var: contextvars.ContextVar[PermissionContext | None] = contextvars.ContextVar(
    "semantic_pctx", default=None
)
_static_subject_var: contextvars.ContextVar[bool] = contextvars.ContextVar("semantic_static", default=False)
# Request-scoped DatasetManager supplied by a host (HTTP handler) for one hand-off; never stored on the toolkit.
_request_dataset_manager_var: contextvars.ContextVar[Any] = contextvars.ContextVar(
    "semantic_request_dataset_manager", default=None
)


def current_pctx() -> PermissionContext | None:
    """Return the PermissionContext of the current tool call, or None."""
    return _semantic_pctx_var.get()
