# TASK-2009: Test suite — shared fixtures, integration flows, fallout sweep

**Feature**: FEAT-393 — Stable UUID-Based Field Identity (field_uid)
**Spec**: `sdd/specs/formdesigner-field-uid.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: L (4-8h)
**Depends-on**: TASK-1995, TASK-1996, TASK-1997, TASK-1998, TASK-1999, TASK-2000, TASK-2001, TASK-2002, TASK-2003, TASK-2004, TASK-2005, TASK-2006, TASK-2007, TASK-2008
**Assigned-to**: unassigned

---

## Context

Implements Module 15 of FEAT-393 (spec §3). Final quality gate: shared
fixtures, the three end-to-end integration tests from spec §4, and a sweep of
any remaining test fallout across both packages.

---

## Scope

- Shared fixtures in `packages/parrot-formdesigner/tests/conftest.py`:
  `form_with_nested_fields` (sections + subsection + GROUP children + ARRAY
  item_template), `form_with_rules` (field_id-authored depends_on /
  post_depends / operations), `legacy_schema_json` (no UIDs, field_id-keyed
  rules) — consolidate duplicates that earlier tasks created locally.
- Integration tests (spec §4):
  - `test_edit_flow_rename_stability` — create → upload blob → rename
    field_id via operations → blob reachable, rules evaluate, partial save
    survives.
  - `test_llm_create_edit_roundtrip` — CreateFormTool (mocked LLM) →
    EditToolkit edits by UID → validate → store → reload → UIDs stable.
  - `test_migration_end_to_end` — legacy-shaped stored form → migration →
    loads clean, rules resolved, re-run no-op.
- Full-suite sweep: `pytest packages/parrot-formdesigner/tests/ -v` and
  `pytest packages/ai-parrot/tests/ -v` green; fix residual fallout (exact
  `model_dump()` shape assertions, ops payload params).
- Verify every spec §5 acceptance criterion has at least one covering test;
  list the mapping in the completion note.

**NOT in scope**: new features or behavior changes — test-only task; any
production-code fix needed here means a prior task is incomplete (reopen it
in the index and note it).

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/parrot-formdesigner/tests/conftest.py` | MODIFY | shared fixtures |
| `packages/parrot-formdesigner/tests/integration/test_field_uid_flows.py` | CREATE | 3 end-to-end flows |
| both packages' tests | MODIFY | residual fallout |

---

## Codebase Contract (Anti-Hallucination)

### Verified Imports
```python
# By this point ALL new interfaces exist (created by TASK-1996/1997):
from parrot_formdesigner.core.schema import FormField, FormSchema, walk_fields
from parrot_formdesigner.core.resolution import (
    resolve_rule_references, find_field_by_uid, resolve_answer,
)
```

### Existing Signatures to Use
- Fixture shapes: spec §4 "Test Data / Fixtures".
- Integration flow steps: spec §4 "Integration Tests" table — each step maps
  to an API/tool call implemented in TASK-1999/2000/2002/2003/2008.
- Existing test layout: `tests/unit/<area>/`, `tests/formdesigner/`,
  `tests/integration/` — follow the prevailing pytest-asyncio patterns
  (see `packages/parrot-formdesigner/tests/` conftest for event-loop/fixture
  conventions).

### Does NOT Exist
- ~~a live LLM in tests~~ — CreateFormTool tests use the existing mocked-client pattern (find it in current create_form tests)
- ~~a real S3/GCS in tests~~ — blob tests run on the temp/file backend
- ~~a live Redis requirement~~ — partial-save tests use the in-process fallback or the existing redis stub fixture (grep for it)

---

## Implementation Notes

### Key Constraints
- The rename-stability integration test is THE feature's reason to exist —
  it must exercise the real stack (ops handler + blob storage + partial saves
  + rule evaluator), not mocks of them.
- Coverage mapping (spec §5 criterion → test) goes in the completion note —
  the sdd-done review checks it.
- Run with `source .venv/bin/activate` from the worktree; see
  `CLAUDE.md` worktree test-setup notes (PYTHONPATH gotchas).

---

## Acceptance Criteria

- [ ] Three shared fixtures available package-wide; local duplicates removed
- [ ] Three integration tests pass against the real component stack
- [ ] `pytest packages/parrot-formdesigner/tests/ -v` fully green
- [ ] `pytest packages/ai-parrot/tests/ -v` fully green
- [ ] `ruff check` clean on both packages' test trees
- [ ] Spec §5 criteria → test mapping documented in the completion note

---

## Test Specification

```python
# packages/parrot-formdesigner/tests/integration/test_field_uid_flows.py
async def test_edit_flow_rename_stability(client, tmp_blob_backend):
    """create form → upload to field → rename field_id → blob reachable,
    rules evaluate, partial save answers survive under the new field_id."""

async def test_llm_create_edit_roundtrip(mocked_llm_client, storage): ...

async def test_migration_end_to_end(pg_or_stub, legacy_schema_json): ...
```

---

## Agent Instructions

1. **Read the spec** §4/§5; verify ALL prior tasks are in `sdd/tasks/completed/`.
2. **Verify the contract**: locate the existing mocked-LLM, redis-stub, and blob-temp fixtures before writing new ones.
3. **Update status** in `sdd/tasks/index/formdesigner-field-uid.json` → `"in-progress"`.
4. **Implement**, run both suites, verify acceptance criteria.
5. **Move this file** to `sdd/tasks/completed/`, update index → `"done"`, fill Completion Note (with the coverage mapping).

---

## Completion Note

*(Agent fills this in when done)*

**Completed by**:
**Date**:
**Notes**:

**Deviations from spec**: none
