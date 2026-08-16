# TASK-2206: Migrate the package test suite to tenant-qualified URLs

**Feature**: FEAT-421 — Client-declared tenant in the forms URL
**Spec**: `sdd/specs/forms-tenant-in-url.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: L (4-8h)
**Depends-on**: TASK-2202, TASK-2203, TASK-2204
**Assigned-to**: unassigned

---

## Context

The suite goes red the moment TASK-2201 lands (every existing test still calls
`/api/v1/forms/...`) and stays red until this task. That is by design — the spec
sequences the cut so exactly one task owns restoring green, rather than smearing
URL edits across seven implementation tasks.

**26** test files under `packages/parrot-formdesigner/tests/` reference form URL
paths; **17** match `api/v1/forms` specifically.

---

## Scope

- Update every test that builds a forms URL to the tenant-qualified shape
  (`/api/v1/t/{tenant}/forms/...`, `/api/v1/t/{tenant}/fields`).
- Update fixtures that build authenticated requests so the session's `programs`
  contains the tenant the test declares — otherwise every test now 403s.
- Add a shared fixture/helper for "an authorized request under tenant X" rather
  than repeating session scaffolding in 26 files.
- Restore the full package suite to green.

**NOT in scope**:
- **`/org/*` tests.** They must NOT change. An `/org/*` test diff is a signal
  that spec G7 was violated somewhere upstream — stop and investigate rather
  than editing the test to pass (spec AC11).
- Adding the new feature tests — TASK-2198 through TASK-2205 each ship their own.
- Any source change. If a test cannot pass without touching `src/`, that is a
  defect in an earlier task; report it rather than patching around it here.

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/parrot-formdesigner/tests/**` (26 files) | MODIFY | Tenant-qualified URLs + session fixtures |
| `packages/parrot-formdesigner/tests/conftest.py` | MODIFY | Shared authorized-request fixture |

Known files referencing `api/v1/forms` (17):

```
tests/integration/test_render_pdf.py        tests/integration/test_render_xml.py
tests/unit/api/test_setup_form_api.py       tests/test_tenant_context_resolution.py
tests/integration/test_clone_rest.py        tests/integration/test_field_uid_flows.py
tests/integration/test_upload_rest.py       tests/integration/test_registry_multi_tenancy_e2e.py
tests/unit/api/test_render_dispatcher.py    tests/unit/api/test_setup_form_api_rest.py
tests/unit/renderers/test_html5_lifecycle.py tests/unit/ui/test_setup_form_ui_routes.py
tests/unit/services/test_blob_uid_keys.py   tests/unit/services/test_public_forms.py
tests/integration/test_operations_e2e.py    tests/formdesigner/test_audio_integration.py
tests/formdesigner/test_audio_models.py
```

Re-run the survey before starting — earlier tasks may have added or renamed files:

```bash
grep -rl "/forms/" packages/parrot-formdesigner/tests/   # broad: 26 as of 045a555fc
grep -rl "api/v1/forms" packages/parrot-formdesigner/tests/   # narrow: 17
```

---

## Codebase Contract (Anti-Hallucination)

### The URL transformation

```
OLD                                          NEW
{bp}/forms                                -> {bp}/t/{tenant}/forms
{bp}/forms/{form_uid}                     -> {bp}/t/{tenant}/forms/{form_uid}
{bp}/forms/{form_uid}/schema              -> {bp}/t/{tenant}/forms/{form_uid}/schema
{bp}/forms/{form_uid}/render/{format}     -> {bp}/t/{tenant}/forms/{form_uid}/render/{format}
{bp}/forms/blank                          -> {bp}/t/{tenant}/forms/blank
{bp}/fields                               -> {bp}/t/{tenant}/fields

{bp}/org/...                              -> UNCHANGED  (spec G7 / AC11)
```

### The session shape tests must build

```python
# The read that authorization performs (api/handlers.py:235-254):
session.get("session", {}).get("programs", [])   # list[str] of tenant slugs
session.get("session", {}).get("superuser", False)
```

So a request declaring `/t/flexroc/...` needs `programs` containing
`"flexroc"`, or `superuser=True`.

### `test_tenant_context_resolution.py` — delete, do not migrate

```
packages/parrot-formdesigner/tests/test_tenant_context_resolution.py
```

This file (added by PR #1146) tests resolution step 0,
`request["tenant_context"]`, which no longer exists. Its four cases are
superseded by TASK-2199's decorator matrix. Delete it rather than rewriting it.

### Does NOT Exist

- ~~`request["tenant_context"]`~~ — removed. Any test setting it is testing a
  deleted contract.
- ~~a default tenant for tests~~ — `registry.default_tenant` is unreachable
  from a forms request now. Tests that relied on the implicit `"navigator"`
  fallback must declare a tenant explicitly.
- ~~`programs[0]` determining the tenant~~ — a test with
  `programs=["navigator", "flexroc"]` hitting `/t/flexroc/` must now resolve
  `flexroc`. Tests asserting `navigator` there were asserting the bug.

---

## Implementation Notes

### Key Constraints

- Work file by file, running that file's tests after each edit. A bulk
  find-and-replace across 26 files will silently rewrite `/org/*` URLs and
  break G7 — the paths overlap textually (`/forms/` appears inside some org
  fixtures' payloads).
- When a test previously passed with no session at all, decide deliberately:
  is it a **public** form path (still works, no session needed) or an
  authenticated one (now needs `programs`)? Do not blanket-add sessions.
- If a test asserted the old fallback behaviour, its assertion was encoding the
  bug. Rewrite the assertion to the new contract; note it in the Completion Note.
- `tests/unit/services/test_public_forms.py` was already updated by TASK-2201.
  Verify rather than re-edit.

### References in Codebase

- `sdd/specs/forms-tenant-in-url.spec.md` §4 — the full test matrix.
- TASK-2199's decorator tests — the fixture pattern to reuse.

---

## Acceptance Criteria

- [ ] Full package suite green: `pytest packages/parrot-formdesigner/tests/ -v` (spec AC13)
- [ ] `git diff --name-only` shows **no** `/org/*` test file modified (spec AC11)
- [ ] `grep -rn "tenant_context" packages/parrot-formdesigner/tests/` returns nothing
- [ ] `test_tenant_context_resolution.py` is deleted
- [ ] `grep -rn "api/v1/forms/" packages/parrot-formdesigner/tests/` returns no unqualified path
- [ ] No source file under `src/` was modified by this task
- [ ] No linting errors: `ruff check packages/parrot-formdesigner/tests/`

---

## Test Specification

This task makes existing tests pass rather than adding new behaviour. The one
new guard to add:

```python
# packages/parrot-formdesigner/tests/unit/api/test_no_legacy_urls.py
from pathlib import Path
import re

LEGACY = re.compile(r"/api/v1/forms/")


def test_no_test_uses_a_legacy_forms_url():
    """FEAT-421 hard cut: every forms URL must be tenant-qualified."""
    offenders = [
        str(p) for p in Path("packages/parrot-formdesigner/tests").rglob("*.py")
        if LEGACY.search(p.read_text())
    ]
    assert offenders == [], f"legacy forms URLs still in: {offenders}"
```

---

## Agent Instructions

1. **Read the spec** at `sdd/specs/forms-tenant-in-url.spec.md` (§4 Test Specification)
2. **Check dependencies** — TASK-2202, TASK-2203, TASK-2204 must be in `sdd/tasks/completed/`
3. **Re-run the file survey** — the 26/17 counts are from commit `045a555fc`
4. **Update status** in `sdd/tasks/index/forms-tenant-in-url.json` → `"in-progress"`
5. **Implement** file by file, never with a bulk replace
6. **Verify** all acceptance criteria are met
7. **Move this file** to `sdd/tasks/completed/TASK-2206-test-suite-url-migration.md`
8. **Update index** → `"done"`
9. **Fill in the Completion Note** below — list every test whose ASSERTION changed (not just its URL), since those encode behaviour decisions

---

## Completion Note

*(Agent fills this in when done)*

**Completed by**:
**Date**:
**Notes**:

**Deviations from spec**: none | describe if any
