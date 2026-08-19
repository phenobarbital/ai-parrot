# TASK-2246: Drop `/t/` literal from route registration

**Feature**: FEAT-429 — Remove `/t/` marker from tenant-qualified URLs
**Spec**: `sdd/specs/fieldsync-tenant-url.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: S (< 2h)
**Depends-on**: none
**Assigned-to**: unassigned

---

## Context

FEAT-429 removes the `/t/` literal URL segment from all FormDesigner
tenant-qualified routes. This task handles the **structural change**: the
`tp` prefix variable in both `api/routes.py` and `ui/routes.py` that every
forms route is built from.

Implements spec Module 1.

---

## Scope

- Change the `tp` prefix variable in `api/routes.py` from
  `f"{bp}/t/{{tenant}}"` to `f"{bp}/{{tenant}}"`.
- Change the `tp` prefix variable in `ui/routes.py` identically.
- Update the Telegram REST fallback route in `ui/routes.py` (hardcoded
  path, not built from `tp`).
- Update the log message in `api/routes.py:357`.
- Update all FEAT-421 comments in both files to reflect the new URL shape.

**NOT in scope**:
- URL strings in handler response bodies, renderers, error hints, or
  docstrings (TASK-2247).
- Test file updates (TASK-2248).
- Migration guide (TASK-2249).

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `.../api/routes.py` | MODIFY | `tp` variable (line 233), log message (line 357), comments |
| `.../ui/routes.py` | MODIFY | `tp` variable (line 136), telegram-submit route (line 169), comments |

All paths under `packages/parrot-formdesigner/src/parrot_formdesigner/`.

---

## Codebase Contract (Anti-Hallucination)

### Verified Imports

No new imports needed — this task only changes string values.

### Existing Signatures to Use

```python
# packages/parrot-formdesigner/src/parrot_formdesigner/api/routes.py
def setup_form_api(app, registry, *, ...):                  # line 116
    bp = base_path.rstrip("/")                              # line 226
    tp = f"{bp}/t/{{tenant}}"                               # line 233 — CHANGE to f"{bp}/{{tenant}}"
    # ... all routes below use tp, e.g.:
    # app.router.add_get(f"{tp}/forms", ...)                # line 236
    # log message:
    # logger.info("setup_form_api: audio WS endpoint mounted at %s/t/{tenant}/...", bp)  # line 357

# packages/parrot-formdesigner/src/parrot_formdesigner/ui/routes.py
def setup_form_ui(app, registry, *, ...):                   # line 105
    bp = base_path.rstrip("/")                              # line 132
    tp = f"{bp}/t/{{tenant}}"                               # line 136 — CHANGE to f"{bp}/{{tenant}}"
    # telegram-submit route (not built from tp):
    # f"{bp}/api/v1/t/{{tenant}}/forms/{{form_uid}}/telegram-submit"  # line 169
```

### Does NOT Exist

- ~~`_TENANT_PREFIX` constant~~ — does not exist; the `/t/` marker is
  inline in the `tp` f-string, not extracted to a named constant.
- ~~`setup_form_api(tenant_prefix=...)`~~ — no such parameter.
- ~~A shared `_build_tenant_path()` helper~~ — does not exist; each
  `setup_form_*` function defines its own `tp` locally.

---

## Implementation Notes

### Pattern to Follow

The change is a one-line edit in each file for the `tp` variable:

```python
# BEFORE
tp = f"{bp}/t/{{tenant}}"

# AFTER
tp = f"{bp}/{{tenant}}"
```

The telegram-submit route in `ui/routes.py:169` is hardcoded (not built
from `tp`) and must be edited separately:

```python
# BEFORE
f"{bp}/api/v1/t/{{tenant}}/forms/{{form_uid}}/telegram-submit"

# AFTER
f"{bp}/api/v1/{{tenant}}/forms/{{form_uid}}/telegram-submit"
```

### Key Constraints

- **Preserve route registration order**: `POST /forms/blank` MUST stay
  registered BEFORE the `{form_uid}` catch-all (api/routes.py:242 before
  :247). Do not reorder routes.
- **Do NOT modify `_wrap_auth` or `_page_wrap`** — only the URL prefix
  changes.
- **Do NOT touch `/org/*` routes** — they use `bp` directly
  (`f"{bp}/org/..."`, line 389+), not `tp`, so they are inherently
  unaffected. Verify this by confirming no `/org/*` route references `tp`.
- **Do NOT touch the `form-controls` route** — it uses `f"{bp}/form-controls"`,
  not `tp` (line 294).
- Update FEAT-421 comment blocks (lines 227–232 in api/routes.py, lines
  133–135 in ui/routes.py) to say `{tenant}` rather than `t/{tenant}`.

---

## Acceptance Criteria

- [ ] `tp` in `api/routes.py` is `f"{bp}/{{tenant}}"` (no `/t/`).
- [ ] `tp` in `ui/routes.py` is `f"{bp}/{{tenant}}"` (no `/t/`).
- [ ] Telegram-submit route in `ui/routes.py` uses `/{tenant}/`, not `/t/{tenant}/`.
- [ ] Log message in `api/routes.py` uses `/{tenant}/`, not `/t/{tenant}/`.
- [ ] No `/org/*` route path changed.
- [ ] No `/form-controls` route path changed.
- [ ] Route registration order preserved.
- [ ] `ruff check packages/parrot-formdesigner/src/parrot_formdesigner/api/routes.py packages/parrot-formdesigner/src/parrot_formdesigner/ui/routes.py` clean.

---

## Test Specification

No new tests in this task — existing route-path assertion tests are updated
in TASK-2248. After this task, the existing test suite is expected to have
URL-mismatch failures until TASK-2248 lands.

---

## Agent Instructions

When you pick up this task:

1. **Read the spec** at `sdd/specs/fieldsync-tenant-url.spec.md`
2. **Verify** the `tp` variable is still at the expected line numbers
3. **Edit** the 4 sites: `api/routes.py:233`, `api/routes.py:357`,
   `ui/routes.py:136`, `ui/routes.py:169`
4. **Update comments** referencing `/t/{tenant}` in both files
5. **Verify** no `/org/*` or `/form-controls` route was touched
6. **Run** `ruff check` on both files
7. **Commit** with message: `feat(formdesigner): drop /t/ from route table (FEAT-429 TASK-2246)`

---

## Completion Note

**Completed by**: sdd-worker (autonomous)
**Date**: 2026-08-18
**Notes**: Changed `tp` in `api/routes.py:233` and `ui/routes.py:136` from
`f"{bp}/t/{{tenant}}"` to `f"{bp}/{{tenant}}"`. Updated the telegram-submit
route (`ui/routes.py:169`) and the audio-WS log message (`api/routes.py:358`,
one line off from the task's stated :357 — verified via grep before editing).
Updated the FEAT-421 comment blocks in both files to describe the new URL
shape while preserving the original rationale. Verified `/org/*` and
`/form-controls` routes still build from `bp` directly (untouched) and route
registration order is unchanged. `ruff check` on both files shows 19
pre-existing errors (import sorting, `UP037` quoted annotations, one
`BLE001`) — confirmed identical before and after this change via
`git stash`/`git stash pop`, so out of scope for this task.

**Deviations from spec**: none
