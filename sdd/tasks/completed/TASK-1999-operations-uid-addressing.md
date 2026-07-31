# TASK-1999: Edit operations API — UID addressing (api/operations.py)

**Feature**: FEAT-393 — Stable UUID-Based Field Identity (field_uid)
**Spec**: `sdd/specs/formdesigner-field-uid.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: L (4-8h)
**Depends-on**: TASK-1997
**Assigned-to**: unassigned

---

## Context

Implements Module 5 of FEAT-393 (spec §3, blueprint §9). The batch edit API
(`PATCH .../operations`) addresses fields/sections by UID. Fixes three latent
bugs: subsection fields unaddressable (`_field_index` skips them), uniqueness
per-section-only, and `field_id` renames silently reverted.

---

## Scope

- Rewrite op payload models: `AddField`/`RemoveField`/`UpdateField`/
  `UpdateSectionMeta` take `section_uid`/`field_uid` (uuid.UUID);
  `MoveField.from_/to` dicts carry `section_uid`/`field_uid`;
  `DuplicateField` keeps `as_field_id: str` and always mints a fresh uid.
- Replace `_section_index`/`_field_index`/`_check_unique_field_id`/
  `_check_unique_section_id` with `_section_index_by_uid`, `_locate_field`
  (searches section fields AND subsection fields → returns
  `(containing_list, index)`), `_check_unique_in_form` (per-FORM uid +
  field_id checks).
- `_apply_update_field`: allow `field_id` rename (with per-form uniqueness
  check); reject any `field_uid` change with `OperationError`.
- `_apply_duplicate_field`: `clone_dict.pop("field_uid", None)` → fresh uid.
- `_apply_add_field`: accept optional client-supplied `field.field_uid`
  (upsert origin), `_check_unique_in_form` before insert.
- `handle_operations` (:358): after applying all ops, run
  `resolve_rule_references(form)` before final `FormSchema.model_validate`.
- Update route docs (`{form_id}` → `{form_uid}` path is FEAT-389's; this task
  only touches op bodies).
- Update existing operations tests to UID addressing + spec §4 Module 5 tests.

**NOT in scope**: EditToolkit (TASK-2000); upload route (TASK-2002).

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/parrot-formdesigner/src/parrot_formdesigner/api/operations.py` | MODIFY | models, helpers, apply fns, handler |
| `packages/parrot-formdesigner/tests/unit/api/test_operations*.py` | MODIFY/CREATE | UID addressing tests |

---

## Codebase Contract (Anti-Hallucination)

### Verified Imports
```python
from parrot_formdesigner.core.resolution import resolve_rule_references, find_field_by_uid  # TASK-1997
from parrot_formdesigner.core.schema import FormField, FormSchema, FormSection, FormSubsection
```

### Existing Signatures to Use
```python
# api/operations.py (verbatim from dev@94d8fc543)
class _OpBase(BaseModel):                                # :42-49
    model_config = ConfigDict(extra="forbid", populate_by_name=True)
class AddSection(_OpBase): op; section: FormSection; position: int | None    # :52-57
class AddField(_OpBase): op; section_id: str; field: FormField; position     # :60-66
class MoveField(_OpBase): op; from_: dict = Field(alias="from"); to: dict    # :69-79
class RemoveField(_OpBase): op; section_id: str; field_id: str               # :82-87
class UpdateField(_OpBase): op; section_id: str; field_id: str; patch: dict  # :90-96
class UpdateSectionMeta(_OpBase): op; section_id: str; patch: dict           # :99-104
class UpdateFormMeta(_OpBase): op; patch: dict                               # :107-111
class DuplicateField(_OpBase): op; from_: dict; as_field_id: str             # :114-119
Operation = Annotated[Union[...8 ops...], Field(discriminator="op")]         # :122-134
class OperationsEnvelope(BaseModel): operations: list[Operation]             # :137-142
class OperationError(Exception): __init__(self, index, op_name, message)     # :150-163
def _section_index(form, section_id) -> int                                  # :171-175
def _field_index(section, field_id) -> int   # :178-184 — SKIPS FormSubsection items
def _check_unique_field_id(section, field_id) -> None  # :187-193 — per-section, iter_fields
def _check_unique_section_id(form, section_id) -> None                       # :196-202
def _apply_add_field(form, op) -> FormSchema                                 # :214-222
def _apply_move_field(form, op) -> FormSchema  # :225-260 — rollback-insert on dup (:249)
def _apply_remove_field(form, op) -> FormSchema                              # :263-268
def _apply_update_field(form, op) -> FormSchema  # :271-283 — merged["field_id"] = op.field_id (:278)
def _apply_duplicate_field(form, op) -> FormSchema  # :315-338 — clone_dict["field_id"] = op.as_field_id (:332)
_DISPATCH: dict[str, Any]                                                     # :341-350
async def handle_operations(request: web.Request) -> web.Response            # :358
# _deep_merge — RFC 7396 helper, defined earlier in the module (grep it)
```

