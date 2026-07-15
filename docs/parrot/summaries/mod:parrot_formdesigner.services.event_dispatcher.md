---
type: Wiki Summary
title: parrot_formdesigner.services.event_dispatcher
id: mod:parrot_formdesigner.services.event_dispatcher
tags:
- summary
timestamp: '2026-07-14T22:20:21+00:00'
summary: Form lifecycle event dispatcher — FEAT-188.
relates_to:
- concept: func:parrot_formdesigner.services.event_dispatcher.apply_schema_overrides
  rel: defines
- concept: func:parrot_formdesigner.services.event_dispatcher.dispatch
  rel: defines
- concept: func:parrot_formdesigner.services.event_dispatcher.dispatch_visit
  rel: defines
- concept: mod:parrot_formdesigner.core.events
  rel: references
- concept: mod:parrot_formdesigner.core.schema
  rel: references
- concept: mod:parrot_formdesigner.services.event_registry
  rel: references
---

# `parrot_formdesigner.services.event_dispatcher`

Form lifecycle event dispatcher — FEAT-188.

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

## Functions

- `def apply_schema_overrides(base: dict[str, Any], overrides: Mapping[str, Any]) -> dict[str, Any]` — Shallow-merge ``overrides`` onto a copy of ``base``.
- `async def dispatch(event: FormEventName, *, form: FormSchema, request: web.Request, tenant: str | None, auth_context: Any, payload: Mapping[str, Any] | None=None, schema_dump: Mapping[str, Any] | None=None, error: BaseException | None=None) -> EventResolution` — Resolve and run the handler bound to ``event`` for ``form``.
- `async def dispatch_visit(event: VisitEventName, *, tenant: str | None, auth_context: Any, event_id: str | None=None, shift_id: str | None=None, visit_id: str | None=None, staff_id: str | None=None, payload: Mapping[str, Any] | None=None, extra: dict[str, Any] | None=None, handler_ref: str | None=None) -> EventResolution` — Resolve and run the handler bound to a visit lifecycle ``event``.
