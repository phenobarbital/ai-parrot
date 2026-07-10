"""Form lifecycle event models for parrot-formdesigner.

This module defines the Pydantic models and typed exception used by the
form lifecycle events system (FEAT-188). All later modules (event_registry,
event_dispatcher, schema extension, handlers, renderer) import from here.

FEAT-329 extends the same pattern with the ``visit.*`` namespace: visit /
assignment lifecycle events reuse the FEAT-188 registry and semantics
(context → handler → ``EventResolution`` | ``FormEventAbort``) without a
``FormSchema`` in the path.

Public surface:
    - FormEventName
    - FormEventBinding
    - FormEventsConfig
    - FormEventContext
    - EventResolution
    - FormEventAbort
    - VisitEventName
    - VisitEventContext
"""

from collections.abc import Mapping
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field

# ---------------------------------------------------------------------------
# Type alias
# ---------------------------------------------------------------------------

FormEventName = Literal[
    "onBeforeOpen",
    "onSchemaLoaded",
    "onBeforeSubmit",
    "onAfterSubmit",
    "onError",
]

VisitEventName = Literal[
    "visit.onAssignmentCreated",
    "visit.onArtifactAttached",
    "visit.onArrival",
    "visit.onGeofenceExit",
    "visit.onCheckout",
]


# ---------------------------------------------------------------------------
# Pydantic models
# ---------------------------------------------------------------------------


class FormEventBinding(BaseModel):
    """Declaración por-formulario de un binding evento → handler.

    Attributes:
        handler_ref: Logical handler name, namespaced as
            ``'<form_id>.<event>'``. At least one dot is required to
            prevent cross-form collisions (per spec §7 naming decision).
        remote: When ``True``, the HTML5 client bridges the event to the
            server via a ``fetch`` call to the remote endpoint.
        required: When ``True`` and the handler is not registered, the
            dispatcher raises ``RuntimeError`` instead of silently no-op-ing.
    """

    model_config = ConfigDict(extra="forbid")

    handler_ref: str = Field(
        ...,
        description="Logical handler name, namespaced as '<form_id>.<event>'.",
        pattern=r"^[A-Za-z_][A-Za-z0-9_]*(\.[A-Za-z_][A-Za-z0-9_]*)+$",
    )
    remote: bool = False  # if True, HTML5 client bridges via fetch
    required: bool = False  # if True and handler missing → 500


class FormEventsConfig(BaseModel):
    """Mapa declarado por-formulario de event → binding.

    All fields are optional. Forms without an event binding simply skip
    that hook without any overhead (no-op by default in the dispatcher).

    Attributes:
        onBeforeOpen: Fired before the form is returned to the client.
            Can mutate ``schema_dump`` or abort with ``FormEventAbort``.
        onSchemaLoaded: Fired after the structural schema is rendered.
            Can apply ``schema_overrides``.
        onBeforeSubmit: Fired before validation. Can normalise/replace
            ``payload`` or abort with ``FormEventAbort``.
        onAfterSubmit: Fired after the submission is stored and forwarded.
            Side-effects only; return value ignored by dispatcher.
        onError: Fired when any unhandled exception escapes ``submit_data``.
            Can transform ``user_message``; original exception is re-raised.
    """

    model_config = ConfigDict(extra="forbid")

    onBeforeOpen: FormEventBinding | None = None
    onSchemaLoaded: FormEventBinding | None = None
    onBeforeSubmit: FormEventBinding | None = None
    onAfterSubmit: FormEventBinding | None = None
    onError: FormEventBinding | None = None


class FormEventContext(BaseModel):
    """Payload passed to a form lifecycle event handler.

    Attributes:
        event: The name of the lifecycle event being dispatched.
        form_id: Identifier of the form that owns the event.
        tenant: Tenant slug used to resolve the handler in the registry.
        auth_context: Resolved auth credentials.  Typed as ``Any`` to
            avoid a circular import through ``core/`` → ``services/``.
        payload: Submitted data (present only for submit events).
        schema_dump: Rendered schema dict (present for open/schema_loaded).
        error: The exception that triggered ``onError`` (if applicable).
        user_message: Mutable error message that ``onError`` handlers may
            replace for friendlier i18n output.
        extra: Free-form bag for correlation IDs, tracing data, etc.
    """

    model_config = ConfigDict(extra="forbid", arbitrary_types_allowed=True)

    event: FormEventName
    form_id: str
    tenant: str | None
    auth_context: Any  # services.auth_context.AuthContext — avoid circular
    payload: Mapping[str, Any] | None = None       # submit only
    schema_dump: Mapping[str, Any] | None = None   # open / schema_loaded only
    error: BaseException | None = None             # onError only
    user_message: str | None = None                # onError mutable
    extra: dict[str, Any] = Field(default_factory=dict)  # correlation_id, etc.


