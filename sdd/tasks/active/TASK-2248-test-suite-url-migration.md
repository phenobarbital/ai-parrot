# TASK-2248: Migrate test suite URL patterns from `/t/{tenant}/` to `/{tenant}/`

**Feature**: FEAT-429 — Remove `/t/` marker from tenant-qualified URLs
**Spec**: `sdd/specs/fieldsync-tenant-url.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: M (2-4h)
**Depends-on**: TASK-2246, TASK-2247
**Assigned-to**: unassigned

---

## Context

TASK-2246 changed the route table and TASK-2247 changed all source URL
references. This task updates the **163 test references** across 23 test
files so assertions match the new URL shape. Without this, tests that check
route paths or make requests to specific URLs will fail.

Implements spec Module 3.

---

## Scope

Update every `/t/{tenant}/` URL pattern in test files under
`packages/parrot-formdesigner/tests/`. This includes:

- Route path assertions (e.g., `assert "/api/v1/t/{tenant}/forms" in paths`)
- Test request URLs (e.g., `client.get("/api/v1/t/flexroc/forms")`)
- Route registrations in test helpers
- Docstrings and comments

### Files to update (23 files, 163 references total — measured `grep -ro "/t/" tests/ | wc -l`, spec v0.2; the key files below are the largest, the grep is authoritative)

**Unit tests**:
- `unit/api/test_setup_form_api.py` — route path assertions
- `unit/api/test_setup_form_api_rest.py` — REST route assertions
- `unit/api/test_route_tenant_coverage.py` — coverage introspection
- `unit/api/test_tenant_errors.py` — error `expected` field assertions
- `unit/ui/test_setup_form_ui_routes.py` — UI route path assertions
- `unit/ui/test_setup_form_ui_protect_pages.py` — handler lookup by path
- `unit/services/test_public_forms.py` — glob assertions

**Integration tests**:
- `integration/test_registry_multi_tenancy_e2e.py` — route registration
- `integration/test_render_xml.py` — render route
- `integration/test_render_pdf.py` — render route
- `integration/test_operations_e2e.py` — operations route
- `integration/test_clone_rest.py` — clone route
- `integration/test_upload_rest.py` — upload route
- `integration/test_field_uid_flows.py` — operations + upload routes

**NOT in scope**:
- Source code changes (TASK-2246, TASK-2247).
- Migration guide (TASK-2249).
- Writing NEW tests — only updating existing URL strings.

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `tests/unit/api/test_setup_form_api.py` | MODIFY | Route path assertions |
| `tests/unit/api/test_setup_form_api_rest.py` | MODIFY | REST route path assertions |
| `tests/unit/api/test_route_tenant_coverage.py` | MODIFY | Coverage assertions |
| `tests/unit/api/test_tenant_errors.py` | MODIFY | Error expected-field assertions |
| `tests/unit/ui/test_setup_form_ui_routes.py` | MODIFY | UI route assertions |
| `tests/unit/ui/test_setup_form_ui_protect_pages.py` | MODIFY | Handler lookup path |
| `tests/unit/services/test_public_forms.py` | MODIFY | Glob assertions |
| `tests/integration/test_registry_multi_tenancy_e2e.py` | MODIFY | Route registration |
| `tests/integration/test_render_xml.py` | MODIFY | Render route |
| `tests/integration/test_render_pdf.py` | MODIFY | Render route |
| `tests/integration/test_operations_e2e.py` | MODIFY | Operations route |
| `tests/integration/test_clone_rest.py` | MODIFY | Clone route + docstring |
| `tests/integration/test_upload_rest.py` | MODIFY | Upload route |
| `tests/integration/test_field_uid_flows.py` | MODIFY | Operations + upload routes |

All paths under `packages/parrot-formdesigner/tests/`.

---

## Codebase Contract (Anti-Hallucination)

### Verified Imports

No new imports needed — this task only changes URL string values in tests.

### Existing Signatures to Use

```python
# test_route_tenant_coverage.py:75 — this assertion STAYS CORRECT:
assert not any("/t/" in p for p in paths)
# ^ This tests that /org/* routes do NOT have the tenant prefix.
# After FEAT-429, /org/* still has no /t/ (and no /{tenant}/), so the
# assertion is correct as-is. DO NOT change this line.
# BUT the FORMS assertions below it (lines 90-91+) DO change:
"/api/v1/t/{tenant}/forms"      → "/api/v1/{tenant}/forms"
"/api/v1/t/{tenant}/forms/from-db" → "/api/v1/{tenant}/forms/from-db"
# etc.

