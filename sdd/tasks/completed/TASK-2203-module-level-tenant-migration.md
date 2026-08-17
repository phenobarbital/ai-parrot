# TASK-2203: Migrate module-level handlers and delete `_get_request_tenant`

**Feature**: FEAT-421 — Client-declared tenant in the forms URL
**Spec**: `sdd/specs/forms-tenant-in-url.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: M (2-4h)
**Depends-on**: TASK-2199, TASK-2201
**Assigned-to**: unassigned

---

## Context

Implements spec Module 6. `api/_utils.py:16` holds `_get_request_tenant`, a
module-level twin of `FormAPIHandler._get_tenant` with the same three-step
fallback (`tenant_context` → `programs[0]` → `default_tenant`, `:50-65`). It
serves the handlers that are plain module functions rather than methods:
`operations.py`, `render.py`, `uploads.py`.

Deleting it is what makes spec AC8 true. Leaving it would keep a second,
parallel guessing path alive after the main one is gone — invisible unless you
grep for it.

---

## Scope

- Replace `_get_request_tenant(request)` with `declared_tenant(request)` at:
  - `api/operations.py:551`
  - `api/render.py:131`
  - `api/uploads.py:247`
- Delete `_get_request_tenant` from `api/_utils.py` entirely, along with its
  now-unused import surface. Keep the other helpers in that file
  (`_deep_merge`, `_loc_to_str`, `_bump_version`) untouched.
- Update the three import statements that pull it in.

**NOT in scope**: `ui/telegram.py`'s local duplicate (TASK-2204 owns it),
`handlers.py` (TASK-2202), route paths (TASK-2201).

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/parrot-formdesigner/src/parrot_formdesigner/api/_utils.py` | MODIFY | Delete `_get_request_tenant` |
| `packages/parrot-formdesigner/src/parrot_formdesigner/api/operations.py` | MODIFY | Import + call site |
| `packages/parrot-formdesigner/src/parrot_formdesigner/api/render.py` | MODIFY | Import + call site |
| `packages/parrot-formdesigner/src/parrot_formdesigner/api/uploads.py` | MODIFY | Import + call site |
| `packages/parrot-formdesigner/tests/unit/api/test_module_level_tenant.py` | CREATE | Unit tests |

---

## Codebase Contract (Anti-Hallucination)

### Verified Imports — the exact lines to edit

```python
# api/operations.py:39
from ._utils import _bump_version, _deep_merge, _get_request_tenant
#   -> keep _bump_version and _deep_merge; drop _get_request_tenant
#   -> add: from .tenant import declared_tenant

# api/render.py:27
from ._utils import _get_request_tenant
#   -> replace entirely with: from .tenant import declared_tenant

# api/uploads.py:66
from ._utils import _get_request_tenant
#   -> replace entirely with: from .tenant import declared_tenant
```

### Existing Signatures

```python
# packages/parrot-formdesigner/src/parrot_formdesigner/api/_utils.py:16-65
def _get_request_tenant(request: "web.Request") -> str | None:   # :16  DELETE
    declared = request.get("tenant_context")                     # :50  the removed step 0
    if declared: return str(declared)                            # :51-52
    session = getattr(request, "session", None)                  # :54
    ...
    programs: list[str] = userinfo.get("programs", [])           # :57
    if programs: return programs[0]                              # :58-59
    registry = request.app.get("form_registry") ...              # :61
    default = getattr(registry, "default_tenant", None)          # :63
    ...
    return None                                                  # :65

# Call sites — the ONLY three in this task:
# api/operations.py:551   tenant = _get_request_tenant(request)
# api/render.py:131       tenant = _get_request_tenant(request)
# api/uploads.py:247      tenant = _get_request_tenant(request)

# Helpers in _utils.py that MUST SURVIVE:
def _deep_merge(base: dict, patch: dict) -> dict:   # :68
def _loc_to_str(value: object) -> str | None:       # :93
def _bump_version(version: str) -> str:             # :120
```

### Does NOT Exist

- ~~`ui/telegram.py` importing from `_utils`~~ — it defines its OWN copy at
  `ui/telegram.py:24`. This task does not touch it; TASK-2204 does. Do not
  assume deleting `_utils._get_request_tenant` fixes telegram.
- ~~a `None` return from `declared_tenant`~~ — it returns `str` or raises
  `RuntimeError`. The old function returned `str | None`; any `if tenant is
  None:` branch at the three call sites is now dead code and should be removed,
  not left as unreachable defensive handling.
- ~~`request.app.get("form_registry")` as a tenant source~~ — step 2 of the old
  fallback. Gone. Do not reintroduce it as a "safety net".

---

