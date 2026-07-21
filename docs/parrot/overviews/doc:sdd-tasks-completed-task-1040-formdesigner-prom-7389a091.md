---
type: Wiki Overview
title: 'TASK-1040: Promote `navigator-auth`, `lxml`, `reportlab` to hard deps + bump
  to 0.2.0'
id: doc:sdd-tasks-completed-task-1040-formdesigner-promote-hard-deps-md
tags:
- overview
timestamp: '2026-07-16T08:34:12+00:00'
summary: Wave 1, Step 3 of FEAT-152 promotes three previously-optional /
---

# TASK-1040: Promote `navigator-auth`, `lxml`, `reportlab` to hard deps + bump to 0.2.0

**Feature**: FEAT-152 — parrot-formdesigner Structural Refactor
**Spec**: `sdd/specs/formdesigner-refactor.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: S (< 2h)
**Depends-on**: none
**Assigned-to**: unassigned

---

## Context

Wave 1, Step 3 of FEAT-152 promotes three previously-optional /
transitive dependencies to required `[project.dependencies]` entries in
`packages/parrot-formdesigner/pyproject.toml`. This task is the first
step in the worktree because (a) it's mechanical, (b) it surfaces any
constraint conflicts before the rest of Wave 1 starts touching code,
and (c) every later Wave 1 task assumes these deps are hard.

Spec sections: §1 Goals (auth becomes hard dep; render dispatcher needs
`lxml` + `reportlab`); §3 Module 5; §7 External Dependencies.

---

## Scope

- Promote `navigator-auth`, `lxml>=6.1.0`, `reportlab>=4.1.0` from
  optional / transitive to **required** `[project.dependencies]` in
  `packages/parrot-formdesigner/pyproject.toml`.
- Bump `version` to `0.2.0` (the breaking layout change ships under
  this minor).
- Remove any `[project.optional-dependencies]` block entries that are
  now redundant (e.g. an "auth" extra that only listed
  `navigator-auth`).

**NOT in scope:**
- Removing the `try/except ImportError` block in
  `handlers/routes.py` — that goes with TASK-1042 (which deletes the
  block as it migrates the handler to `api/routes.py`).
- Adding `pypdf` — it is test-only; goes in `[project.optional-dependencies].test`
  or the package's existing test extras (whichever is the convention here).
- Touching `__init__.py` or any `.py` source file.

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/parrot-formdesigner/pyproject.toml` | MODIFY | Promote deps + version bump |

---

## Codebase Contract (Anti-Hallucination)

### Verified Files

- `packages/parrot-formdesigner/pyproject.toml` — current build config.
  `version = {attr = "parrot_formdesigner.version.__version__"}` (verified
  2026-05-07).
- `packages/parrot-formdesigner/src/parrot_formdesigner/version.py:5` —
  `__version__ = "0.1.28"`. Bump to `"0.2.0"`.

### Already Installed (verified in venv 2026-05-07)

```text
lxml       6.1.0
reportlab  4.1.0
navigator-auth (already used at handlers/routes.py:32 conditionally)
```

### Does NOT Exist

- ~~A separate `parrot-formdesigner` PyPI extras called `xforms` or `pdf`~~
  — there are no per-feature extras today; the deps go in the main
  `[project.dependencies]`.

---

## Implementation Notes

1. The `version = {attr = "parrot_formdesigner.version.__version__"}`
   reference means you bump the version by editing
   `src/parrot_formdesigner/version.py:5`, not `pyproject.toml`.
2. Pin floors only (`>=`), not exacts. Match the venv-confirmed floor
   for `lxml` (6.1.0) and `reportlab` (4.1.0). For `navigator-auth`,
   use the same floor that the rest of `ai-parrot` uses; check
   `pyproject.toml` at the monorepo root for the existing pin if
   `navigator-auth` is already listed as a transitive dep there.
3. Run `uv pip install -e packages/parrot-formdesigner` (with `.venv`
   activated) to verify the modified `pyproject.toml` resolves.

### Pattern to Follow

Look at how other `parrot-*` sub-packages structure
`[project.dependencies]` if there's an existing pattern in the
repo (e.g. `packages/parrot-*/pyproject.toml`).

---

## Acceptance Criteria

- [ ] `packages/parrot-formdesigner/pyproject.toml` lists
      `navigator-auth`, `lxml>=6.1.0`, `reportlab>=4.1.0` in
      `[project.dependencies]`.
- [ ] `parrot_formdesigner.version.__version__ == "0.2.0"`.
- [ ] Any redundant `[project.optional-dependencies]` entry that only
      held `navigator-auth` is removed.
- [ ] `source .venv/bin/activate && uv pip install -e
      packages/parrot-formdesigner` resolves without errors.
- [ ] `python -c "import parrot_formdesigner; print(parrot_formdesigner.__version__)"`
      prints `0.2.0`.

---

## Test Specification

This task has no unit tests of its own; the verification is the install
+ version-print check above. Subsequent tasks rely on these deps being
importable.

---

## Agent Instructions

When you pick up this task:

1. Read the spec at `sdd/specs/formdesigner-refactor.spec.md` (§1, §3
   Module 5, §7 External Dependencies).
2. Open `packages/parrot-formdesigner/pyproject.toml` and find the
   `[project.dependencies]` table.
3. Add the three deps with `>=` floors per the spec.
4. Bump `__version__` in `version.py` to `0.2.0`.
5. Activate venv and re-install the package.
6. Mark this task done in `sdd/tasks/index/formdesigner-refactor.json`,
   move this file to `sdd/tasks/completed/`, fill in the Completion Note.

---

## Completion Note

*(Agent fills this in when done)*

**Completed by**:
**Date**:
**Notes**:

**Completed by**: sdd-worker (Claude Sonnet)
**Date**: 2026-05-07
**Notes**: Promoted navigator-auth, lxml>=6.1.0, reportlab>=4.1.0 to required dependencies. Bumped version to 0.2.0. Added test extras with pypdf>=6.0 and jsonschema>=4.0 (needed by Wave 2 tests). Verified by `import parrot_formdesigner; print(parrot_formdesigner.__version__)` → "0.2.0".