# test_setup_form_api.py — typical assertion pattern:
assert "/api/v1/t/{tenant}/forms" in paths
# CHANGE TO: assert "/api/v1/{tenant}/forms" in paths

# test_setup_form_ui_routes.py — typical assertion pattern:
assert "/t/{tenant}/" in paths
# CHANGE TO: assert "/{tenant}/" in paths

# test_setup_form_ui_protect_pages.py — handler lookup by route path:
handler = _find_handler(app, "/t/{tenant}/")
# CHANGE TO: handler = _find_handler(app, "/{tenant}/")

# test_tenant_errors.py — error expected field:
exc = TenantNotDeclaredError(expected="/api/v1/t/{tenant}/forms")
assert body["expected"] == "/api/v1/t/{tenant}/forms"
# CHANGE both to: "/api/v1/{tenant}/forms"

# Integration tests — route registration in test setup:
"/api/v1/t/{tenant}/forms/{form_uid}/render/{format}", handle_render
# CHANGE TO: "/api/v1/{tenant}/forms/{form_uid}/render/{format}", handle_render
```

### Does NOT Exist

- ~~`conftest.py` tenant URL fixture~~ — does not exist; test URLs are
  inline strings in each test file.
- ~~`test_utils.TENANT_PREFIX`~~ — no such constant.

---

## Implementation Notes

### Pattern to Follow

Mechanical find-and-replace within each test file:

```
/t/{tenant}  →  /{tenant}
/t/{{tenant}}  →  /{{tenant}}
"/t/"  →  "/"  (only in URL path context)
```

### Key Constraints

- **CRITICAL — `test_route_tenant_coverage.py:75`**: the assertion
  `assert not any("/t/" in p for p in paths)` checks that `/org/*` routes
  do NOT carry the tenant prefix. This line is STILL CORRECT after
  FEAT-429 — do NOT change it. It verifies G5 (org routes unchanged).
- **Do NOT change any `/org/*` test assertions** — they must stay
  byte-identical. If a test file exercises both forms and org routes, only
  the forms URL strings change.
- Run the full test suite after all updates to verify:
  ```bash
  pytest packages/parrot-formdesigner/tests/ -v --tb=short
  ```

### Verification Command

```bash
grep -rn '/t/{tenant}\|/t/{{tenant}}' packages/parrot-formdesigner/tests/ \
  --include='*.py' | grep -v '__pycache__'
```

Expected: **zero lines** after this task.

---

## Acceptance Criteria

- [ ] All 163 test URL references updated from `/t/{tenant}/` to `/{tenant}/`.
- [ ] `test_route_tenant_coverage.py:75` (`assert not any("/t/" in p ...)`)
      is **unchanged**.
- [ ] No `/org/*` test assertions were modified.
- [ ] Verification grep returns zero lines.
- [ ] Full test suite passes:
      `pytest packages/parrot-formdesigner/tests/ -v --tb=short`
- [ ] `ruff check packages/parrot-formdesigner/tests/` clean.

---

## Test Specification

This task IS the test update. The acceptance criterion is that the full
existing suite passes green against the updated source from TASK-2246 and
TASK-2247.

---

## Agent Instructions

When you pick up this task:

1. **Read the spec** at `sdd/specs/fieldsync-tenant-url.spec.md`
2. **Run the discovery grep** first to get the current list of sites:
   ```bash
   grep -rn '/t/{tenant}\|/t/{{tenant}}' packages/parrot-formdesigner/tests/ \
     --include='*.py' | grep -v '__pycache__'
   ```
3. **Edit each file**, replacing `/t/{tenant}` → `/{tenant}` (and variants)
4. **Leave `test_route_tenant_coverage.py:75` UNCHANGED**
5. **Run** the full test suite
6. **Run** the verification grep to confirm zero remaining references
7. **Commit** with message: `test(formdesigner): migrate test URLs for FEAT-429 (TASK-2248)`

---

## Completion Note

*(Agent fills this in when done)*

**Completed by**: *(session or agent ID)*
**Date**: YYYY-MM-DD
**Notes**: *(What was implemented, any deviations from scope, issues encountered.)*

**Deviations from spec**: none | describe if any
