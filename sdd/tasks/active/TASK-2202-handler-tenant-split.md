# TASK-2202: Split `_get_tenant` (forms) from `_session_tenant` (`/org/*`)

**Feature**: FEAT-421 — Client-declared tenant in the forms URL
**Spec**: `sdd/specs/forms-tenant-in-url.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: L (4-8h)
**Depends-on**: TASK-2199, TASK-2201
**Assigned-to**: unassigned

---

## Context

Implements spec Module 5 — where the guessing actually dies.

`FormAPIHandler._get_tenant` (`api/handlers.py:256`) has 30 call sites. Twenty-one
are forms handlers and nine are `/org/*` handlers. Because `/org/*` stays out of
the tenant-URL scheme (spec G7), the two groups need different resolvers. The
method KEEPS its name and signature so the 21 forms call sites are not edited at
all — only its body changes.

The nine `/org/*` sites move to a new, deliberately verbose `_session_tenant`.
The rename is the point: it makes the surviving `programs[0]` inference greppable
and impossible to reach from a forms handler by accident.

---

## Scope

- Replace the body of `_get_tenant` with a read of the decorator-validated
  value (`declared_tenant(request)`), raising `RuntimeError` when absent.
  **Do not change its signature** — `(self, request: web.Request) -> str`.
- Add `_session_tenant(self, request) -> str` carrying today's logic verbatim:
  `programs[0]` if present, else `self.registry.default_tenant`.
- Repoint the **nine** `/org/*` call sites to `_session_tenant` (mechanical).
- Add `_assert_form_tenant(form, tenant)` — raise `HTTPNotFound` (404, NOT 403)
  when a resolved form's tenant differs from the declared one. Apply it after
  every `registry.get` / `get_by_slug` in forms handlers.
- Add `assert_body_tenant_matches(body, tenant)` on the write verbs, at the
  three `registry.register` sites.
- Delete the `request["tenant_context"]` read at `:280`.

**NOT in scope**: `api/_utils.py` (TASK-2203), route paths (done in TASK-2201),
migrating existing tests (TASK-2206).

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/parrot-formdesigner/src/parrot_formdesigner/api/handlers.py` | MODIFY | The split + assertions |
| `packages/parrot-formdesigner/tests/unit/api/test_handler_tenant_split.py` | CREATE | Unit tests |

---

## Codebase Contract (Anti-Hallucination)

### Verified Imports

```python
from aiohttp import web                              # api/handlers.py:17
from navigator.responses import JSONResponse         # api/handlers.py:19
from ..services.registry import FormAlreadyExistsError, FormRegistry  # api/handlers.py:28
from .tenant import declared_tenant, assert_body_tenant_matches       # TASK-2199
```

### Existing Signatures to Use

```python
# packages/parrot-formdesigner/src/parrot_formdesigner/api/handlers.py
class FormAPIHandler:                                                 # :102
    def _get_org_id(self, request) -> int | None:                     # :207  LEAVE UNCHANGED
    def _get_programs(self, request) -> list[str]:                    # :235  KEEP — used by _session_tenant
    def _get_tenant(self, request: web.Request) -> str:               # :256  BODY REPLACED
        declared = request.get("tenant_context")                      # :280  DELETE
        if declared: return str(declared)                             # :281-282  DELETE
        programs = self._get_programs(request)                        # :283  MOVES to _session_tenant
        if programs: return programs[0]                               # :284-285  MOVES
        return self.registry.default_tenant                           # :286  MOVES

# packages/parrot-formdesigner/src/parrot_formdesigner/services/registry.py
async def get(self, form_uid: uuid.UUID, *, tenant: str | None = None) -> FormSchema | None:  # :858
async def get_by_slug(...)                                                                     # :886
async def register(self, form, *, persist=False, overwrite=True, tenant=None) -> None:         # :367
@property
def default_tenant(self) -> str:                                                               # :259
```

### The 30 call sites, classified — DO NOT MISCLASSIFY

```
FORMS (21) — leave the call `self._get_tenant(request)` EXACTLY as-is:
   639 list_forms          738 get_form           769 get_schema
   797 get_style           833 remote_event       895 validate
   940 create_blank_form   994 create_form       1041 edit_form
  1168 update_form        1230 patch_form        1285 delete_form
  1349 submit_data        1628 load_from_db      1725 publish_form
  1748 list_fields        1765 create_field      1795 list_versions
  1831 get_version        1855 get_import_report 1892 _rbac_shadow_gate

  # _rbac_shadow_gate (:1868) is a HELPER, called only from form write
  # handlers: create :976, edit :1033, update :1166, patch :1228, delete :1283.
  # It is forms-side. Do not move it to _session_tenant.

ORG (9) — change to `self._session_tenant(request)`:
  1962 get_org_graph      2030 create_project    2089 map_project_workday
  2162 assign_user_role   2275 list_sites        2326 create_site
  2368 list_locations     2435 create_location   2482 get_location

WRITE SITES gaining the body cross-check:
   953, 1202, 1267   await self.registry.register(...)
```

### Does NOT Exist

- ~~`request["tenant_context"]`~~ — after this task, no reader remains in
  `handlers.py`. Spec AC8.
- ~~`FormAPIHandler._require_tenant` / `_authorize_tenant`~~ — an earlier spec
  revision proposed these; the decorator (TASK-2199) owns that job now. Do not
  add them.
- ~~a 403 for cross-tenant form access~~ — it must be **404**. A 403 confirms
  the form exists under some other tenant, which is an existence oracle.
- ~~an org→tenant mapping service~~ — none exists. `/org/*` handlers pass
  `org_id` and `tenant` as two independent arguments; do not try to derive one
  from the other.
- ~~`self.registry.default_tenant` on a forms path~~ — unreachable after this
  task. Spec AC4.

---

## Implementation Notes

### Pattern to Follow

```python
def _get_tenant(self, request: web.Request) -> str:
    """Return the tenant declared in the URL and validated by the decorator.

    Raises:
        RuntimeError: If `requires_tenant` did not run for this route — a
            registration bug, never a runtime condition to recover from.
    """
    return declared_tenant(request)


def _session_tenant(self, request: web.Request) -> str:
    """Legacy session-derived tenant, for /org/* only (FEAT-421 G7).

    Preserves pre-0.9.0 behaviour verbatim. Organizations are the layer
    that DEFINES tenants, so they are not scoped by a declared one. The
    surviving `programs[0]` inference is a known residual — see the spec's
    §7 "Residual" note.
    """
    programs = self._get_programs(request)
    if programs:
        return programs[0]
    return self.registry.default_tenant
```

### Key Constraints

- Work call site by call site against the classified list above. A forms
  handler wired to `_session_tenant` reintroduces exactly the bug this feature
  removes, silently.
- `_assert_form_tenant` must run on every read path that returns a form to the
  caller, not only `get_form` — `get_schema`, `get_style`, `render`,
  `validate`, `submit_data` and the version endpoints all resolve a form.
- The body cross-check is a no-op when the body has no `tenant` key. It is an
  optional cross-check, never a required field.
- Keep `_get_programs` — `_session_tenant` depends on it and it stays the
  reference shape for the decorator's session read.

### References in Codebase

- `api/handlers.py:256-286` — the method being split.
- `api/handlers.py:207-230` — `_get_org_id`, the `/org/*` identity path, untouched.

---

## Acceptance Criteria

- [ ] `_get_tenant` signature unchanged; the 21 forms call-site LINES are unmodified
- [ ] The 9 `/org/*` call sites call `_session_tenant`
- [ ] `_get_tenant` raises `RuntimeError` when the decorator did not run
- [ ] `_session_tenant` returns exactly what `_get_tenant` returned on 0.8.21 for the same request
- [ ] Cross-tenant form access returns **404**, not 403
- [ ] Body `tenant` mismatch on POST/PUT/PATCH → 400 `tenant_conflict`; matching or absent → proceeds
- [ ] `grep -n "tenant_context" packages/parrot-formdesigner/src/parrot_formdesigner/api/handlers.py` returns nothing
- [ ] No forms path can reach `registry.default_tenant`
- [ ] No linting errors: `ruff check packages/parrot-formdesigner/src/parrot_formdesigner/api/handlers.py`

---

## Test Specification

```python
class TestTenantSplit:
    def test_get_tenant_returns_declared(self, handler, request_with_tenant):
        assert handler._get_tenant(request_with_tenant) == "flexroc"

    def test_get_tenant_raises_without_decorator(self, handler, bare_request):
        with pytest.raises(RuntimeError):
            handler._get_tenant(bare_request)

    def test_get_tenant_never_returns_default(self, handler, bare_request):
        """The 0.8.21 fallback must be gone from the forms path."""
        with pytest.raises(RuntimeError):
            handler._get_tenant(bare_request)

    def test_session_tenant_prefers_first_program(self, handler, session_request):
        assert handler._session_tenant(session_request) == "navigator"

    def test_session_tenant_falls_back_to_default(self, handler, no_programs_request):
        assert handler._session_tenant(no_programs_request) == handler.registry.default_tenant


class TestCrossTenantIsolation:
    async def test_other_tenant_form_is_404(self, handler, two_tenant_registry):
        """404, never 403 — a 403 is an existence oracle."""
        resp = await handler.get_form(request_for(tenant="flexroc", uid=uid_in_navigator))
        assert resp.status == 404


class TestBodyCrossCheck:
    async def test_conflicting_body_tenant_is_400(self, handler):
        resp = await handler.create_form(request_for(tenant="flexroc", body={"tenant": "navigator"}))
        assert resp.status == 400
```

---

## Agent Instructions

1. **Read the spec** at `sdd/specs/forms-tenant-in-url.spec.md` (Module 5, §6 call-site table)
2. **Check dependencies** — TASK-2199 and TASK-2201 must be in `sdd/tasks/completed/`
3. **Verify the Codebase Contract** — re-grep the 30 call sites; line numbers shift as earlier tasks land, so match on METHOD NAME, not line number
4. **Update status** in `sdd/tasks/index/forms-tenant-in-url.json` → `"in-progress"`
5. **Implement** following the scope and notes above
6. **Verify** all acceptance criteria are met
7. **Move this file** to `sdd/tasks/completed/TASK-2202-handler-tenant-split.md`
8. **Update index** → `"done"`
9. **Fill in the Completion Note** below

---

## Completion Note

*(Agent fills this in when done)*

**Completed by**:
**Date**:
**Notes**:

**Deviations from spec**: none | describe if any
