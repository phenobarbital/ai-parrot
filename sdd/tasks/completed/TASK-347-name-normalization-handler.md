# TASK-347: Integrate Name Slugification & Dedup into _put_database()

**Feature**: API Bot Creation — Normalization & Provisioning
**Feature ID**: FEAT-049
**Spec**: `sdd/specs/new-api-bot-creation.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: M (2-4h)
**Depends-on**: TASK-345, TASK-346
**Assigned-to**: unassigned

---

## Context

> Core handler integration for FEAT-049. Wires the naming utilities from TASK-345 into the `_put_database()` method and augments the response with the final slugified name.
> Implements spec Section 3 — Module 2, changes #1 and partial #2.

---

## Scope

### 1. Name normalization in `_put_database()`

At the top of `_put_database()`, before the duplicate check:

```
original_name = payload.get('name', '').strip()
```

- Import `slugify_name` and `deduplicate_name` from `parrot.utils.naming`.
- Call `slug = slugify_name(original_name)`.
  - If `ValueError` (empty slug): return 400 with `{"message": "Name produces an empty slug after normalization. Provide a name with alphanumeric characters."}`.
- Call `final_name = await deduplicate_name(slug, self._check_duplicate)`.
  - If `ValueError` (exhaustion): return 409 with `{"message": "All name variants are taken. Choose a different name."}`.
- Set `payload['name'] = final_name`.

### 2. Preserve original name in description

- If `original_name != final_name`:
  - Get existing description: `desc = payload.get('description', '') or ''`
  - Set `payload['description'] = f"Display name: {original_name}. {desc}".strip()`

### 3. Augment response

- The PUT response dict should include:
  - `"name": final_name` (the slugified, deduplicated name)
  - `"original_name": original_name` (only if it differs from `final_name`)

**NOT in scope**: Naming utility implementation (TASK-345), registry cleanup (TASK-346), vector store provisioning (TASK-348).

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `parrot/handlers/bots.py` | MODIFY | Add slug + dedup logic to `_put_database()`, augment response |

---

## Implementation Notes

- `_check_duplicate` already has the right signature for `exists_fn`: `async (name: str) -> str | None`.
- The `deduplicate_name` function is async, so `_put_database` (already async) can await it directly.
- The slugification must happen BEFORE the `BotModel` is created, since `name` is passed to the model constructor.
- Do NOT modify the `_put_registry` path — this is scoped to database agents only.

---

## Acceptance Criteria

- [x] `PUT /api/v1/bots` with `name: "My Cool Bot"` creates agent with `name: "my-cool-bot"`.
- [x] `PUT /api/v1/bots` with `name: "my-cool-bot"` passes through unchanged (idempotent).
- [x] Creating two agents with `name: "My Bot"` results in `"my-bot"` and `"my-bot-2"`.
- [x] `PUT /api/v1/bots` with `name: "!@#$%"` returns 400.
- [x] When slug differs from input, description contains `"Display name: {original}."`.
- [x] Response includes `"name": "<final-slug>"`.
- [x] Existing GET/POST/DELETE operations are unaffected.
