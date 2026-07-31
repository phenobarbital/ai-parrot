---
type: Wiki Summary
title: parrot_formdesigner.api.operations
id: mod:parrot_formdesigner.api.operations
tags:
- summary
timestamp: '2026-07-16T08:34:12+00:00'
summary: '``PATCH /api/v1/forms/{form_id}/operations`` — atomic batched-edit endpoint.'
relates_to:
- concept: class:parrot_formdesigner.api.operations.AddField
  rel: defines
- concept: class:parrot_formdesigner.api.operations.AddSection
  rel: defines
- concept: class:parrot_formdesigner.api.operations.DuplicateField
  rel: defines
- concept: class:parrot_formdesigner.api.operations.MoveField
  rel: defines
- concept: class:parrot_formdesigner.api.operations.OperationError
  rel: defines
- concept: class:parrot_formdesigner.api.operations.OperationsEnvelope
  rel: defines
- concept: class:parrot_formdesigner.api.operations.RemoveField
  rel: defines
- concept: class:parrot_formdesigner.api.operations.UpdateField
  rel: defines
- concept: class:parrot_formdesigner.api.operations.UpdateFormMeta
  rel: defines
- concept: class:parrot_formdesigner.api.operations.UpdateSectionMeta
  rel: defines
- concept: func:parrot_formdesigner.api.operations.handle_operations
  rel: defines
- concept: mod:parrot_formdesigner.api._utils
  rel: references
- concept: mod:parrot_formdesigner.core.schema
  rel: references
- concept: mod:parrot_formdesigner.services.validators
  rel: references
---

# `parrot_formdesigner.api.operations`

``PATCH /api/v1/forms/{form_id}/operations`` — atomic batched-edit endpoint.

Per FEAT-152 §2 Internal Behavior:

1. Parse the ``OperationsEnvelope`` from the body (Pydantic discriminated
   union over ``op``).
2. Optionally honour ``If-Match: <version>`` (Q1: optimistic concurrency).
3. Apply ops sequentially on a Pydantic-deep-copied working form.
4. On any per-op failure → 422 with the offending op's ``index`` + name.
5. Run ``FormValidator.check_schema`` on the working copy → 422 if errors.
6. Bump the form version via ``_bump_version``.
7. Persist via ``registry.register(working_copy, persist=True, overwrite=True)``.
8. Return 200 with ``{"form": working_copy.model_dump()}``.

Per Q2 (resolved): the existing PUT (``update_form``) and RFC-7396 PATCH
(``patch_form``) endpoints stay alongside this — full-replace and
merge-patch use cases differ from granular UI edits.

## Classes

- **`AddSection(_OpBase)`** — Insert a new section. Optional ``position`` indexes the section list.
- **`AddField(_OpBase)`** — Insert a new field into an existing section.
- **`MoveField(_OpBase)`** — Move a field across (or within) sections.
- **`RemoveField(_OpBase)`** — Remove a field from a section.
- **`UpdateField(_OpBase)`** — Apply RFC 7396 merge-patch to a single field.
- **`UpdateSectionMeta(_OpBase)`** — Apply RFC 7396 merge-patch to a section's metadata.
- **`UpdateFormMeta(_OpBase)`** — Apply RFC 7396 merge-patch to the form-level meta.
- **`DuplicateField(_OpBase)`** — Duplicate a field within the same (or another) section.
- **`OperationsEnvelope(BaseModel)`** — Top-level body shape for ``PATCH .../operations``.
- **`OperationError(Exception)`** — Per-op apply failure carried back to the HTTP layer.

## Functions

- `async def handle_operations(request: web.Request) -> web.Response` — PATCH /api/v1/forms/{form_id}/operations — atomic batched edits.
