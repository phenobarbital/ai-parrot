# TASK-2703: A2UIHandler mirror route + route registration

**Feature**: FEAT-492 — A2UI Surface Rehydration
**Spec**: `sdd/specs/a2ui-surface-rehydration.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: M (2-4h)
**Depends-on**: TASK-2702
**Assigned-to**: unassigned

---

## Context

Spec §3 Module 4 (goal G6). Wires the plane into the running app: the
`A2UIHandler` GET dispatch gains a `/surfaces/{surface_id}` branch that
delegates to `SurfaceNegotiationService` (resolved decision: the mirror route
negotiates JSON/HTML exactly like the REST lane — NOT protocol-strict), and
`BotManager.setup_app()` registers all eight routes.

---

## Scope

- Modify `packages/ai-parrot-server/src/parrot/handlers/a2ui.py`:
  - In `A2UIHandler.get()`, add a path-dispatch branch BEFORE the SSE stream
    preparation: when the path matches `.../a2ui/surfaces/{surface_id}`,
    resolve auth via the existing `_authenticate(...)` (agent + user/session),
    load the record from `PgUISurfaceStore`, enforce owner-or-share access
    (same rules as TASK-2702 — reuse its helper, do not duplicate), and
    return `SurfaceNegotiationService.respond(record, accept)`.
  - POST dispatch, SSE stream, `/capabilities` — UNTOUCHED.
- Modify `packages/ai-parrot-server/src/parrot/manager/manager.py`
  (`setup_app`, next to the FEAT-469 block at ~2043-2050):
  - Register `A2UIHandler` at
    `/api/v1/agents/{agent_id}/a2ui/surfaces/{surface_id}` — BEFORE the bare
    `/api/v1/agents/{agent_id}/a2ui` pattern, mirroring the existing
    `/capabilities` literal-before-pattern ordering comment.
  - Register `UISurfacesHandler` routes:
    `/api/v1/ui/surfaces`, `/api/v1/ui/surfaces/{surface_id}`,
    `/api/v1/ui/surfaces/{surface_id}/refresh`,
    `/api/v1/ui/surfaces/{surface_id}/share`,
    `/api/v1/ui/surfaces/{surface_id}/share/{token}` (via `router.add_view`).
- Unit tests in
  `packages/ai-parrot-server/tests/handlers/test_a2ui_surfaces_route.py`.

**NOT in scope**: the service/handler logic itself (TASK-2702); e2e flows
(TASK-2705); any change to A2UIHandler POST/SSE behavior.

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot-server/src/parrot/handlers/a2ui.py` | MODIFY | GET surfaces branch |
| `packages/ai-parrot-server/src/parrot/manager/manager.py` | MODIFY | Route registration (minimal diff) |
| `packages/ai-parrot-server/tests/handlers/test_a2ui_surfaces_route.py` | CREATE | Route/dispatch tests |

---

## Codebase Contract (Anti-Hallucination)

> Verified 2026-09-01 against `dev`.

### Verified Imports
```python
from parrot.handlers.a2ui import A2UIHandler            # verified: handlers/a2ui.py
# From TASK-2702 (verify landed):
from parrot.handlers.ui_surfaces import UISurfacesHandler, SurfaceNegotiationService
# From TASK-2700 (verify landed):
from parrot.handlers.models.ui_surfaces import PgUISurfaceStore
```

### Existing Signatures to Use
```python
# packages/ai-parrot-server/src/parrot/handlers/a2ui.py (verified 2026-09-01)
class A2UIHandler(AgentTalk):
    async def get(self) -> web.StreamResponse:
        # CURRENT dispatch — extend this, do not restructure:
        #   if self.request.path.rstrip("/").endswith("/capabilities"):
        #       return await self._get_capabilities()
        #   return await self._get_stream()
    async def _authenticate(self, data) -> tuple: ...   # (agent, user_id, session_id, err)
    def _resolution_data(self) -> dict[str, Any]: ...

# packages/ai-parrot-server/src/parrot/manager/manager.py:2043-2050 (verified)
#   # ...literal segment must be registered so aiohttp resolves it
#   # before matching it as part of the bare "{agent_id}/a2ui" pattern,
#   router.add_view("/api/v1/agents/{agent_id}/a2ui/capabilities", A2UIHandler)   # :2045
#   router.add_view("/api/v1/agents/{agent_id}/a2ui", A2UIHandler)                # :2046
#   ...
#   self._register_a2ui_deeplink_routes()                                          # :2050
```

### Does NOT Exist
- ~~`/api/v1/agents/{agent_id}/a2ui/surfaces/{surface_id}` route~~ — THIS task registers it
- ~~any `/api/v1/ui/*` registration~~ — THIS task adds them
- ~~`A2UIHandler._get_surface`~~ — new private method THIS task introduces
- ~~negotiation logic inside a2ui.py~~ — MUST delegate to
  `SurfaceNegotiationService` (shared-service acceptance criterion; no duplication)

---

## Implementation Notes

### Pattern to Follow
```python
# a2ui.py get() — path dispatch first, StreamResponse only for the SSE branch:
path = self.request.path.rstrip("/")
if path.endswith("/capabilities"):
    return await self._get_capabilities()
if "surface_id" in self.request.match_info:
    return await self._get_surface()          # plain web.Response
return await self._get_stream()
```

### Key Constraints
- `match_info["surface_id"]` is only present when the surfaces route matched —
  dispatch on it rather than string-parsing the path.
- Keep the manager.py diff minimal and inside the FEAT-469 block; extend the
  existing ordering comment to mention `surfaces`.
