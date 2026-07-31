# TASK-2000: EditToolkit — UID params for all field tools

**Feature**: FEAT-393 — Stable UUID-Based Field Identity (field_uid)
**Spec**: `sdd/specs/formdesigner-field-uid.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: M (2-4h)
**Depends-on**: TASK-1999
**Assigned-to**: unassigned

---

## Context

Implements Module 6 of FEAT-393 (spec §3, blueprint §9). The LLM-facing
EditToolkit (heaviest `field_id` consumer, 69 refs) switches its addressing
to `field_uid`/`section_uid` while keeping LLM ergonomics: search by
name/label, UIDs in every result.

---

## Scope

- `_find_field_and_section(field_uid)` delegates to `find_field_by_uid`.
- Tool params switch to UID strings: `get_field`, `update_field`,
  `remove_field`, `move_field`, `add_dependency`, `update_dependency`,
  `remove_dependency`, `add_post_dependency`, `remove_post_dependency`
  (owner param; `remove_post_dependency`'s `target` param is also a UID).
- `search_fields`: still matches query against `field_id`/label (exact +
  regex); each result gains `"field_uid"`.
- `get_form_summary`: emits both `field_uid` and `field_id` per field (and
  `section_uid`/`section_id`).
- `add_field`: returns the minted `field_uid` in the result.
- Dependency tools: rule/post dicts may reference other fields by authored
  `field_id`; after applying, route the form through
  `resolve_rule_references` (via the ops layer from TASK-1999).
- `_replace_field_in_form`: match on `f.field_uid == field_uid`.
- Update the toolkit docstrings the LLM reads (tool descriptions must state
  "field_uid (UUID string) — obtain from get_form_summary or search_fields").
- Update `tools/create_form.py` EditToolkit surface docs (:154-170).
- Update existing toolkit tests + spec §4 Module 6 test.

**NOT in scope**: operations layer internals (TASK-1999); prompt-contract
changes for form GENERATION (TASK-2001).

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/parrot-formdesigner/src/parrot_formdesigner/tools/edit_toolkit.py` | MODIFY | UID params, summary/search enrichment |
| `packages/parrot-formdesigner/src/parrot_formdesigner/tools/create_form.py` | MODIFY | EditToolkit surface docs (:154-170) |
| `packages/parrot-formdesigner/tests/unit/tools/test_edit_toolkit*.py` | MODIFY | UID addressing |

---

## Codebase Contract (Anti-Hallucination)

### Verified Imports
```python
from parrot_formdesigner.tools.edit_toolkit import EditToolkit  # tools/edit_toolkit.py:50
from parrot_formdesigner.core.resolution import find_field_by_uid  # TASK-1997
```

### Existing Signatures to Use
```python
# tools/edit_toolkit.py — class EditToolkit(AbstractToolkit) (:50)
def _find_field_and_section(self, field_id: str) -> tuple[FormField, FormSection] | tuple[None, None]:
    # :111-125 — iterates section.fields, isinstance(field, FormField) check (:123)
async def get_form_summary(self) -> dict          # :142; emits "field_id" (:173)
async def get_field(self, field_id: str) -> dict  # :201; err :215
async def search_fields(self, ...)                # :222; exact (:263), regex (:264), result key (:270)
async def update_field(self, section_id: str, field_id: str, patch: dict) -> dict  # :282
async def add_field(self, ...)                    # :321; returns validated_field.field_id (:349)
async def remove_field(self, section_id: str, field_id: str) -> dict  # :362
async def add_dependency(self, field_id: str, rule: dict) -> dict     # :396
async def update_dependency(self, field_id: str, patch: dict) -> dict # :434 (merge → add_dependency :453)
async def remove_dependency(self, field_id: str) -> dict              # :455
async def add_post_dependency(self, field_id: str, post: dict) -> dict  # :474
async def remove_post_dependency(self, field_id: str, target: str) -> dict  # :512 — TWO ids: owner + target
def _replace_field_in_form(self, form, section_id, field_id, new_field)  # :548; match :572
async def _check_rules(self, form: FormSchema) -> list[str]           # :578 — delegates to FormValidator
async def move_field(self, from_section, field_id, to_section, position)  # :664; ops payload (:686)
# Toolkit methods build operations payloads and route through api/operations apply fns
```

### Does NOT Exist
- ~~`EditToolkit.get_field_by_uid`~~ — do not add parallel methods; CHANGE the existing ones (clean break)
- ~~UID params on tool methods today~~ — created HERE
- ~~`search_fields` matching on field_uid~~ — search stays name/label-based by design

---

## Implementation Notes

### Pattern to Follow
Spec §9 "Module 6" blueprint. Tool params are `str` (LLM-facing) parsed to
`uuid.UUID` at entry — return a structured error dict (the toolkit's existing
error convention) on invalid UUID, never raise raw.

### Key Constraints
- Tool docstrings ARE the LLM's API docs — every changed method's docstring
  must show a UUID example value.
- `AbstractToolkit` pattern (`parrot/tools/`): keep tool registration
  mechanics untouched.
- Result dicts keep `field_id` alongside `field_uid` everywhere (LLM needs
  the human key for rule authoring).

### References in Codebase
- `api/operations.py` (post-TASK-1999) — the ops payload shapes the toolkit builds

---

## Acceptance Criteria

- [ ] All 12 methods address by UID; invalid UUID string → structured error dict
- [ ] `search_fields` finds by field_id/label, returns `field_uid` per hit
- [ ] `get_form_summary` emits uid+id pairs at section and field level
- [ ] Dependency tools accept `field_id`-authored rule dicts; stored refs are UIDs
- [ ] `pytest packages/parrot-formdesigner/tests/unit/tools/ -v` passes; `ruff check` clean

---

## Test Specification

```python
# packages/parrot-formdesigner/tests/unit/tools/test_edit_toolkit_uid.py
async def test_get_field_by_uid(toolkit): ...
async def test_get_field_invalid_uuid_returns_error(toolkit): ...
async def test_search_fields_returns_uids(toolkit): ...
async def test_update_field_rename_via_uid(toolkit): ...
async def test_add_dependency_authored_by_field_id_stored_as_uid(toolkit): ...
async def test_remove_post_dependency_uid_owner_and_target(toolkit): ...
async def test_summary_pairs_uid_and_id(toolkit): ...
```

---

## Agent Instructions

1. **Read the spec** §9 Module 6; verify TASK-1999 completed.
2. **Verify the contract** anchors.
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
