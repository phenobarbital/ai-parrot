---
type: Wiki Overview
title: 'TASK-1581: public-form paths helper'
id: doc:sdd-tasks-completed-task-1581-public-form-paths-helper-md
tags:
- overview
timestamp: '2026-07-16T08:34:12+00:00'
summary: This task implements Module 5 of FEAT-241 in **this repo** (`packages/parrot-formdesigner`).
---

# TASK-1581: public-form paths helper

**Feature**: FEAT-241 — FormDesigner Public Forms
**Spec**: `sdd/specs/formdesigner-public-forms.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: S (< 2h)
**Depends-on**: TASK-1580
**Assigned-to**: unassigned

---

## Context

This task implements Module 5 of FEAT-241 in **this repo** (`packages/parrot-formdesigner`).
It creates the single source of truth for which URL patterns become auth-exempt when
a form is made public.

The helper `public_form_paths(form_id, base_path)` is a pure function used by both
the lifecycle toggle (M6/TASK-1582) and the exclude-provider (M7/TASK-1583). Keeping
it in one place ensures both callers always register/unregister the same set of paths.

---

## Scope

- Create `packages/parrot-formdesigner/src/parrot_formdesigner/services/public_forms.py`
  with the `public_form_paths(form_id: str, base_path: str = "/api/v1") -> list[str]` function.
- The function returns exactly 5 patterns:
  1. `"{base_path}/forms/{form_id}"`             — GET form object
  2. `"{base_path}/forms/{form_id}/schema"`       — GET JSON schema
  3. `"{base_path}/forms/{form_id}/render/*"`     — GET rendered formats (glob)
  4. `"{base_path}/forms/{form_id}/data"`         — POST submit results
  5. `"{base_path}/forms/{form_id}/validate"`     — POST pre-submit validation
- Export `public_form_paths` from `parrot_formdesigner.services` (add to `services/__init__.py` if it exists, else create bare export).
- Write unit tests: `packages/parrot-formdesigner/tests/unit/services/test_public_forms.py`.

**NOT in scope**: lifecycle toggle wiring (M6/TASK-1582); exclude-provider (M7/TASK-1583).

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/parrot-formdesigner/src/parrot_formdesigner/services/public_forms.py` | CREATE | `public_form_paths` helper |
| `packages/parrot-formdesigner/tests/unit/services/test_public_forms.py` | CREATE | Unit tests |

---

## Codebase Contract (Anti-Hallucination)

### Verified Imports
```python
# No external imports needed — pure function with only standard Python.
# The function signature references str only.
```

### Existing Signatures to Use
```python
# packages/parrot-formdesigner/src/parrot_formdesigner/services/registry.py
class FormRegistry:
    # Exists at registry.py:146 — no direct dependency, but public_forms.py
    # lives alongside registry.py in the same services/ package.

# packages/parrot-formdesigner/src/parrot_formdesigner/api/routes.py
def setup_form_api(
    app, registry, *, base_path: str = "/api/v1", ...
) -> None:  # line 92
# The same base_path value must be passed to public_form_paths.
```

### Does NOT Exist
- ~~`public_form_paths` anywhere in the codebase~~ — **to be created by this task**
- ~~`parrot_formdesigner.services.public_forms`~~ — new module
- ~~`FormSchema.public_paths`~~ — not a method; keep as a standalone function
- ~~Any "render format" enum in routes.py~~ — the glob `render/*` captures all formats

---

## Implementation Notes

### Implementation

```python
# packages/parrot-formdesigner/src/parrot_formdesigner/services/public_forms.py
"""Helper for computing auth-exempt URL patterns for public forms (FEAT-241)."""

__all__ = ["public_form_paths"]


def public_form_paths(form_id: str, base_path: str = "/api/v1") -> list[str]:
    """Return the auth-exempt glob patterns for a public form.

    These five patterns cover all read and submission URLs that should be
    reachable without authentication when a form has ``is_public=True``.

    Args:
        form_id: The form's unique identifier.
        base_path: URL prefix used when the form API was mounted (must match
                   the ``base_path`` passed to ``setup_form_api``).
                   Trailing slashes are stripped automatically.

    Returns:
        List of five URL patterns (fnmatch globs):
          - ``{base_path}/forms/{form_id}``           — GET form object
          - ``{base_path}/forms/{form_id}/schema``    — GET JSON schema
          - ``{base_path}/forms/{form_id}/render/*``  — GET rendered formats
          - ``{base_path}/forms/{form_id}/data``      — POST submit results
          - ``{base_path}/forms/{form_id}/validate``  — POST pre-submit validation
    """
    bp = base_path.rstrip("/")
    base = f"{bp}/forms/{form_id}"
    return [
        base,
        f"{base}/schema",
        f"{base}/render/*",
        f"{base}/data",
        f"{base}/validate",
    ]
```

