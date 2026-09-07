# TASK-2935: `A2UIHandler` mirror route passes the scope; end-to-end visibility round trip

**Feature**: FEAT-535 — Tenant-aware, permission-based visibility for UI surfaces
**Spec**: `sdd/specs/ui-surfaces-tenant-visibility.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: M (2-4h)
**Depends-on**: TASK-2934
**Assigned-to**: unassigned

---

## Context

Implements the rest of **Module 3**. `resolve_surface_access` was promoted to
a module-level function precisely so the REST lane and the `A2UIHandler`
mirror route (`GET /api/v1/agents/{agent_id}/a2ui/surfaces/{surface_id}`)
cannot drift. TASK-2934 gave it a `scope` kwarg; this task makes the mirror
pass one, and proves the whole feature end to end through the existing e2e
harness with a stub resolver installed on the app.

---

## Scope

- `packages/ai-parrot-server/src/parrot/handlers/a2ui.py::_get_surface` (:265-290): after `_authenticate`, `scope = await get_scope_resolver(self.request.app).resolve(self.request)`; call `resolve_surface_access(self._ui_surfaces_store(), surface_id, user_id, token, scope=scope)`. Nothing else changes (negotiation, `agent_id` handling).
- `tests/handlers/test_a2ui_surfaces_route.py`: add `test_mirror_route_tenant_visible_viewer_200` (stub resolver on the app; `fake_store.get` returns a `tenant`-visible record owned by someone else → `200`) and `test_mirror_route_foreign_tenant_404` (scope tenant differs → `404`). Keep every existing test.
- `tests/integration/test_ui_surfaces_e2e.py`: extend `_FakeConn`'s SQL dispatch so `list_visible`/`update_visibility` work over `fake_state.surfaces` (mirror TASK-2932's fake), then add `test_e2e_tenant_visibility_roundtrip`: pin as A (`visibility=tenant`, resolver stub tenant T) → list as B in T shows it with `access="tenant"` → B `GET` and `refresh` `200` → C in tenant U does not see it and gets `404` → A `PATCH` to `groups` `["g1"]` → B with `groups={"g1"}` sees it, B with `{"g2"}` does not → superuser in T sees it regardless → B `DELETE` → `404`, row intact.

**NOT in scope**: docs (TASK-2936); any change to `resolve_surface_access` itself (done in TASK-2934).

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot-server/src/parrot/handlers/a2ui.py` | MODIFY | pass `scope=` in `_get_surface` |
| `packages/ai-parrot-server/tests/handlers/test_a2ui_surfaces_route.py` | MODIFY | two viewer tests |
| `packages/ai-parrot-server/tests/integration/test_ui_surfaces_e2e.py` | MODIFY | fake SQL dispatch + round-trip test |

---

## Codebase Contract (Anti-Hallucination)

### Verified Imports
```python
from parrot.handlers.ui_surfaces import resolve_surface_access            # a2ui.py:55 already imports it
from parrot.handlers.ui_surfaces_scope import SurfaceScope, get_scope_resolver   # TASK-2933
from parrot.handlers.models.ui_surfaces import SurfaceVisibility           # TASK-2932
```

### Existing Signatures to Use
```python
# packages/ai-parrot-server/src/parrot/handlers/a2ui.py (origin/dev 3d03bb2cd)
    def _ui_surfaces_store(self) -> PgUISurfaceStore                        # :243-251  app["ui_surfaces_store"] shared with the REST lane
    def _ui_surfaces_negotiation(self)                                       # (sibling helper, same idiom)
    async def _get_surface(self) -> web.Response                             # :265-290
        _agent, user_id, _session_id, err = await self._authenticate(self._resolution_data())   # :276
        surface_id = self.request.match_info["surface_id"]; token = qs.get("share")            # :279-281
        record, error = await resolve_surface_access(self._ui_surfaces_store(), surface_id, user_id, token)   # :284  ← add scope=
        negotiation.respond(record, accept)                                  # :289-290

# tests/handlers/test_a2ui_surfaces_route.py
fake_store fixture (get/resolve_share/claim_share AsyncMocks)              # :89-95
_stub_auth_middleware: request["authenticated"]=True; request["NAV_SESSION"]=SessionData(data={"user_id": "u-test"})   # :97-103
client fixture: app["ui_surfaces_store"], app["ui_surfaces_negotiation"], routes incl. /api/v1/agents/{agent_id}/a2ui/surfaces/{surface_id}   # :107-131
_auth_params(user_id="u-1", session_id="sess-1")                          # :132  (the mirror route's identity comes from _authenticate → user_id "u-1" by default)

# tests/integration/test_ui_surfaces_e2e.py
_FakeConn dispatch on SQL text (user_id filters at :167-178)               # :60-190  — extend for the new SQL constants
fake_state / store fixtures                                                 # :200-208
class _FakeRequest(app, match_info, path, json_body, user_id, query, headers)   # :218-232  (.user = SimpleNamespace(user_id=...))
def _handler(app, **kwargs) -> UISurfacesHandler ; def _unwrap(method)      # :233-245
```

### Does NOT Exist
- ~~a second copy of the access rule inside `a2ui.py`~~ — it MUST keep calling the shared function.
- ~~tenant derived from `agent_id`~~ — the scope comes from the resolver on the request.
- ~~`make_mocked_request` in the e2e harness~~ — it uses `_FakeRequest`; install the stub resolver on the `app` dict instead.

---

## Implementation Notes

### Key Constraints
- One-line functional change in `a2ui.py`; the value is in the tests.
- The e2e fake must model `?|` semantics (set intersection) and `is_superuser` faithfully — copy TASK-2932's fake dispatch rather than re-inventing it; if TASK-2932 factored it into a shared test helper, import that.
- Do not weaken any existing `404`/`410` test.

### References in Codebase
- `tests/handlers/test_a2ui_surfaces_route.py:171-202` — token/foreign/bad-token tests to mirror for the scope case.

---

## Acceptance Criteria

- [ ] Mirror route: tenant-visible viewer `200`; foreign-tenant viewer `404`; all existing mirror tests pass
- [ ] `test_e2e_tenant_visibility_roundtrip` passes and exercises pin → list → GET → refresh → PATCH → groups → superuser → viewer delete `404`
- [ ] `ruff check` clean

---

## Test Specification

```python
# tests/handlers/test_a2ui_surfaces_route.py (excerpt)
async def test_mirror_route_tenant_visible_viewer_200(client, fake_store):
    rec = _make_record(user_id="someone-else", tenant="epson", visibility=SurfaceVisibility.tenant)
    fake_store.get = AsyncMock(return_value=rec)
    client.app["ui_surfaces_scope_resolver"] = _StubResolver(SurfaceScope("u-1", "epson", frozenset(), False))
    resp = await client.get(f"/api/v1/agents/{AGENT}/a2ui/surfaces/{rec.surface_id}", params=_auth_params())
    assert resp.status == 200
```

---

## Agent Instructions

1. Read spec §2 (mirror row in the HTTP table), §3 Module 3, §4 Integration Tests.
2. Verify the contract; implement; run `pytest packages/ai-parrot-server/tests/handlers/test_a2ui_surfaces_route.py packages/ai-parrot-server/tests/integration/test_ui_surfaces_e2e.py -v`; `ruff check`.
3. Index → `in-progress` → `done`; move to `completed/`; Completion Note.

---

## Completion Note

*(Agent fills this in when done)*

**Completed by**:
**Date**:
**Notes**:

**Deviations from spec**: none | describe if any