class VisitEventContext(BaseModel):
    """Payload passed to a visit lifecycle event handler (FEAT-329).

    Mirror of ``FormEventContext`` for the ``visit.*`` namespace: same
    context → handler → resolution semantics, but scoped to a visit /
    assignment rather than a form — no ``form_id`` / ``schema_dump``
    in the path.

    Attributes:
        event: The name of the visit lifecycle event being dispatched.
        tenant: Tenant slug used to resolve the handler in the registry.
        auth_context: Resolved auth credentials.  Typed as ``Any`` to
            avoid a circular import through ``core/`` → ``services/``.
        event_id: Identifier of the parent Event (FEAT-303), if any.
        shift_id: Identifier of the Shift the visit belongs to, if any.
        visit_id: Identifier of the Visit being processed, if any.
        staff_id: Identifier of the staff member performing the visit.
        payload: Event-specific data (artifact metadata, GPS fix, ...).
        extra: Free-form bag for correlation IDs, tracing data, etc.
    """

    model_config = ConfigDict(extra="forbid", arbitrary_types_allowed=True)

    event: VisitEventName
    tenant: str | None
    auth_context: Any  # services.auth_context.AuthContext — avoid circular
    event_id: str | None = None
    shift_id: str | None = None
    visit_id: str | None = None
    staff_id: str | None = None
    payload: Mapping[str, Any] | None = None
    extra: dict[str, Any] = Field(default_factory=dict)  # correlation_id, etc.


class EventResolution(BaseModel):
    """Return value of a form lifecycle event handler.

    All fields are optional. An empty ``EventResolution()`` is a valid
    no-op: the dispatcher will leave all inputs unchanged.

    Attributes:
        payload: When non-``None``, replaces the submission payload passed
            to the next processing step.
        schema_overrides: When non-``None``, shallow-merges into the
            serialised ``FormSchema`` dict (top-level keys only, per spec
            §7 shallow-merge decision for MVP).
        metadata: Added to ``FormEventContext.extra`` for downstream
            consumers (audit, tracing).
        user_message: Only meaningful for ``onError``; overrides the
            error message returned to the end-user.
    """

    model_config = ConfigDict(extra="forbid")

    payload: Mapping[str, Any] | None = None             # replace payload
    schema_overrides: Mapping[str, Any] | None = None    # shallow merge on form dump
    metadata: Mapping[str, Any] | None = None            # added to ctx.extra
    user_message: str | None = None                      # only meaningful in onError


# ---------------------------------------------------------------------------
# Typed exception
# ---------------------------------------------------------------------------


class FormEventAbort(Exception):
    """Cancels a ``before*`` lifecycle event with a typed user-facing response.

    Inspired by ``api/operations.py:150 OperationError``.  Raising this
    inside a handler registered for ``onBeforeOpen`` or ``onBeforeSubmit``
    causes the dispatcher to re-raise it immediately so that the calling
    handler in ``FormAPIHandler`` can convert it to the correct HTTP error
    response (``status_code`` + ``user_message``).

    ``onError`` is **not** triggered for ``FormEventAbort`` — an abort is a
    controlled flow, not an unexpected failure (per spec §7).

    Attributes:
        reason: Internal technical reason for the abort (logged, not exposed
            to end-users).
        user_message: Human-readable message safe to return in the HTTP body.
        status_code: HTTP status code for the response (default: 403).
    """

    def __init__(
        self,
        reason: str,
        *,
        user_message: str,
        status_code: int = 403,
    ) -> None:
        self.reason = reason
        self.user_message = user_message
        self.status_code = status_code
        super().__init__(reason)
