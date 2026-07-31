# TASK-2003: Partial saves — UID-keyed storage behind field_id wire payloads

**Feature**: FEAT-393 — Stable UUID-Based Field Identity (field_uid)
**Spec**: `sdd/specs/formdesigner-field-uid.spec.md`
**Status**: pending
**Priority**: medium
**Estimated effort**: S (< 2h)
**Depends-on**: TASK-1997
**Assigned-to**: unassigned

---

## Context

Implements Module 9 of FEAT-393 (spec §3, blueprint §9). Partial-save wire
payloads stay `{field_id: value}` (submission-payload symmetry), but Redis
values are re-keyed by `field_uid` so a mid-session `field_id` rename no
longer orphans saved answers. Translation happens at the HANDLER boundary;
`PartialSaveService` stays schema-agnostic.

---

## Scope

- `FormAPIHandler.save_partial` (answer loop): resolve each incoming
  `field_id` via `_find_field`; unknown `field_id` → field error entry,
  NOT stored (removes today's silent acceptance); store
  `{str(field.field_uid): value}` via `PartialSaveService.save`.
- Partial read path (the handler that returns saved partials): map stored
  UID keys back to CURRENT `field_id`s via `find_field_by_uid`; UIDs whose
  field was deleted are dropped silently.
- `services/partial_saves.py`: code unchanged; update docstrings (:84 "Mapping
  of field_uid to new values"; `core/partial.py` `PartialFormData.data`/
  `field_errors` docstrings).
- Spec §4 Module 9 tests (incl. the rename-survival test).

**NOT in scope**: Redis key structure (`_redis_key` :174 uses form/session
only — untouched); submission validation (stays field_id-keyed).

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/parrot-formdesigner/src/parrot_formdesigner/api/handlers.py` | MODIFY | save_partial loop + read-path mapping |
| `packages/parrot-formdesigner/src/parrot_formdesigner/services/partial_saves.py` | MODIFY | docstrings only |
| `packages/parrot-formdesigner/src/parrot_formdesigner/core/partial.py` | MODIFY | docstrings only |
| `packages/parrot-formdesigner/tests/unit/` | MODIFY/CREATE | re-key + rename tests |

---

## Codebase Contract (Anti-Hallucination)

### Verified Imports
```python
from parrot_formdesigner.core.resolution import find_field_by_uid  # TASK-1997
```

### Existing Signatures to Use
```python
# api/handlers.py
def _find_field(self, form: FormSchema, field_id: str) -> "FormField | None"  # :284-301
async def save_partial(self, request: web.Request) -> web.Response  # :306
# body: {"answers": {field_id: value}} (:316); loop :380-385:
#   for field_id, value in answers.items(): field = self._find_field(...); 
#   validate `if field is not None`; field_errors[field_id] = errors
#   → unknown field_ids are currently silently ACCEPTED and stored

# services/partial_saves.py
async def save(self, form_id: str, session_id: str, answers: dict[str, Any]) -> PartialFormData  # :67-117
#   merge: {**(existing.data if existing else {}), **answers} (:97-100) — last-write-wins
#   PartialFormData(..., field_errors={}, ...) (:103-110) — errors NOT stored in Redis
async def get(self, form_id: str, session_id: str) -> PartialFormData | None  # :119-139
def _redis_key(self, form_id: str, session_id: str) -> str  # :174 — no field component

# core/partial.py — class PartialFormData(BaseModel) (:15); data (:25), field_errors (:28)
```

### Does NOT Exist
- ~~a partial-save READ endpoint distinct from save~~ — verify: the handler may return
  the merged state from `save_partial` itself; if no separate GET exists, the
  back-mapping applies to the RESPONSE of save_partial (merged state) — check
  `api/routes.py` for a partial GET route before assuming
- ~~schema access inside PartialSaveService~~ — service must stay form-schema-agnostic;
  ALL translation in the handler
- ~~stored field_errors in Redis~~ — errors are response-only (:107)

---

## Implementation Notes

### Pattern to Follow
Spec §9 "Module 9" blueprint — the handler-boundary loop is given verbatim.

### Key Constraints
- Response shape compatibility: the handler's response reports answers/errors
  keyed by `field_id` — after storing UID-keyed, map the merged state back
  before serializing the response.
- The merge in `save()` is last-write-wins on RAW keys — since all writes now
  use UID keys, old field_id-keyed entries from before this change are
  effectively orphaned; acceptable (pre-production, Redis TTL expires them).
- Unknown-field rejection returns HTTP 200 with per-field errors (matches
  existing validation-error shape), not a 4xx — preserve the endpoint's
  contract.

### References in Codebase
- `sdd/specs/formdesigner-partial-saves.spec.md` — original feature spec

---

## Acceptance Criteria

- [ ] Redis-persisted `PartialFormData.data` keyed by UID strings
- [ ] Wire request/response keyed by `field_id`
- [ ] Rename survival test passes: save → rename field_id (ops) → read shows answer under NEW field_id
- [ ] Unknown `field_id` in answers → field error, value not stored
- [ ] Deleted-field UIDs dropped silently on read
- [ ] `pytest packages/parrot-formdesigner/tests/ -v` passes; `ruff check` clean

---

## Test Specification

```python
# packages/parrot-formdesigner/tests/unit/api/test_partial_saves_uid.py
async def test_partial_save_rekeyed_by_uid(client, redis_stub): ...
async def test_partial_save_response_keyed_by_field_id(client): ...
async def test_partial_save_survives_rename(client): ...
async def test_unknown_field_rejected_not_stored(client): ...
async def test_deleted_field_uid_dropped_on_read(client): ...
```

---

## Agent Instructions

1. **Read the spec** §9 Module 9; verify TASK-1997 completed.
2. **Verify the contract** — especially whether a separate partial GET route exists (`grep partial api/routes.py`).
3. **Update status** in `sdd/tasks/index/formdesigner-field-uid.json` → `"in-progress"`.
4. **Implement**, run tests, verify acceptance criteria.
5. **Move this file** to `sdd/tasks/completed/`, update index → `"done"`, fill Completion Note.

---

## Completion Note

*(Agent fills this in when done)*

**Completed by**:
**Date**:
**Notes**:

**Deviations from spec**: none
