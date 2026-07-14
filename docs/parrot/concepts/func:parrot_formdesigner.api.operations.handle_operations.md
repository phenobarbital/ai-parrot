---
type: Concept
title: handle_operations()
id: func:parrot_formdesigner.api.operations.handle_operations
tags:
- concept
timestamp: '2026-07-14T22:20:21+00:00'
summary: PATCH /api/v1/forms/{form_id}/operations — atomic batched edits.
---

# handle_operations

```python
async def handle_operations(request: web.Request) -> web.Response
```

PATCH /api/v1/forms/{form_id}/operations — atomic batched edits.

Steps (per spec §2 Internal Behavior):

1. Parse ``form_id`` from match_info.
2. Load form from ``request.app['form_registry']``; 404 if missing.
3. Parse + validate the ``OperationsEnvelope`` body; 422 on shape errors.
4. Honour ``If-Match`` header (Q1); 412 on mismatch.
5. Apply ops sequentially on a deep-copy working form. On the first
   ``OperationError``, return 422 with the offending op's index/name.
6. ``FormValidator.check_schema`` on the working copy; 422 if errors.
7. Bump the version via ``_bump_version``.
8. Persist via ``registry.register(working_copy, persist=True, overwrite=True)``.
9. Return 200 with ``{"form": working_copy.model_dump()}``.