- The mirror route enforces the same owner/share access rules as the REST
  lane (share `?share=` accepted); `agent_id` in the path is resolved for
  auth/consistency but the record lookup is by `surface_id` alone.
- aiohttp: literal `surfaces` segment resolves before the bare pattern —
  covered by an explicit test.

### References in Codebase
- `packages/ai-parrot-server/src/parrot/handlers/a2ui.py` — the file being extended
- `packages/ai-parrot-server/src/parrot/manager/manager.py:2043-2050` — registration block

---

## Acceptance Criteria

- [ ] `GET /api/v1/agents/{agent_id}/a2ui/surfaces/{id}` returns JSON and HTML
      per negotiation, via the SHARED service (assert the service is called —
      no duplicated negotiation code in a2ui.py)
- [ ] `/capabilities`, SSE stream, and POST dispatch behave exactly as before
      (existing FEAT-469 tests stay green)
- [ ] All eight routes registered; literal `surfaces` and `capabilities`
      segments resolve before the bare `{agent_id}/a2ui` pattern
- [ ] All tests pass: `pytest packages/ai-parrot-server/tests/handlers/test_a2ui_surfaces_route.py -v`
- [ ] Existing a2ui tests pass: `pytest packages/ai-parrot-server/tests -k a2ui -v`
- [ ] No linting errors on both modified files

---

## Test Specification

```python
# packages/ai-parrot-server/tests/handlers/test_a2ui_surfaces_route.py
async def test_mirror_route_json_and_html_negotiation(): ...
async def test_mirror_route_delegates_to_shared_service(): ...
async def test_mirror_route_share_token_access(): ...
async def test_capabilities_and_sse_unchanged(): ...
async def test_routes_registered_and_ordering(): ...   # surfaces before bare a2ui pattern
```

---

## Agent Instructions

1. **Read the spec** (§3 Module 4, §7 gotchas — StreamResponse ordering).
2. **Check dependencies** — TASK-2702 must be in `sdd/tasks/completed/`.
3. **Verify the Codebase Contract** — manager.py line numbers may have drifted.
4. **Update status** in `sdd/tasks/index/a2ui-surface-rehydration.json` → `"in-progress"`.
5. **Implement**, **verify**, **move to completed**, update index, fill Completion Note.

---

## Completion Note

**Completed by**: sdd-worker (Claude)
**Date**: 2026-09-01
**Notes**:
Added a `/surfaces/{surface_id}` branch to `A2UIHandler.get()` (before the
`/capabilities` branch's sibling check, both resolved BEFORE any
`StreamResponse` preparation — the bare pattern's SSE branch is unaffected).
`_get_surface()` calls the existing `_authenticate()` for agent/user
resolution (parity with every other route on this handler), then delegates
negotiation to the SAME `SurfaceNegotiationService` instance
`UISurfacesHandler` uses — both lazily cached on `app["ui_surfaces_store"]`/
`app["ui_surfaces_negotiation"]`, so whichever handler is hit first wires
them for both. `manager.py` registers the mirror route literal-before-bare
(next to the existing `/capabilities` ordering comment, extended to mention
`surfaces`) plus the five `UISurfacesHandler` URL shapes.

12 new tests across two areas: `test_a2ui_surfaces_route.py` (8, real
aiohttp `TestClient` — `A2UIHandler` doesn't use `@is_authenticated()`,
confirmed from its own module docstring, so the `test_a2ui_handler.py`
client-fixture idiom applies directly: negotiation JSON/HTML, shared-service
delegation via monkeypatched spies, share-token access + claim, 404/410
discipline, `/capabilities` + POST dispatch unchanged, and route ordering).
Reran `test_a2ui_handler.py` (27) + `test_infographic_recipes.py`/
`test_ui_surfaces_handler.py`/`test_ui_surfaces_store.py` alongside (71
total) — all green, no regressions to existing POST/SSE/`/capabilities`
behavior. `ruff check` clean on both modified files; confirmed via a
byte-identical `ruff check` run against `manager.py`'s pre-task committed
version (`git show <prev-sha>`) that its 105 pre-existing violations are
unchanged by this diff (my +17 lines add none).

**Deviations from spec**:
- The task's Scope says to "reuse [`UISurfacesHandler`'s] helper, do not
  duplicate" for the owner/share access-check rules, but its own Files to
  Create/Modify table does NOT list `ui_surfaces.py` (TASK-2702's file) —
  only `a2ui.py`/`manager.py`/the new test file. Rather than violate File
  Fidelity by touching a file outside this task's declared scope (or
  contorting `UISurfacesHandler._resolve_surface_for_access` into an
  importable module-level function, itself an undeclared change to
  TASK-2702's file), I reimplemented the SAME 4-branch rule set (owner
  match → 200; token resolves + matches → claim + 200; unmatched/missing
  token → 404; bad token → 410) as a small standalone function in
  `a2ui.py` (`_resolve_ui_surface_access`), taking a `store` and returning
  `(record, None)` / `(None, (message, status))` so each handler builds its
  own response with its own `json_response` helper. The AC's actual
  "no duplication" test is scoped to negotiation only ("assert the service
  is called — no duplicated negotiation code in a2ui.py"), which IS
  satisfied literally (verified by `test_mirror_route_delegates_to_shared_service`
  monkeypatching `SurfaceNegotiationService.negotiate`/`respond` and
  asserting both were called). Flagging this tension for the spec/task
  author: either add `ui_surfaces.py` to a future task's Files table to
  truly share the helper, or accept the small, rules-mirrored duplication
  as intentional given the file-scope boundary.
