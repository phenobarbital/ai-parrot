# TASK-2205: Revert the tenant middleware from `app.py`

**Feature**: FEAT-421 — Client-declared tenant in the forms URL
**Spec**: `sdd/specs/forms-tenant-in-url.spec.md`
**Status**: pending
**Priority**: medium
**Estimated effort**: S (< 2h)
**Depends-on**: TASK-2201
**Assigned-to**: unassigned

---

## Context

Implements spec Module 9. This is the proof of spec G4: once the decorator ships
inside the wheel, the repository's own host application needs **zero** tenant
wiring. Deleting `forms_tenant_context_middleware` and leaving forms correctly
scoped is the demonstration that no other host needs to copy it either.

Only run this if PR #1149 was merged to `dev`. If it was closed unmerged (the
planned outcome), `app.py` never received the middleware — verify and close the
task as a no-op rather than inventing something to delete.

---

## Scope

- Delete the `forms_tenant_context_middleware` function from `app.py`.
- Delete its registration (`self.app.middlewares.append(...)`) from `configure()`.
- Delete the now-unused `from aiohttp import web` import **only if** nothing
  else in `app.py` uses it — check before removing.
- Delete PR #1149's `tests/test_forms_tenant_context_middleware.py` if present;
  its case matrix already lives in TASK-2199's decorator tests.
- If the middleware is not present, record that in the Completion Note and
  close the task without changes.

**NOT in scope**: any other `app.py` change; any other middleware in the host.

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `app.py` | MODIFY | Remove the middleware + its registration |
| `tests/test_forms_tenant_context_middleware.py` | DELETE | Superseded by decorator tests |

---

## Codebase Contract (Anti-Hallucination)

### What PR #1149 added — the exact shape to remove

```python
# app.py, after the imports
@web.middleware
async def forms_tenant_context_middleware(request: web.Request, handler):
    """FEAT-421 — declare the browsed programme as the form request's tenant."""
    program_slug = request.query.get("program_slug")
    if program_slug:
        session = getattr(request, "session", None)
        if session is not None:
            userinfo = session.get("session", {}) or {}
            programs = userinfo.get("programs", []) or []
            is_superuser = bool(userinfo.get("superuser", False))
            if is_superuser or program_slug in programs:
                request["tenant_context"] = program_slug
    return await handler(request)


# app.py, inside Main.configure(), after auth.setup and the add_exclude_list calls:
        self.app.middlewares.append(forms_tenant_context_middleware)
```

The registration sits immediately after these existing lines, which MUST stay:

```python
        auth.add_exclude_list('/a2a/*')
        auth.add_exclude_list('/.well-known/*')
```

and immediately before the PBAC block, which MUST stay:

```python
        # PBAC setup — navigator-auth Rust evaluator bug is now fixed.
        # setup_pbac() MUST be called BEFORE BotManager.setup(app) ...
```

### Does NOT Exist

- ~~any other writer of `request["tenant_context"]`~~ — a repo-wide grep finds
  only this one. Once it is gone, spec AC8 is satisfiable.
- ~~`app.py` being installed by the wheel~~ — it is not. That is the entire
  reason this middleware could never have worked for `fieldsync` or
  `navigator`, and why it is being removed rather than relocated.
- ~~other middlewares that must be removed~~ — only this one. `app.py` may
  register unrelated middlewares; leave every one of them alone.

---

## Implementation Notes

### Key Constraints

- Do NOT reorder or touch anything else in `configure()`. The ordering
  constraints around `setup_pbac()` / `BotManager.setup(app)` are load-bearing
  and documented in place.
- Verify `web` is genuinely unused in `app.py` before dropping the import —
  `from aiohttp import web` may predate PR #1149.
- After this task, `grep -rn "tenant_context" app.py packages/` must return
  nothing at all (combined with TASK-2202 and TASK-2203).

### References in Codebase

- PR #1149's diff — the authoritative record of what was added.
- `sdd/specs/FEAT-421-form-tenant-program-slug-scoping.spec.md` — PR #1149's
  own spec, if it landed. Remove it too if present; it describes the rejected
  design and shares this feature's ID.

---

## Acceptance Criteria

- [ ] `grep -n "forms_tenant_context_middleware" app.py` returns nothing
- [ ] `grep -rn "tenant_context" app.py packages/` returns nothing (spec AC8)
- [ ] `grep -n "middlewares.append" app.py` shows no tenant-related middleware
- [ ] `auth.add_exclude_list` calls and the PBAC block are unchanged
- [ ] The app still boots: `python -c "import app"` (or the project's usual smoke check)
- [ ] No linting errors: `ruff check app.py`

---

## Test Specification

```python
# tests/test_no_tenant_middleware.py
import re
from pathlib import Path


def test_app_py_has_no_tenant_middleware():
    """FEAT-421 G4: the host needs zero tenant wiring."""
    source = Path("app.py").read_text()
    assert "forms_tenant_context_middleware" not in source
    assert "tenant_context" not in source


def test_no_tenant_context_anywhere():
    """FEAT-421 AC8."""
    hits = []
    for path in Path("packages").rglob("*.py"):
        if "tenant_context" in path.read_text():
            hits.append(str(path))
    assert hits == [], f"tenant_context still referenced in: {hits}"
```

---

## Agent Instructions

1. **Read the spec** at `sdd/specs/forms-tenant-in-url.spec.md` (Module 9, G4)
2. **Check dependencies** — TASK-2201 must be in `sdd/tasks/completed/`
3. **Verify** whether the middleware is actually present; if PR #1149 was closed unmerged it will not be — close as a verified no-op
4. **Update status** in `sdd/tasks/index/forms-tenant-in-url.json` → `"in-progress"`
5. **Implement** following the scope and notes above
6. **Verify** all acceptance criteria are met
7. **Move this file** to `sdd/tasks/completed/TASK-2205-revert-app-py-middleware.md`
8. **Update index** → `"done"`
9. **Fill in the Completion Note** below

---

## Completion Note

*(Agent fills this in when done)*

**Completed by**:
**Date**:
**Notes**:

**Deviations from spec**: none | describe if any