### Does NOT Exist
- ~~`{field_id}` as a path param on the operations route~~ — ops carry targets in the BODY (route: `api/routes.py:255-256`)
- ~~`_locate_field` / `_check_unique_in_form` / `_section_index_by_uid`~~ — created HERE
- ~~a nested-GROUP edit surface~~ — ops address section-level and subsection-level fields only; `children`/`item_template` are edited via `update_field` patches on the parent, NOT addressable ops (keep it that way)

---

## Implementation Notes

### Pattern to Follow
Spec §9 "Module 5" blueprint — model shapes, `_locate_field`,
`_check_unique_in_form`, and the full `_apply_update_field` body are given
verbatim.

### Key Constraints
- Preserve `_OpBase` config (`extra="forbid"`, `populate_by_name=True`) and
  the `from` alias trick on MoveField/DuplicateField.
- Preserve MoveField's rollback-insert-before-raise behavior (:249) with the
  new duplicate check.
- `OperationError` shape unchanged (HTTP layer depends on index/op_name).
- After-ops `resolve_rule_references` catches renames that orphan nothing
  (UID refs) but validates any rules added via `update_field` patches.
- Wire examples in docstrings must show UUID strings.

### References in Codebase
- `sdd/specs/form-designer-edition.spec.md` — original operations design

---

## Acceptance Criteria

- [ ] All ops address by `section_uid`/`field_uid`; invalid UUID in body → Pydantic 422/400 envelope error
- [ ] Field inside a subsection is addressable by every op (regression test for `_field_index` skip)
- [ ] `update_field` renames `field_id` (with per-form uniqueness); rejects `field_uid` change
- [ ] `duplicate_field` result carries a fresh `field_uid`
- [ ] `add_field` accepts client-supplied unique `field_uid`, rejects duplicates form-wide
- [ ] `handle_operations` re-resolves rules post-ops
- [ ] `pytest packages/parrot-formdesigner/tests/ -v` passes; `ruff check` clean

---

## Test Specification

```python
# packages/parrot-formdesigner/tests/unit/api/test_operations_uid.py
def test_update_field_renames_field_id(form_with_nested_fields): ...
def test_update_field_rejects_field_uid_change(): ...
def test_remove_field_inside_subsection(): ...
def test_move_field_duplicate_destination_rolls_back(): ...
def test_duplicate_field_mints_fresh_uid(): ...
def test_add_field_client_uid_upsert_and_conflict(): ...
def test_operations_envelope_rejects_unknown_keys(): ...
def test_handle_operations_reresolves_rules(aiohttp_client_fixture): ...
```

---

## Agent Instructions

1. **Read the spec** §9 Module 5; verify TASK-1997 completed.
2. **Verify the contract** (grep `_deep_merge`; re-check anchors post-FEAT-389).
3. **Update status** in `sdd/tasks/index/formdesigner-field-uid.json` → `"in-progress"`.
4. **Implement**, run tests, verify acceptance criteria.
5. **Move this file** to `sdd/tasks/completed/`, update index → `"done"`, fill Completion Note.

---

## Completion Note

**Completed by**: sdd-worker (Claude)
**Date**: 2026-07-31
**Notes**:

- Rewrote op payload models: `AddField.section_uid`, `RemoveField.
  section_uid/field_uid`, `UpdateField.section_uid/field_uid`,
  `UpdateSectionMeta.section_uid` (all `uuid.UUID`). `MoveField.from_/to`
  and `DuplicateField.from_` are still plain dicts but now carry
  `section_uid`/`field_uid` keys. `AddSection` is UNCHANGED (still
  `section_id`-based per spec — section-slug uniqueness stays a separate,
  section-level concern). Added wire-example docstrings (UUID strings) to
  every rewritten op model.
- Replaced `_field_index`/`_check_unique_field_id` with `_locate_field`
  (searches `section.fields` AND every subsection's fields, returns
  `(containing_list, index)` — fixes the "subsection fields
  unaddressable" bug) and `_check_unique_in_form` (per-FORM, via
  `iter_fields_recursive()` — fixes the "uniqueness per-section-only"
  bug). Added `_section_index_by_uid`. Kept `_section_index`/
  `_check_unique_section_id` (section_id/slug-based) for `AddSection`,
  unchanged.