## Implementation Notes

### Key Constraints

- All three call sites are **forms** paths (operations = batched form edits,
  render = form rendering, uploads = REST field uploads), so they all get the
  declared tenant. None of them is `/org/*`.
- After swapping, check each call site for now-dead `None` handling and delete
  it — leaving it implies a fallback that can no longer occur.
- Run `grep -rn "_get_request_tenant" packages/parrot-formdesigner/src` at the
  end. The only remaining hit must be `ui/telegram.py` (TASK-2204's scope). Any
  other hit means a call site was missed.

### References in Codebase

- `api/_utils.py:16-65` — the function being deleted.
- `api/handlers.py:256` — the sibling method, split in TASK-2202.

---

## Acceptance Criteria

- [ ] `_get_request_tenant` no longer exists in `api/_utils.py`
- [ ] `_deep_merge`, `_loc_to_str`, `_bump_version` still exist and still import cleanly
- [ ] The three call sites use `declared_tenant`
- [ ] No dead `if tenant is None:` branches remain at those call sites
- [ ] `grep -rn "_get_request_tenant" packages/parrot-formdesigner/src` returns only `ui/telegram.py`
- [ ] `grep -rn "tenant_context" packages/parrot-formdesigner/src/parrot_formdesigner/api/` returns nothing
- [ ] No linting errors: `ruff check packages/parrot-formdesigner/src/parrot_formdesigner/api/`

---

## Test Specification

```python
class TestUtilsCleanup:
    def test_get_request_tenant_is_gone(self):
        from parrot_formdesigner.api import _utils
        assert not hasattr(_utils, "_get_request_tenant")

    def test_surviving_helpers_still_importable(self):
        from parrot_formdesigner.api._utils import (
            _bump_version, _deep_merge, _loc_to_str,
        )
        assert _deep_merge({"a": 1}, {"b": 2}) == {"a": 1, "b": 2}


class TestModuleLevelHandlers:
    async def test_operations_uses_declared_tenant(self, request_with_tenant):
        ...  # handle_operations resolves "flexroc", not programs[0]

    async def test_render_uses_declared_tenant(self, request_with_tenant):
        ...

    async def test_upload_uses_declared_tenant(self, request_with_tenant):
        ...

    async def test_no_tenant_raises_rather_than_defaults(self, bare_request):
        with pytest.raises(RuntimeError):
            ...
```

---

## Agent Instructions

1. **Read the spec** at `sdd/specs/forms-tenant-in-url.spec.md` (Module 6)
2. **Check dependencies** — TASK-2199 and TASK-2201 must be in `sdd/tasks/completed/`
3. **Verify the Codebase Contract** before writing any code
4. **Update status** in `sdd/tasks/index/forms-tenant-in-url.json` → `"in-progress"`
5. **Implement** following the scope and notes above
6. **Verify** all acceptance criteria are met
7. **Move this file** to `sdd/tasks/completed/TASK-2203-module-level-tenant-migration.md`
8. **Update index** → `"done"`
9. **Fill in the Completion Note** below

---

## Completion Note

**Completed by**: sdd-worker (Claude)
**Date**: 2026-08-16
**Notes**: Deleted `_get_request_tenant` and its now-unused `TYPE_CHECKING`/
`web` import surface from `api/_utils.py`; the three surviving helpers
(`_deep_merge`, `_loc_to_str`, `_bump_version`) are untouched. Swapped all
three call sites (`operations.py:551`, `render.py:131`, `uploads.py:247`,
pre-edit line numbers) to `declared_tenant(request)` from `.tenant`; none
had a dead `if tenant is None:` branch to remove (all three went straight
to `registry.get(form_uid, tenant=tenant)`). `grep -rn
"_get_request_tenant" .../src` now returns only `ui/telegram.py` (TASK-2204's
scope); `grep -rn "tenant_context" .../api/` returns nothing.

Full `tests/unit/` suite: 5 new failures beyond the post-TASK-2202
baseline, all confirmed (by inspecting the traceback) to be the intended
fail-loud hard-cut: `test_render_dispatcher.py` (3) and
`test_blob_uid_keys.py` (2) register `handle_render`/`handle_rest_upload`
directly on a bare router without ever declaring a tenant, so
`declared_tenant()` now raises `RuntimeError` instead of the old code
silently defaulting — exactly the AC2/§7 "fail-loud backstop" this task
implements. Deferred to TASK-2206 per this task's own scope note. New test
file: 7/7 passing. Lint diff-count unchanged for all four touched source
files (pre-existing, unrelated debt in `render.py`/`uploads.py`;
`_utils.py` and `operations.py` clean before and after).

**Deviations from spec**: none
