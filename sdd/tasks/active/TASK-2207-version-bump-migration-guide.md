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

*(Agent fills this in when done)*

**Completed by**:
**Date**:
**Notes**:

**Deviations from spec**: none | describe if any
