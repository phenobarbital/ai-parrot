# TASK-2207: Version bump to 0.9.0 and migration guide

**Feature**: FEAT-421 — Client-declared tenant in the forms URL
**Spec**: `sdd/specs/forms-tenant-in-url.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: S (< 2h)
**Depends-on**: TASK-2201, TASK-2204
**Assigned-to**: unassigned

---

## Context

Implements spec Module 10. The hard cut means `navigator-svelte`, `fieldsync`
and the wheel must ship together — this document is what makes that deploy
schedulable rather than a surprise. It is a deliverable, not paperwork: without
the full old→new URL table, each consuming team reverse-engineers the mapping
from a 404.

---

## Scope

- Bump `parrot-formdesigner` from `0.8.21` to `0.9.0` (breaking change).
- Write `docs/migration/feat-421-forms-tenant-in-url.md` containing:
  - Why the change exists (one paragraph, pointing at NAV-9372 / NAV-9370).
  - The **complete** old→new URL table for every forms route.
  - An explicit "**`/org/*` URLs do not change**" section — consumers will
    assume otherwise, since the two namespaces sit under the same `base_path`.
  - The new error contract (`tenant_not_declared` 400, `tenant_forbidden` 403,
    `tenant_conflict` 400, cross-tenant 404) with the JSON body shape.
  - The POST-body rule: URL authoritative; a body `tenant` must match or 400.
  - A coordinated-deploy checklist.
- Cross-check the table against the router as built, not against this spec —
  the code is the source of truth by now.

**NOT in scope**: publishing to PyPI; editing `fieldsync` or `navigator-svelte`.

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/parrot-formdesigner/src/parrot_formdesigner/version.py` | MODIFY | `0.8.21` → `0.9.0` |
| `docs/migration/feat-421-forms-tenant-in-url.md` | CREATE | Migration guide |

---

## Codebase Contract (Anti-Hallucination)

### Verified

```python
# packages/parrot-formdesigner/src/parrot_formdesigner/version.py:5
__version__ = "0.8.21"

# packages/parrot-formdesigner/pyproject.toml:69
version = {attr = "parrot_formdesigner.version.__version__"}
# ^ the version is read dynamically from version.py — edit version.py ONLY,
#   do NOT add a literal `version = "0.9.0"` to pyproject.toml.
```

### The route inventory to document (from `api/routes.py:207-360`)

Forms routes needing the `/t/{tenant}` prefix — CRUD (`GET/POST /forms`,
`from-db`, `blank`, `GET/PUT/PATCH/DELETE /forms/{form_uid}`), `edit`, `clone`,
`schema`, `style`, `render/{format}`, `validate`, `data`, `form-controls`,
`operations`, `fields/{field_uid}/upload`, `partial` (POST/GET/DELETE),
`events/{event_name}`, `audio/ws`, `publish`, `GET/POST /fields`, `versions`,
`versions/{version}`, `import-report` — plus the UI routes in `ui/routes.py:91-118`
(`/`, `/gallery`, `/forms/{form_uid}`, `/forms/{form_uid}/schema`,
`/forms/{form_uid}/telegram`, `/api/v1/forms/{form_uid}/telegram-submit`).

Unchanged `/org/*` routes: `graph`, `projects`,
`cost-centers/{project_id}/workday-map`, `users/{user_id}/assign`,
`sync/workday`, `stores/{store_id}/sites`, `sites/{site_id}/locations`,
`locations/{location_id}`.

> Generate the table from the live router rather than transcribing this list —
> it is a checklist for completeness, not the source of truth.

### Does NOT Exist

- ~~a CHANGELOG.md in `packages/parrot-formdesigner/`~~ — verify before
  assuming one exists to append to.
- ~~a deprecation window~~ — the spec mandates a hard cut. Do not document a
  fallback period; there isn't one.
- ~~`version` as a literal in `pyproject.toml`~~ — it is `{attr = ...}`.

---

## Implementation Notes

### Key Constraints

- `0.9.0`, not `1.0.0` — the package is pre-1.0, so a minor bump is the
  breaking-change signal for this project's versioning.
- The `/org/*` section must be prominent, not a footnote. The single most likely
  consumer error is prefixing `/org/*` too, which produces a 404 that looks like
  the migration failed.
- Include a copy-pasteable example request/response for each error case;
  frontend teams branch on `error` slugs, not prose.

### References in Codebase

- `docs/migration/feat-201-ai-parrot-embeddings.md` — the house style for
  migration guides in this repo. Follow its structure.
- `sdd/specs/forms-tenant-in-url.spec.md` §2, §5 — the contract to document.

---

## Acceptance Criteria

- [ ] `parrot_formdesigner.version.__version__ == "0.9.0"`
- [ ] `pyproject.toml` still reads the version dynamically (no literal added)
- [ ] `docs/migration/feat-421-forms-tenant-in-url.md` exists
- [ ] The guide's URL table covers every forms route registered by `setup_form_api` and `setup_form_ui` — verified against the live router, not transcribed
- [ ] The guide states explicitly that `/org/*` URLs are unchanged, in its own section
- [ ] The guide documents all four error cases with JSON bodies
- [ ] The guide documents the URL-authoritative POST-body rule
- [ ] Spec AC12 satisfied

---

## Test Specification

```python
# packages/parrot-formdesigner/tests/unit/test_version_and_docs.py
from pathlib import Path
import parrot_formdesigner.version as v

GUIDE = Path("docs/migration/feat-421-forms-tenant-in-url.md")


def test_version_bumped():
    assert v.__version__ == "0.9.0"


def test_migration_guide_exists():
    assert GUIDE.is_file()


def test_guide_documents_org_exemption():
    text = GUIDE.read_text()
    assert "/org/" in text
    assert "unchanged" in text.lower()


def test_guide_documents_error_slugs():
    text = GUIDE.read_text()
    for slug in ("tenant_not_declared", "tenant_forbidden", "tenant_conflict"):
        assert slug in text
```

---

## Agent Instructions

1. **Read the spec** at `sdd/specs/forms-tenant-in-url.spec.md` (Module 10, AC12)
2. **Check dependencies** — TASK-2201 and TASK-2204 must be in `sdd/tasks/completed/`
3. **Enumerate the live router** to build the URL table — do not transcribe from the spec
4. **Update status** in `sdd/tasks/index/forms-tenant-in-url.json` → `"in-progress"`
5. **Implement** following the scope and notes above
6. **Verify** all acceptance criteria are met
7. **Move this file** to `sdd/tasks/completed/TASK-2207-version-bump-migration-guide.md`
8. **Update index** → `"done"`
9. **Fill in the Completion Note** below

---

## Completion Note

**Completed by**: sdd-worker (Claude)
**Date**: 2026-08-16
**Notes**: Bumped `__version__` to `0.9.0` in `version.py` only —
`pyproject.toml` still reads it dynamically via `{attr = ...}` (unchanged,
verified no literal `version =` line exists). Wrote
`docs/migration/feat-421-forms-tenant-in-url.md` following the
`feat-201-ai-parrot-embeddings.md` house style. The URL tables were
generated by **instantiating the live router** (`setup_form_api` +
`setup_form_ui`, plus a second run with `synthesizer`/`transcriber`/
`token_validator` mocks to surface the audio WS route) and enumerating
`app.router.routes()` — not transcribed from the spec, per the task's own
explicit instruction. Documents all four error cases (`tenant_not_declared`
400, `tenant_forbidden` 403, `tenant_conflict` 400, cross-tenant 404) with
JSON bodies, the URL-authoritative POST-body rule with a worked
match/absent/conflict example, a dedicated prominent `/org/*` UNCHANGED
section (not a footnote, per the task's own emphasis), the audio WS
close-code-1008 contract, and a coordinated-deploy checklist.

Created `tests/unit/test_version_and_docs.py` matching the task's own
embedded Test Specification verbatim, even though — unlike every other
task in this feature — the "Files to Create/Modify" table omitted it. This
is the one instance across all 10 tasks where the table and the Test
Specification section disagreed; I inferred inclusion was intended (the
Test Specification is a complete, ready-to-use file, and every other task
in this feature lists its test file in the table) rather than skip
testing entirely. All 4 tests pass.

Full suite re-verified after this task: 39 failures (38 true pre-existing
baseline + the 1 `test_ui_imports.py` item flagged in TASK-2204/2206,
unchanged), 1919 passed (+4 from this task's new tests), zero new
regressions.

**Deviations from spec**: none in intent — see the Files-table/Test-Spec
discrepancy noted above (resolved by inference, not a scope change).
