"""A2UI Agent Functions runtime — pure-data models and error codes.

Implements spec ``a2ui-agent-functions`` (FEAT-469) §3 Module 1: the types
every other runtime module (``dispatch.py``, ``adapters.py``) consumes.

This module is pure protocol data (Pydantic v2 models + a str-enum) and MUST
NEVER import ``parrot.bots``, ``parrot.clients``, ``parrot.tools``, or
``parrot.memory`` at module level (the G8 one-way import rule, spec §7).
``A2UICallContext.permission_context`` is deliberately typed ``Any`` rather
than importing :class:`parrot.auth.permission.PermissionContext` — the
runtime treats it as an opaque token handed back to the transport-provided
executor, never inspecting it itself.

Error codes: :class:`A2UIErrorCode` mixes two families. ``INVALID_FUNCTION_CALL``,
``UNALLOWED_PARENT``, and ``UNALLOWED_CHILD`` are protocol-defined (they match
:data:`parrot.outputs.a2ui.models._VALIDATION_ERROR_CODES` plus the wire's
generic-error convention). ``FORBIDDEN``, ``NOT_FOUND``, ``INTERNAL``, and
``TIMEOUT`` are **parrot extensions** — the A2UI v1.0 wire spec reserves no
fixed code list for "Generic Error" (any string is legal there), so these are
our own conventions layered on top, not part of the official protocol.
"""

from __future__ import annotations

from datetime import datetime
from enum import Enum
from typing import Any, Literal

from pydantic import BaseModel, Field

from parrot.outputs.a2ui.models import ErrorMessage
from parrot.outputs.a2ui.serialization import serialize

__all__ = [
    "A2UICallContext",
    "A2UIErrorCode",
    "DispatchResult",
    "FunctionCallRecord",
    "SurfaceState",
    "error_envelope",
]


class A2UIErrorCode(str, Enum):
    """A2UI runtime error codes.

    ``INVALID_FUNCTION_CALL``, ``UNALLOWED_PARENT``, and ``UNALLOWED_CHILD``
    are protocol-facing generic-error codes. ``FORBIDDEN``, ``NOT_FOUND``,
    ``INTERNAL``, and ``TIMEOUT`` are parrot-specific extensions — do not
    "correct" them against an official A2UI code list, because none exists
    for generic errors.
    """

    INVALID_FUNCTION_CALL = "INVALID_FUNCTION_CALL"
    UNALLOWED_PARENT = "UNALLOWED_PARENT"
    UNALLOWED_CHILD = "UNALLOWED_CHILD"
    FORBIDDEN = "FORBIDDEN"
    NOT_FOUND = "NOT_FOUND"
    INTERNAL = "INTERNAL"
    TIMEOUT = "TIMEOUT"


class A2UICallContext(BaseModel):
    """The context a transport builds for a single R->A invocation.

    Attributes:
        agent_id: The id of the agent handling this call.
        user_id: The authenticated user id, if any.
        session_id: The conversation session id.
        surface_id: The surface this call is scoped to, if known.
        permission_context: Opaque ``parrot.auth.permission.PermissionContext``,
            passed straight through to ``ToolManager.execute_tool()``. Typed
            ``Any`` on purpose — the runtime never imports or inspects it
            (G8).
        transport: Which transport built this context.
        streaming: Whether the call is part of a streaming exchange.
    """

    agent_id: str
    user_id: str | None = None
    session_id: str
    surface_id: str | None = None
    permission_context: Any = None
    transport: Literal["http", "a2a", "deeplink"]
    streaming: bool = False


class FunctionCallRecord(BaseModel):
    """An agent->renderer ``callRendererFunction`` call awaiting correlation.

    Attributes:
        function_call_id: The unique id the renderer must echo back in its
            ``rendererFunctionResponse``/``error``.
        surface_id: The surface this call targets, if any.
        call: The renderer function name being invoked.
        catalog_id: The catalog the function belongs to, if not the default.
        args: The arguments passed to the renderer function.
        created_at: When this record was registered (UTC).
        ttl_seconds: Seconds after ``created_at`` this record may still be
            resolved. Defaults to 900s (15 minutes).
    """

    function_call_id: str
    surface_id: str | None = None
    call: str
    catalog_id: str | None = None
    args: dict[str, Any] = Field(default_factory=dict)
    created_at: datetime
    ttl_seconds: int = 900


class SurfaceState(BaseModel):
    """The last known ``dataModel`` for a surface (spec G3 ``sendDataModel``).

    Attributes:
        surface_id: The surface this state belongs to.
        catalog_id: The surface's catalog id.
        data_model: The last full data model reported for this surface.
        updated_at: When this state was last updated (UTC).
    """

    surface_id: str
    catalog_id: str
    data_model: dict[str, Any]
    updated_at: datetime


class DispatchResult(BaseModel):
    """The outcome of :meth:`A2UIRuntime.dispatch` (TASK-2569).

    Attributes:
        messages: Already-serialized A->R envelopes (``{"version": "v1.0",
            ...}``) to return to the renderer.
        user_turn: A structured user/system turn to inject into the bot, if
            the dispatched message was an ``action``.
        surface_state: The updated :class:`SurfaceState`, if ``sendDataModel``
            was honoured for this dispatch.
    """

    messages: list[dict[str, Any]] = Field(default_factory=list)
    user_turn: str | None = None
    surface_state: SurfaceState | None = None


def error_envelope(
    code: A2UIErrorCode,
    message: str,
    *,
    function_call_id: str | None = None,
    surface_id: str | None = None,
    path: str | None = None,
) -> dict[str, Any]:
    """Build a schema-valid ``{"version": "v1.0", "error": {...}}`` envelope.

    Always goes through :class:`~parrot.outputs.a2ui.models.ErrorMessage` +
    :func:`~parrot.outputs.a2ui.serialization.serialize` — this function never
    hand-writes the ``version`` field (spec §7: "el runtime nunca escribe
    ``version`` a mano"; ``serialization`` owns it).

    Args:
        code: The error code. Determines which of the two wire shapes
            applies ("Validation Failed" vs. "Generic Error").
        message: A short, safe description of the error. MUST NOT contain
            exception text or a traceback — log the real cause with
            ``logger.exception`` instead.
        function_call_id: The function invocation this error responds to.
            Only valid for a Generic Error; mutually exclusive with
            ``surface_id``.
        surface_id: The surface where the error occurred. Required (with
            ``path``) for a Validation Failed error; for a Generic Error,
            mutually exclusive with ``function_call_id``.
        path: JSON pointer to the field that failed validation. Only valid
            (and required) for a Validation Failed error.

    Returns:
        A JSON-ready envelope dict with exactly two keys: ``version`` and
        ``error``.

    Raises:
        ValueError: If ``code``/``surface_id``/``function_call_id``/``path``
            do not form one of the two valid wire shapes.
            :class:`pydantic.ValidationError` (raised by
            :class:`~parrot.outputs.a2ui.models.ErrorMessage`'s own shape
            validator) is a ``ValueError`` subclass, so this is the single
            source of truth for what counts as a malformed error envelope —
            this function does not duplicate that check.
    """
    error = ErrorMessage(
        code=code.value,
        message=message,
        surfaceId=surface_id,
        path=path,
        functionCallId=function_call_id,
    )
    return serialize(error)