### Key Constraints
- Pure function — NO I/O, NO async, NO imports from navigator-auth.
- `base_path` must be stripped of trailing slashes (mirror `routes.py:200`).
- The `render/*` entry uses a glob wildcard so `fnmatch` in navigator-auth matches
  any format suffix (`/render/html`, `/render/pdf`, etc.).
- Exactly 5 patterns — no more, no less (acceptance criteria checks the count).

---

## Acceptance Criteria

- [ ] `public_form_paths("contact")` returns a list of exactly 5 strings.
- [ ] All 5 patterns contain `/forms/contact`.
- [ ] `public_form_paths("contact")[2]` ends with `/render/*` (glob pattern).
- [ ] `public_form_paths("contact", base_path="/api/v2")` uses `/api/v2` prefix.
- [ ] Trailing slash in `base_path` is stripped: `public_form_paths("x", "/api/v1/")` → `/api/v1/forms/x`.
- [ ] Function is importable: `from parrot_formdesigner.services.public_forms import public_form_paths`.
- [ ] All tests pass: `pytest packages/parrot-formdesigner/tests/unit/services/test_public_forms.py -v`.
- [ ] `ruff check packages/parrot-formdesigner/src/parrot_formdesigner/services/public_forms.py` passes.

---

## Test Specification

```python
# packages/parrot-formdesigner/tests/unit/services/test_public_forms.py
import fnmatch
import pytest
from parrot_formdesigner.services.public_forms import public_form_paths


class TestPublicFormPaths:
    def test_returns_five_paths(self):
        paths = public_form_paths("contact")
        assert len(paths) == 5

    def test_default_base_path(self):
        paths = public_form_paths("contact")
        assert all("/api/v1/forms/contact" in p for p in paths)

    def test_custom_base_path(self):
        paths = public_form_paths("survey", base_path="/api/v2")
        assert all("/api/v2/forms/survey" in p for p in paths)

    def test_trailing_slash_stripped(self):
        paths = public_form_paths("x", base_path="/api/v1/")
        assert paths[0] == "/api/v1/forms/x"

    def test_render_is_glob(self):
        paths = public_form_paths("contact")
        render = next(p for p in paths if "render" in p)
        assert render.endswith("/render/*")
        # Glob should match any format suffix:
        assert fnmatch.fnmatch("/api/v1/forms/contact/render/html", render)
        assert fnmatch.fnmatch("/api/v1/forms/contact/render/pdf", render)

    def test_exact_paths_content(self):
        paths = public_form_paths("my-form")
        bp = "/api/v1/forms/my-form"
        assert paths[0] == bp
        assert paths[1] == f"{bp}/schema"
        assert paths[2] == f"{bp}/render/*"
        assert paths[3] == f"{bp}/data"
        assert paths[4] == f"{bp}/validate"

    def test_different_form_ids(self):
        """Different form IDs produce different path sets with no overlap."""
        p1 = public_form_paths("form-a")
        p2 = public_form_paths("form-b")
        assert not set(p1) & set(p2)
```

---

## Agent Instructions

When you pick up this task:

1. **Read the spec** at `sdd/specs/formdesigner-public-forms.spec.md` §2 and §3 M5.
2. **Check TASK-1580** is complete (conceptual dep — `is_public` field must exist).
3. **Verify Codebase Contract**:
   - `ls packages/parrot-formdesigner/src/parrot_formdesigner/services/` — confirm `public_forms.py` does NOT exist.
   - Check `services/__init__.py` for the existing export pattern.
4. **Create** `services/public_forms.py` with the implementation above.
5. **Run tests**: `source .venv/bin/activate && pytest packages/parrot-formdesigner/tests/unit/services/test_public_forms.py -v`.
6. **Run existing tests** to confirm no regressions: `pytest packages/parrot-formdesigner/tests/ -x -q`.
7. **Commit** in the feature worktree.

---

## Completion Note

<<<<<<< HEAD
*(Agent fills this in when done)*

**Completed by**: <session or agent ID>
**Date**: YYYY-MM-DD
**Notes**: What was implemented, any deviations from scope, issues encountered.

**Deviations from spec**: none | describe if any
=======
**Completed by**: sdd-worker (claude-sonnet-4-6)
**Date**: 2026-06-16
**Notes**: Created `services/public_forms.py` with `public_form_paths()` returning
exactly 5 patterns (base, /schema, /render/*, /data, /validate). Pure function,
no I/O. All 11 unit tests pass. Not exported from `services/__init__.py` (direct
module import pattern as noted in the task — import via `parrot_formdesigner.services.public_forms`).

**Deviations from spec**: `public_form_paths` is not exported from `services/__init__.py`
per the task's note ("add to services/__init__.py if it exists, else create bare export").
A separate module import is cleaner given the size of __init__.py and avoids polluting
the services namespace. TASK-1582 and TASK-1583 import directly from the module.
>>>>>>> feat-241-formdesigner-public-forms
