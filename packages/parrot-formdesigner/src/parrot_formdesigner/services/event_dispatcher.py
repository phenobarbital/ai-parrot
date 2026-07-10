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

FEAT-329 adds ``dispatch_visit(...)`` — the same pattern for the
``visit.*`` namespace (visit / assignment lifecycle). Visit events reuse
the FEAT-188 string-keyed tenant-scoped registry: the visit event name
itself acts as the ``handler_ref`` (``"visit.onArrival"`` vs
``"<form_id>.onBeforeSubmit"`` — the namespace disambiguates). No
``FormSchema`` / binding / ``schema_dump`` is involved in the visit path.
"""

from __future__ import annotations

import logging
from collections.abc import Mapping
from typing import Any

from aiohttp import web

from parrot_formdesigner.core.events import (
    EventResolution,
    FormEventAbort,
    FormEventContext,
    FormEventName,
    VisitEventContext,
    VisitEventName,
)
from parrot_formdesigner.core.schema import FormSchema
from parrot_formdesigner.services.event_registry import get_form_event

logger = logging.getLogger(__name__)

# Visit events with pre-hook (interceptor) semantics: ``FormEventAbort``
# raised by the handler is re-raised to the caller, mirroring the
# ``before*`` form events of FEAT-188 (per FEAT-329 spec §2). All other
# visit events are post-hooks: fire-and-forget, handler failures are
# logged and never break the visit flow.
_VISIT_PRE_HOOKS: frozenset[str] = frozenset({"visit.onArrival"})


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
        tenant=tenant,
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


async def dispatch_visit(
    event: VisitEventName,
    *,
    tenant: str | None,
    auth_context: Any,
    event_id: str | None = None,
    shift_id: str | None = None,
    visit_id: str | None = None,
    staff_id: str | None = None,
    payload: Mapping[str, Any] | None = None,
    extra: dict[str, Any] | None = None,
    handler_ref: str | None = None,
) -> EventResolution:
    """Resolve and run the handler bound to a visit lifecycle ``event``.

    Mirror of :func:`dispatch` for the ``visit.*`` namespace (FEAT-329).
    Reuses the FEAT-188 tenant-scoped registry: handlers are registered
    with ``@register_form_event("visit.onArrival")`` (optionally with
    ``tenant="<slug>"``) and the visit event name itself acts as the
    ``handler_ref``. No ``FormSchema`` / binding / ``schema_dump`` is
    involved in the visit path.

    Hook semantics (per FEAT-329 spec §2):

    - **Pre-hooks** (``visit.onArrival``): ``FormEventAbort`` raised by
      the handler is re-raised intact (the caller converts it to an HTTP
      ``status_code`` + ``user_message``); other exceptions propagate
      unchanged, mirroring the ``before*`` form events.
    - **Post-hooks** (all other visit events): fire-and-forget — any
      exception raised by the handler (including ``FormEventAbort``) is
      logged and swallowed so side-effects never break the visit flow.

    Args:
        event: The visit lifecycle event name to dispatch
            (e.g. ``"visit.onArrival"``).
        tenant: Tenant slug used for registry lookup with global fallback.
        auth_context: Resolved authentication credentials (typed ``Any``
            to avoid a circular import; typically an ``AuthContext`` instance).
        event_id: Identifier of the parent Event (FEAT-303), if any.
        shift_id: Identifier of the Shift the visit belongs to, if any.
        visit_id: Identifier of the Visit being processed, if any.
        staff_id: Identifier of the staff member performing the visit.
        payload: Event-specific data (artifact metadata, GPS fix, ...).
        extra: Free-form bag for correlation IDs, tracing data, etc.
        handler_ref: Registry key to look up. Defaults to ``event``
            itself (the ``visit.*`` namespace disambiguates it from
            form-scoped ``'<form_id>.<event>'`` refs in the shared registry).

    Returns:
        An ``EventResolution``. If no handler is registered for
        ``handler_ref`` (tenant-specific or global), returns an empty
        ``EventResolution()`` (no-op).

    Raises:
        FormEventAbort: Re-raised intact when a **pre-hook** handler
            aborts (``visit.onArrival``). Never raised for post-hooks.
        Exception: Any other exception raised by a **pre-hook** handler
            propagates unchanged. Post-hook exceptions are logged and
            swallowed (fire-and-forget).
    """
    ref = handler_ref if handler_ref is not None else event
    is_pre_hook = event in _VISIT_PRE_HOOKS

    # --- Step 1: look up handler (tenant → global fallback) --------------
    try:
        handler = get_form_event(ref, tenant=tenant)
    except KeyError:
        logger.warning(
            "no handler registered for %r (event=%r, tenant=%r); skipping",
            ref,
            event,
            tenant,
        )
        return EventResolution()

    # --- Step 2: build context and run ------------------------------------
    ctx = VisitEventContext(
        event=event,
        tenant=tenant,
        auth_context=auth_context,
        event_id=event_id,
        shift_id=shift_id,
        visit_id=visit_id,
        staff_id=staff_id,
        payload=payload,
        extra=extra if extra is not None else {},
    )

    logger.debug(
        "dispatching %r → %r (visit=%r, tenant=%r)",
        event,
        ref,
        visit_id,
        tenant,
    )

    if is_pre_hook:
        # FormEventAbort propagates intact (not caught here).
        # All other exceptions also propagate; the caller handles them.
        result = await handler(ctx)
    else:
        # Post-hooks are fire-and-forget: never break the visit flow.
        try:
            result = await handler(ctx)
        except FormEventAbort:
            logger.warning(
                "handler %r raised FormEventAbort for post-hook %r; "
                "aborts are only meaningful for pre-hooks — ignoring",
                ref,
                event,
            )
            return EventResolution()
        except Exception:  # noqa: BLE001 — fire-and-forget by design
            logger.exception(
                "handler %r failed for post-hook %r (visit=%r, tenant=%r); "
                "ignoring (fire-and-forget)",
                ref,
                event,
                visit_id,
                tenant,
            )
            return EventResolution()

    # --- Step 3: normalise result -----------------------------------------
    if result is None:
        return EventResolution()

    return result
