# TASK-2006: Question bank — rename field_id → question_id + fresh field_uid on insertion

**Feature**: FEAT-393 — Stable UUID-Based Field Identity (field_uid)
**Spec**: `sdd/specs/formdesigner-field-uid.spec.md`
**Status**: pending
**Priority**: medium
**Estimated effort**: M (2-4h)
**Depends-on**: TASK-1996
**Assigned-to**: unassigned

---

## Context

Implements Module 12 of FEAT-393 (spec §3, blueprint §9). The bank's
`field_id` is a minted bank-entry UUID with NO relation to
`FormField.field_id` — the naming collision is eliminated by renaming it
`question_id` end to end. Bank entries are templates: every insertion into a
form mints a fresh `field_uid`.

---

## Scope

- `ReusableField.field_id` → `question_id`; `ReusableFieldRef.bank_field_id`
  → `question_id`.
- DDL: column `field_id` → `question_id`; `UNIQUE(question_id, tenant)`.
  (Existing-install migration is TASK-2008.)
- All four SQL statements (`_INSERT_SQL`, `_SELECT_SQL`, `_SELECT_ALL_SQL`,
  `_INCREMENT_SQL`) use `question_id`.
- `_row_to_entry`: `question_id=row["question_id"]`.
- Method params rename (`get_field(question_id)`, `increment_usage(question_id, ...)`,
  `create_field` internals); method NAMES unchanged. In-memory fallback dict
  keys keyed by `question_id`.
- `resolve_ref`: `definition_dict.pop("field_uid", None)` after deepcopy
  (fresh identity via default_factory); raise `ValueError` if
  `ref.overrides` contains `field_uid`.
- Update docstrings/examples (:113-120) and tests; spec §4 Module 12 tests.

**NOT in scope**: renaming methods; DB migration for existing installs
(TASK-2008); any caller changes outside this service (grep for callers and
update param names only).

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/parrot-formdesigner/src/parrot_formdesigner/services/question_bank.py` | MODIFY | full rename + resolve_ref minting |
| callers of `ReusableFieldRef`/`QuestionBankService` (grep) | MODIFY | param/attr rename fallout |
| `packages/parrot-formdesigner/tests/unit/services/test_question_bank*.py` | MODIFY | rename + minting tests |

---

## Codebase Contract (Anti-Hallucination)

### Verified Imports
```python
from parrot_formdesigner.services.question_bank import (
    QuestionBankService, ReusableField, ReusableFieldRef,
)
```

### Existing Signatures to Use
```python
# services/question_bank.py (verbatim from dev@94d8fc543)
class ReusableField(BaseModel):      # :29-48; extra="forbid" (:41)
    field_id: str                    # :43 — "Unique identifier for this bank entry (UUID string)"
    definition: FormField            # :44
    tenant: str; usage_forms: int = 0; usage_responses: int = 0; created_at: datetime | None
class ReusableFieldRef(BaseModel):   # :51-67; extra="forbid" (:64)
    bank_field_id: str               # :66
    overrides: dict[str, Any] | None = None  # :67
_CREATE_TABLE_SQL   # :74-85 — field_id VARCHAR(255) NOT NULL (:77); UNIQUE(field_id, tenant) (:83)
_INSERT_SQL         # :87-91 — ON CONFLICT (field_id, tenant) DO NOTHING
_SELECT_SQL         # :93; _SELECT_ALL_SQL :95 (ORDER BY field_id); _INCREMENT_SQL :97-102
class QuestionBankService:           # :105; in-memory fallback dict self._mem (:151)
# create_field (:176-190) — mints uuid4 for the bank entry regardless of source field
# get_field(self, field_id: str) -> ReusableField | None (:209-226)
# list_fields (:240) — sorts by e.field_id; increment_usage (:244-266)
async def resolve_ref(self, ref: ReusableFieldRef) -> FormField:   # :271-297
    entry = await self.get_field(ref.bank_field_id)                # :287
    definition_dict = copy.deepcopy(entry.definition.model_dump()) # :292
    if ref.overrides: definition_dict.update(ref.overrides)        # :294-295
    return FormField.model_validate(definition_dict)               # :297
def _row_to_entry(self, row) -> ReusableField                      # :303-322; field_id=row["field_id"] (:316)
```

### Does NOT Exist
- ~~any relation between bank field_id and FormField.field_id~~ — the bank id is minted (:176-177); the rename is safe
- ~~`get_question` / `create_question` methods~~ — method names do NOT change
- ~~bank REST handlers with `field_id` params~~ — VERIFY with grep before assuming; update any callers found (`ReusableFieldRef(bank_field_id=...)` construction sites)

---

## Implementation Notes

### Pattern to Follow
Spec §9 "Module 12" blueprint — resolve_ref diff given verbatim.

### Key Constraints
- `extra="forbid"` on both models means every construction site MUST be
  updated in the same commit — grep `bank_field_id` and `ReusableField(`
  across BOTH packages.
- After TASK-1996, `entry.definition.model_dump()` includes `field_uid` —
  the `pop` is what guarantees a fresh mint; the overrides guard prevents
  callers smuggling one in.
- `mode="json"` vs default dump: `model_dump()` returns `uuid.UUID` objects
  in the dict; `FormField.model_validate` accepts them — no serialization
  churn needed.

---

## Acceptance Criteria

- [ ] `question_id` end to end: models, DDL, 4 SQL statements, params, in-memory keys, row mapping
- [ ] `grep -rn "bank_field_id\|field_bank.*field_id" packages/parrot-formdesigner/src/` → zero hits
- [ ] Two `resolve_ref` insertions of one bank entry → two distinct `field_uid`s
- [ ] `overrides={"field_uid": ...}` → ValueError
- [ ] `pytest packages/parrot-formdesigner/tests/ -v` passes; `ruff check` clean

---

## Test Specification

```python
# packages/parrot-formdesigner/tests/unit/services/test_question_bank_rename.py
async def test_question_id_model_roundtrip(): ...
async def test_ddl_and_sql_use_question_id(): ...
async def test_resolve_ref_mints_fresh_field_uid(bank_with_entry):
    a = await svc.resolve_ref(ReusableFieldRef(question_id=qid))
    b = await svc.resolve_ref(ReusableFieldRef(question_id=qid))
    assert a.field_uid != b.field_uid
async def test_overrides_cannot_set_field_uid(bank_with_entry): ...
async def test_increment_usage_by_question_id(bank_with_entry): ...
```

---

## Agent Instructions

1. **Read the spec** §9 Module 12; verify TASK-1996 completed.
2. **Verify the contract**; grep all `bank_field_id` / `ReusableFieldRef(` construction sites in both packages.
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