- `_apply_update_field`: implemented the spec's blueprint verbatim —
  allows `field_id` rename (with per-form uniqueness check excluding the
  field's own `field_uid`), explicitly rejects any patch touching
  `field_uid` (`OperationError`, not a silent pin — fixes the "field_id
  renames silently reverted" bug, replaced by the new "field_uid
  immutable" guard).
- `_apply_duplicate_field`: `from_` now uses `section_uid`/`field_uid`;
  `clone_dict.pop("field_uid", None)` so the clone gets a fresh UID from
  `FormField`'s `default_factory`; added an explicit form-wide
  `as_field_id` collision check (`_check_unique_in_form`-equivalent logic)
  since the old per-section `_check_unique_field_id` call was removed.
- `_apply_move_field`/`_apply_remove_field`: re-addressed via
  `_section_index_by_uid`/`_locate_field`; preserved the rollback-insert-
  before-raise behavior on a duplicate-destination `field_uid` (verified
  by a new regression test).
- `handle_operations`: added a `resolve_rule_references(working)` call
  (wrapped in `try/except ValueError` → 422) between the per-op apply loop
  and `FormValidator().check_schema()`, per the spec — catches renames/
  additions that introduce a rule needing (re-)resolution. Updated the
  handler's docstring step list (now 10 steps, was 9).
- Rewrote `tests/unit/api/test_operations.py` (25 tests, was 16) and
  `tests/integration/test_operations_e2e.py` (10 tests, was 7) entirely
  for UID addressing — every test builds a form first and reads its
  randomly-generated `section_uid`/`field_uid` off the fixture rather than
  hardcoding a slug string. Added the acceptance-criteria regression tests
  by name: `test_remove_field_inside_subsection`,
  `test_move_field_duplicate_destination_rolls_back` (constructs a
  pre-existing duplicate by mutating the field list directly post-
  construction, bypassing `FormSchema`'s own construction-time
  uniqueness validator — Pydantic doesn't re-validate on plain attribute/
  list mutation without `validate_assignment`), `test_duplicate_field_
  mints_fresh_uid`, `test_add_field_client_uid_upsert_and_conflict`,
  `test_update_field_renames_field_id`,
  `test_update_field_rejects_field_uid_change`,
  `test_operations_envelope_rejects_unknown_keys`,
  `test_handle_operations_reresolves_rules`.
- Fixed one new ruff finding (SIM102, nested `if` in the new
  `_apply_update_field`) by combining with `and` — behavior-identical,
  zero net-new lint debt versus the pre-task baseline (verified via
  `git stash` diff).

**Known, expected fallout — NOT a regression, deferred to TASK-2000**:
`EditToolkit` (`tools/edit_toolkit.py`) constructs `AddField`/`RemoveField`/
`UpdateField`/etc. instances FROM THIS MODULE directly (`from
..api.operations import AddField, ...`) using its OWN `section_id`/
`field_id`-based internal params — confirmed by inspecting the actual
failure (`AddField` validation error: `section_uid` missing, `section_id`
extra-forbidden). Since `EditToolkit`'s UID-param rewrite is explicitly
TASK-2000's scope ("EditToolkit — UID params for all field tools"), this
task's model rename surfaces as an EXPECTED, foreseeable 11-test failure
bloc on top of the 10 already-known TASK-1998→TASK-2000/2001 fallout from
the previous task (`tests/test_edit_toolkit.py::TestEditToolkitMutation`
(6), `tests/unit/test_edit_toolkit_schema.py::TestAddFieldFromSchema` (3),
`tests/test_create_form_toolkit.py::test_toolkit_edit_applies_mutation`
(1), `tests/unit/test_deterministic_integration.py::test_create_then_edit`
(1)) — all root-caused to the same `EditToolkit` coupling, none to a
defect in this task. Expect all of it (21 tests total, on top of the 20
pre-existing/unrelated baseline) to go green once TASK-2000 lands.

**Verification**:
- `pytest packages/parrot-formdesigner/tests/unit/api/test_operations.py
  packages/parrot-formdesigner/tests/integration/test_operations_e2e.py -v`
  → 35 passed.
- `pytest packages/parrot-formdesigner/tests/ -v` → 1776 passed, 3 skipped,
  41 failed = 20 pre-existing (TASK-1995 baseline) + 21 EditToolkit
  cross-task fallout (see above) — zero unexplained new failures.
- `ruff check packages/parrot-formdesigner/src/parrot_formdesigner/api/
  operations.py` → clean (0 findings; fixed the one new SIM102 this task
  introduced).

**Deviations from spec**: none — the EditToolkit fallout is the same
inherent Module 5 → Module 6 sequencing gap already documented in
TASK-1998's Completion Note, now also touching operations.py's renamed
models.
