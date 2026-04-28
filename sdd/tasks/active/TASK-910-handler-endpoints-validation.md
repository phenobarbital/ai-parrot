# TASK-910: Accept and persist reranker/parent_searcher configs in bot endpoints

**Feature**: FEAT-133 — DB-Persisted Reranker & Parent-Searcher Config for AI Bots
**Spec**: `sdd/specs/bot-reranker-and-parent-searcher-config.spec.md`
**Status**: pending
**Priority**: medium
**Estimated effort**: M (2-4h)
**Depends-on**: TASK-904, TASK-907
**Assigned-to**: unassigned

---

## Context

`packages/ai-parrot/src/parrot/handlers/bots.py` exposes POST/PUT/PATCH
endpoints that persist `BotModel` rows. They must accept the two new fields
end-to-end. Validation policy is **shallow** (only `isinstance(value, dict)`)
— deep validation of `type` happens at factory call time. Implements spec
section 3 / Module 6.

---

## Scope

- Update the POST/PUT/PATCH handlers in
  `packages/ai-parrot/src/parrot/handlers/bots.py` to:
  1. Allow `reranker_config` and `parent_searcher_config` keys in the
     incoming JSON payload.
  2. Apply shallow validation: if either key is present and not an instance
     of `dict`, return HTTP 400 with a clear error.
  3. Persist the values via `BotModel(**payload)` (already works once the
     fields exist on `BotModel` — TASK-907).
  4. Roundtrip the values on GET (no special handling needed if `BotModel`
     serializes them; verify by reading the GET response).
- Do NOT touch `_provision_vector_store` (line 777) — reranker and
  parent_searcher have no DB-side provisioning.
- Add a handler-level integration test that:
  1. POSTs a new bot with both new fields populated.
  2. GETs it back and verifies the values roundtripped.
  3. POSTs a bot with `reranker_config = "not-a-dict"` and asserts a 400.

**NOT in scope**:
- Form-builder / UI introspection — out of scope per spec §1.
- Migration of existing rows — out of scope per spec §1.
- Factory invocation at the handler level — happens in `BotManager`
  (TASK-908). Handlers persist the dict; the manager validates types.

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot/src/parrot/handlers/bots.py` | MODIFY | Shallow validation of new fields in POST/PUT/PATCH |
| `packages/ai-parrot/tests/handlers/test_bot_endpoints_factories.py` | CREATE | Roundtrip + 400-on-bad-shape |

---

## Codebase Contract (Anti-Hallucination)

### Verified Imports
```python
# Already present in handlers/bots.py:
from ..handlers.models import BotModel
```

### Existing Signatures to Use
```python
# packages/ai-parrot/src/parrot/handlers/bots.py:730-770 — POST flow
payload = ...                                           # parsed JSON
bot_model = BotModel(**payload)                         # line 741
await bot_model.insert()                                # line 742
bot_data = bot_model.to_bot_config()                    # line 745 — must already include the new keys (TASK-907)
bot_instance = await self._register_bot_into_manager(bot_data, self.request.app)  # line 748
vs_config = payload.get('vector_store_config') or {}    # line 753 — pattern to mirror
await self._provision_vector_store(bot_instance, vs_config, ...)  # line 754 — DO NOT change

# _provision_vector_store: packages/ai-parrot/src/parrot/handlers/bots.py:777
# Stays as-is.
```

### Does NOT Exist
- ❌ Any handler-level reranker/parent provisioning helper — does not exist
  and MUST NOT be created (factory invocation lives in the manager only).
- ❌ A schema validator on the new dicts — out of scope.

---

## Implementation Notes

### Shallow validation snippet
```python
for key in ("reranker_config", "parent_searcher_config"):
    if key in payload and not isinstance(payload[key], dict):
        return self.error(
            response={"message": f"{key} must be a JSON object"},
            status=400,
        )
```

Apply this guard at the top of POST and PUT/PATCH handlers, BEFORE
`BotModel(**payload)`.

### Pattern to follow
Mirror how `vector_store_config` is read at line 753 — `payload.get(...) or {}`.
The dict travels untouched through `BotModel(**payload)` → `to_bot_config()`
→ `BotManager` (which calls the factories at load time).

### Key Constraints
- Do not import the factories in this module. Factory invocation belongs
  to `BotManager` (TASK-908) — keeping them out of the handler avoids a
  network/runtime dep on `transformers` at HTTP-request time.
- The handler MUST allow `{}` (empty dict) — that is the back-compat
  default and must persist as `{}`, not be stripped.

### References in Codebase
- `parrot/handlers/bots.py:730-775` — POST handler.
- `parrot/handlers/bots.py:777-870` — `_provision_vector_store` (DO NOT modify).

---

## Acceptance Criteria

- [ ] POST with `reranker_config = {"type": "llm"}` persists and the GET
  response includes the same dict.
- [ ] POST with `parent_searcher_config = {"type": "in_table", "expand_to_parent": true}`
  persists and roundtrips.
- [ ] POST with `reranker_config = "not-a-dict"` returns HTTP 400 with a
  clear message.
- [ ] POST with no new keys still succeeds (back-compat).
- [ ] POST with `reranker_config = {}` persists `{}` (not None).
- [ ] `_provision_vector_store` is unchanged.
- [ ] `pytest packages/ai-parrot/tests/handlers/test_bot_endpoints_factories.py -v`
  passes.
- [ ] `ruff check packages/ai-parrot/src/parrot/handlers/bots.py` clean.
- [ ] Maps to spec AC2 + the persistence half of AC6/AC7.

---

## Test Specification

```python
# packages/ai-parrot/tests/handlers/test_bot_endpoints_factories.py
import pytest

# Use the project's standard handler test fixtures (aiohttp client +
# in-memory or test DB). Shape:

@pytest.mark.asyncio
async def test_post_then_get_roundtrips_new_configs(client, fresh_db):
    payload = {
        "name": "test-bot-feat-133",
        "reranker_config": {"type": "llm", "client_ref": "bot"},
        "parent_searcher_config": {"type": "in_table", "expand_to_parent": True},
    }
    resp = await client.post("/bots", json=payload)
    assert resp.status == 201

    resp = await client.get("/bots/test-bot-feat-133")
    body = await resp.json()
    assert body["reranker_config"]["type"] == "llm"
    assert body["parent_searcher_config"]["expand_to_parent"] is True


@pytest.mark.asyncio
async def test_post_rejects_non_dict_reranker_config(client, fresh_db):
    resp = await client.post(
        "/bots",
        json={"name": "bad", "reranker_config": "not-a-dict"},
    )
    assert resp.status == 400


@pytest.mark.asyncio
async def test_post_without_new_keys_still_works(client, fresh_db):
    resp = await client.post("/bots", json={"name": "bare"})
    assert resp.status == 201
```

---

## Agent Instructions

1. Read spec section 3 (Module 6).
2. Confirm TASK-904 (DDL) and TASK-907 (BotModel fields) are completed.
3. Verify the Codebase Contract — re-read `handlers/bots.py:725-775`.
4. Update `tasks/.index.json` → `"in-progress"`.
5. Add the shallow-validation guard in POST/PUT/PATCH.
6. Add tests, run them green.
7. `ruff check packages/ai-parrot/src/parrot/handlers/bots.py`.
8. Move this file to `tasks/completed/` and update the index.

---

## Completion Note

*(Agent fills this in when done)*

**Completed by**:
**Date**:
**Notes**:

**Deviations from spec**: none | describe if any
