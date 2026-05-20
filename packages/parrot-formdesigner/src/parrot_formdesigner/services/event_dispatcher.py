"""Form lifecycle event dispatcher — FEAT-188.

Implements the central orchestration coroutine ``dispatch(...)`` that
resolves a ``FormEventBinding`` from a ``FormSchema``, looks up the
registered handler in the tenant-scoped ``event_registry``, runs it, and
returns a normalised ``EventResolution``.

Responsibilities
----------------
1. Resolve the binding for ``event`` from ``form.events`` (or ``None`` if
   the field does not exist / is not declared).
2. If no binding → return an empty ``EventResolution()`` immediately (no-op,
   no registry lookup).
3. Look up the handler via ``get_form_event(handler_ref, tenant=tenant)``.
   - ``required=True`` + ``KeyError`` → ``RuntimeError`` (configuration error).
   - ``required=False`` + ``KeyError`` → log warning + return empty ``EventResolution()``.
4. Build ``FormEventContext`` and ``await handler(ctx)``.
5. Normalise ``None`` return → empty ``EventResolution()``.
6. Re-raise ``FormEventAbort`` intact (the caller converts it to HTTP).
7. Let all other exceptions propagate; the caller decides whether to
   dispatch ``onError`` and how to respond.

Also exposes ``apply_schema_overrides(base, overrides)`` — a pure helper
for shallow-merging ``EventResolution.schema_overrides`` into a serialised
``FormSchema`` dict (top-level keys only, per spec §7).
"""

from __future__ import annotations

import logging
from collections.abc import Mapping
from typing import Any

from aiohttp import web

from parrot_formdesigner.core.events import (
    EventResolution,
    FormEventContext,
    FormEventName,
)
from parrot_formdesigner.core.schema import FormSchema
from parrot_formdesigner.services.event_registry import get_form_event

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Public helpers
# ---------------------------------------------------------------------------


def apply_schema_overrides(
    base: dict[str, Any],
    overrides: Mapping[str, Any],
) -> dict[str, Any]:
    """Shallow-merge ``overrides`` onto a copy of ``base``.

    Only top-level keys are replaced. Nested structures in ``base`` that
    share a key with ``overrides`` are entirely replaced by the value from
    ``overrides`` (no deep merge). This is intentional per spec §7 MVP
    decision; deep merge is deferred to a follow-up.

    Args:
        base: The serialised ``FormSchema`` dict to patch.
        overrides: Top-level key/value pairs to merge in.

    Returns:
        A new dict with ``overrides`` applied (``base`` is not mutated).

    Example::

        >>> apply_schema_overrides({"a": 1, "b": {"x": 1}}, {"b": {"y": 2}})
        {"a": 1, "b": {"y": 2}}  # nested "x" is dropped — shallow only
    """
    result = dict(base)
    result.update(overrides)
    return result


# ---------------------------------------------------------------------------
# Public coroutine
# ---------------------------------------------------------------------------


async def dispatch(
    event: FormEventName,
    *,
    form: FormSchema,
    request: web.Request,
    tenant: str | None,
    auth_context: Any,
    payload: Mapping[str, Any] | None = None,
    schema_dump: Mapping[str, Any] | None = None,
    error: BaseException | None = None,
) -> EventResolution:
    """Resolve and run the handler bound to ``event`` for ``form``.

    Args:
        event: The lifecycle event name to dispatch
            (e.g. ``"onBeforeSubmit"``).
        form: The ``FormSchema`` whose ``events`` config is inspected.
        request: The current aiohttp ``Request`` (passed to the context
            for handler access if needed; the dispatcher itself does not
            read it).
        tenant: Tenant slug used for registry lookup with global fallback.
        auth_context: Resolved authentication credentials (typed ``Any``
            to avoid a circular import; typically an ``AuthContext`` instance).
        payload: Submission data (present for submit events).
        schema_dump: Rendered schema dict (present for open / schema_loaded).
        error: The exception that triggered ``onError`` (if applicable).

    Returns:
        An ``EventResolution``. If no binding is declared for ``event`` on
        ``form``, returns an empty ``EventResolution()`` (no-op).

    Raises:
        FormEventAbort: Re-raised intact when the handler aborts a
            ``before*`` event.  The calling handler in ``FormAPIHandler``
            converts it to an HTTP response.
        RuntimeError: When the binding has ``required=True`` but no handler
            is registered for ``handler_ref``.
        Exception: Any other exception raised by the handler propagates
            unchanged. The caller decides whether to dispatch ``onError``
            and how to respond.
    """
    # --- Step 1: resolve binding ----------------------------------------
    events_config = getattr(form, "events", None)
    if events_config is None:
        return EventResolution()

    binding = getattr(events_config, event, None)
    if binding is None:
        return EventResolution()

    handler_ref: str = binding.handler_ref

    # --- Step 2: look up handler ----------------------------------------
    try:
        handler = get_form_event(handler_ref, tenant=tenant)
    except KeyError:
        if binding.required:
            raise RuntimeError(
                f"event handler not registered: {handler_ref!r} "
                f"(form={form.form_id!r}, event={event!r}). "
                "The binding has required=True — register the handler before "
                "starting the application."
            )
        logger.warning(
            "no handler registered for %r (form=%r, event=%r, tenant=%r); "
            "skipping (binding.required=False)",
            handler_ref,
            form.form_id,
            event,
            tenant,
        )
        return EventResolution()

    # --- Step 3: build context and run ----------------------------------
    ctx = FormEventContext(
        event=event,
        form_id=form.form_id,
        tenant=tenant or "",
        auth_context=auth_context,
        payload=payload,
        schema_dump=schema_dump,
        error=error,
    )

    logger.debug(
        "dispatching %r → %r (form=%r, tenant=%r)",
        event,
        handler_ref,
        form.form_id,
        tenant,
    )

    # FormEventAbort propagates intact (not caught here).
    # All other exceptions also propagate; caller handles onError dispatch.
    result = await handler(ctx)

    # --- Step 4: normalise result ---------------------------------------
    if result is None:
        return EventResolution()

    return result
