# TASK-3787: UISurfacesHandler — save-time snapshot + descriptor refresh through LinkedSurfaceService

**Feature**: FEAT-598 — A2UI Linked Surfaces
**Spec**: `sdd/specs/a2ui-linked-surfaces.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: L (4-8h)
**Depends-on**: TASK-3786, TASK-3781
**Assigned-to**: unassigned

---

## Context

Spec §3 Module 8 (REST half): `POST /api/v1/ui/surfaces` (`_pin_save`) and
`POST /api/v1/ui/surfaces/{id}/refresh` (`_refresh`) are two of the four call sites that must
delegate to `LinkedSurfaceService` (S1). On save, a linked envelope is validated at the
persistence boundary with a fail-closed guard (S2/AC14) and, when it lacks a snapshot, executed
ONCE with the owner's context; a failure persists nothing (AC8). On refresh, the recipe path
keeps precedence; otherwise the descriptor path runs the executor with each source's own tenant
(AC4), the owner's principal (AC18), and persists with optimistic concurrency (S11/AC15).
`GET` (JSON and HTML) never executes (AC8).

---

## Scope

- Add `_linked_service()` accessor on the handler: `app["linked_surface_service"]` if present, else build
  `LinkedSurfaceService(guard=app.get("dataplane_guard"))` once and cache it in the app.
- `_pin_save`: after `CreateSurface.model_validate` (L546) build
  `owner_pctx = build_principal_context(user_id, channel="ui_surfaces")`, call
  `validate_for_persistence` then `ensure_snapshot`; persist the snapshotted dump. Error mapping:
  `LinkedGuardRequired` → 403, `AuthorizationRequired` → 403, `CatalogValidationError` → 422
  (`errors` = its `.issues`), `SnapshotError` → `exc.status` with `{"code": exc.code}`.
- `_refresh`: recipe path unchanged when `record.recipe_name` (and it stays first); otherwise the
  descriptor path via `service.refresh(record.envelope, params=req.params, owner_pctx=…)`; all
  sources failed → `outcome.error_status`; persist with
  `store.update_envelope(..., expected_updated_at=record.updated_at)`; `False` → 409
  `{"status": "error", "error": "stale refresh", "snapshot_at": <newer>}`; partial failures →
  `X-Parrot-Refresh-Warnings` response header (JSON list). The `recipe_runner is None → 500`
  check moves INSIDE the recipe branch (a descriptor refresh needs no runner).
- `GET` lanes untouched.
- Unit tests in the existing `__new__` + fake-request idiom (new file).

**NOT in scope**: `PublishSurfaceTool` / `publish_surface` (TASK-3788); the store change (TASK-3786);
changing `PublishSurfaceRequest` / `RefreshSurfaceRequest`; any new route.

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot-server/src/parrot/handlers/ui_surfaces.py` | MODIFY | `_linked_service`, `_pin_save` boundary + snapshot, `_refresh` descriptor path |
| `packages/ai-parrot-server/tests/handlers/test_ui_surfaces_linked_handler.py` | CREATE | unit tests |

---

## Codebase Contract (Anti-Hallucination)

### Verified Imports
```python
# already imported in handlers/ui_surfaces.py
from parrot.auth.permission import build_principal_context          # L29
from parrot.handlers.models.ui_surfaces import PgUISurfaceStore, SurfaceVisibility, UISurfaceKind, UISurfaceRecord  # L31-36
from parrot.outputs.a2ui.models import CreateSurface                 # L42
from pydantic import BaseModel, Field, ValidationError               # L45
# new imports for this task
import json
from parrot.auth.exceptions import AuthorizationRequired             # auth/exceptions.py:12
from parrot.outputs.a2ui.catalog.base import CatalogValidationError  # catalog/base.py:307 (.issues)
from parrot.outputs.a2ui.linked import has_data_sources              # TASK-3769
from parrot.outputs.a2ui.linked.service import LinkedGuardRequired, LinkedSurfaceService, SnapshotError   # TASK-3781
```

### Existing Signatures to Use
```python
# packages/ai-parrot-server/src/parrot/handlers/ui_surfaces.py
class RefreshSurfaceRequest(BaseModel): params: dict[str, Any]       # L91-95
class SurfaceNegotiationService:                                     # L213; negotiate(request) -> str L221; respond(record, accept) L244
class UISurfacesHandler(BaseView):
    def store(self) -> PgUISurfaceStore                               # L326 (app["ui_surfaces_store"] cache idiom L327-331)
    def _recipe_runner(self) -> RecipeRunner | None                   # L341-343
    def _artifact_store(self)                                         # L345
    async def _user_id(self) -> str | None                            # L348
    def _error(self, message, *, status=400) -> web.Response          # L360 — BaseView.error() status WHITELIST: build 403/409/422/5xx
                                                                      #   with self.json_response(..., status=…) directly (L533-537, L608-613 precedent)
    async def post(self) -> web.Response                              # L385-392 dispatch: /refresh → _refresh, /share, else _pin_save
    async def _pin_save(self) -> web.Response                         # L491
        # envelope = CreateSurface.model_validate(envelope_dict)        L546 (ValidationError → 400 L547-551)
        # record = UISurfaceRecord(..., envelope=envelope.model_dump(by_alias=True, mode="json"), ...,
        #          tenant=scope.tenant,  # server-set, NEVER from the body (spec §2/§6)   L566
        #          ...)  ; surface_id = await self.store.save(record)   L572
    async def _refresh(self) -> web.Response                          # L577
        # record, err = await self._resolve_surface_for_access(...)     L585
        # if not record.refreshable: 409 {"refreshable": False}          L590-597
        # req = RefreshSurfaceRequest.model_validate(...)                L604
        # merged_params = {**record.recipe_params, **req.params}         L606
        # runner None → 500                                              L608-614
        # owner_pctx = build_principal_context(record.user_id, channel="ui_surfaces")   L618
        # runner.run(...) L621-628 ; await self.store.update_envelope(surface_id, envelope_dump, merged_params) L638
        # updated = await self.store.get(surface_id); return await self.negotiation.respond(updated, accept)  L639-641

# PgUISurfaceStore.update_envelope(surface_id, envelope, recipe_params, *, expected_updated_at=None) -> bool   (after TASK-3786)
# UISurfaceRecord.refreshable == recipe_name is not None or has_data_sources(envelope)                       (after TASK-3786)
# LinkedSurfaceService (after TASK-3781):
#   async validate_for_persistence(envelope: CreateSurface, *, owner_pctx) -> None   (no-op for baked envelopes)
#   async ensure_snapshot(envelope: dict, *, owner_pctx) -> dict                      (raises SnapshotError(status, code))
#   async refresh(envelope: dict, *, params, owner_pctx) -> RefreshOutcome(envelope, snapshot_at, warnings, error_status, error_code)
```

### Does NOT Exist
- ~~`app["linked_surface_service"]`, `app["dataplane_guard"]`~~ — `app["linked_surface_service"]` is introduced by this task; `app["dataplane_guard"]` is WRITTEN by TASK-3805 (`setup_dataplane_guard()` on `BotManager.setup` startup, when PBAC initializes) and only READ here — do not add a second writer. When TASK-3805's wiring yields no guard (bare install, no policies), the key is absent and linked saves answer 403 (fail closed, AC14) while baked saves are unaffected; this task's tests keep exercising the guard-absent path with a bare app dict.
- ~~reading `record.tenant` / `scope.tenant` for QuerySource routing~~ — FORBIDDEN (AC4); `record.tenant` is the FEAT-535 auth scope. Tenants come from the descriptor inside the service.
- ~~executor calls in `_get_one` / `_get_list` / HTML rendering~~ — must stay absent (GET never executes).
- ~~`RefreshSurfaceRequest.tenant`, `PublishSurfaceRequest.tenant`~~ — deliberately absent (L85-87); do not add.

---

## Complexity Contract

```json
{
  "schema_version": 1,
  "targets": [
    {"path": "packages/ai-parrot-server/src/parrot/handlers/ui_surfaces.py", "action": "MODIFY"},
    {"path": "packages/ai-parrot-server/tests/handlers/test_ui_surfaces_linked_handler.py", "action": "CREATE"}
  ],
  "contract_symbols": [
    "sym:packages/ai-parrot-server/src/parrot/handlers/ui_surfaces.py#UISurfacesHandler._pin_save",
    "sym:packages/ai-parrot-server/src/parrot/handlers/ui_surfaces.py#UISurfacesHandler._refresh",
    "sym:packages/ai-parrot-server/src/parrot/handlers/ui_surfaces.py#UISurfacesHandler.store",
    "sym:packages/ai-parrot-server/src/parrot/handlers/ui_surfaces.py#RefreshSurfaceRequest",
    "sym:packages/ai-parrot-server/src/parrot/handlers/ui_surfaces.py#SurfaceNegotiationService.respond",
    "sym:packages/ai-parrot/src/parrot/auth/permission.py#build_principal_context"
  ]
}
```

---

## Implementation Notes

### Key Constraints
- **Recipe precedence**: `record.recipe_name` set ⇒ the existing recipe path runs exactly as today (existing `TestRefresh` stays green, AC11).
- **Owner context on every lane (AC18)**: save → the saving user's id; refresh → `record.user_id` (a share bearer refreshes as the OWNER, existing Known Risk comment L616-617).
- **Nothing persists on failure (AC8)**: `store.save` must be unreachable when any service call raised.
- **Concurrency (AC15)**: the descriptor path ALWAYS passes `expected_updated_at=record.updated_at`; the recipe path keeps the unconditional call.
- Status mapping of every QuerySource denial stays **404** (never 403 from QuerySource, never the word "denied"); 403 here only comes from OUR boundary (`LinkedGuardRequired` / `AuthorizationRequired`).
- `BaseView.error()` has a status whitelist — build every non-whitelisted response with `self.json_response(..., status=…)`.

---

## Implementation Blueprint

### Steps (in order)
1. Add imports + `_linked_service()` next to `_recipe_runner()` — *why*: one cached service per app (S1), injectable in tests via `app["linked_surface_service"]`.
2. Insert the boundary + snapshot in `_pin_save` between `model_validate` and `UISurfaceRecord(...)` — *why*: AC14 + AC8; the record must be built from the snapshotted dump.
3. Split `_refresh` after `req` (L604): recipe branch (existing code, runner check moved inside) vs descriptor branch — *why*: a linked surface without a recipe must not 500 on a missing runner.
4. Tests.

### `packages/ai-parrot-server/src/parrot/handlers/ui_surfaces.py` (MODIFY) — accessor
```python
# occurrences: 1 (verified: grep -c '    def _recipe_runner(self) -> RecipeRunner | None:' packages/ai-parrot-server/src/parrot/handlers/ui_surfaces.py)
# BEFORE — insert immediately above `    def _recipe_runner(self) -> RecipeRunner | None:` (verified: ui_surfaces.py:341)
    def _linked_service(self) -> LinkedSurfaceService:
        """The app's LinkedSurfaceService (FEAT-598 S1); built once from ``app["dataplane_guard"]`` when not injected.

        A missing guard is NOT an error here — the service fails closed (403) only for linked envelopes.
        """
        service = self.request.app.get("linked_surface_service")
        if service is None:
            service = LinkedSurfaceService(guard=self.request.app.get("dataplane_guard"))
            self.request.app["linked_surface_service"] = service
        return service
```

### `ui_surfaces.py` (MODIFY) — `_pin_save` boundary
```python
# occurrences: 1 (verified: grep -c '            envelope = CreateSurface.model_validate(envelope_dict)' ui_surfaces.py)
# AFTER — insert below the `except ValidationError` block that follows
#   `            envelope = CreateSurface.model_validate(envelope_dict)` (verified: ui_surfaces.py:546-551),
#   i.e. immediately before `        now = datetime.now(UTC)` (L553)
        owner_pctx = build_principal_context(user_id, channel="ui_surfaces")
        envelope_dump = envelope.model_dump(by_alias=True, mode="json")
        if has_data_sources(envelope):
            service = self._linked_service()
            try:
                await service.validate_for_persistence(envelope, owner_pctx=owner_pctx)
                envelope_dump = await service.ensure_snapshot(envelope_dump, owner_pctx=owner_pctx)
            except LinkedGuardRequired:
                return self.json_response(
                    {"status": "error", "message": "Linked surfaces require a configured data-plane guard"}, status=403
                )
            except AuthorizationRequired:
                return self.json_response({"status": "error", "message": "Data source not permitted"}, status=403)
            except CatalogValidationError as exc:
                return self.json_response(
                    {"status": "error", "message": "Invalid linked envelope", "errors": exc.issues}, status=422
                )
            except SnapshotError as exc:
                return self.json_response(
                    {"status": "error", "message": "Data source unavailable", "code": exc.code}, status=exc.status
                )
# THEN in the UISurfaceRecord(...) call replace
#   `            envelope=envelope.model_dump(by_alias=True, mode="json"),`
# with
#   `            envelope=envelope_dump,`
```
**Why**: baked envelopes skip the service entirely (identical to today, AC11); the record is built from the snapshotted dump so a persisted linked surface always carries rows + `snapshot_at` (AC16). The tenant anchor (`tenant=scope.tenant` L566) stays untouched — it is the auth scope, not a QuerySource schema.

### `ui_surfaces.py` (MODIFY) — `_refresh` descriptor path
```python
# occurrences: 1 (verified: grep -c 'owner_pctx = build_principal_context(' ui_surfaces.py)
# RESTRUCTURE ui_surfaces.py:604-641 (from `        req = RefreshSurfaceRequest.model_validate(` through the final
#   `return await self.negotiation.respond(updated, accept)`) into:
        req = RefreshSurfaceRequest.model_validate(body if isinstance(body, dict) else {})
        # Share-bearer refresh runs with the OWNER's PermissionContext — never the bearer's identity (spec Known Risk).
        owner_pctx = build_principal_context(record.user_id, channel="ui_surfaces")
        if record.recipe_name is None:
            return await self._refresh_linked(surface_id, record, req, owner_pctx)
        merged_params = {**record.recipe_params, **req.params}
        runner = self._recipe_runner()
        # ... existing runner-None 500 check, runner.run(...) try/except, envelope_dump check,
        #     update_envelope(surface_id, envelope_dump, merged_params), store.get, negotiation.respond — UNCHANGED ...

    async def _refresh_linked(self, surface_id: str, record: UISurfaceRecord, req: RefreshSurfaceRequest,
                              owner_pctx: Any) -> web.Response:
        """Descriptor refresh (FEAT-598 M8): executor per source tenant, owner principal, conditional persist (S11)."""
        service = self._linked_service()
        try:
            outcome = await service.refresh(record.envelope, params=req.params, owner_pctx=owner_pctx)
        except LinkedGuardRequired:
            return self.json_response({"status": "error", "message": "Linked surfaces require a data-plane guard"}, status=403)
        except AuthorizationRequired:
            return self.json_response({"status": "error", "message": "Data source not permitted"}, status=403)
        if outcome.error_status is not None:
            return self.json_response(
                {"status": "error", "message": "Data source unavailable", "code": outcome.error_code},
                status=outcome.error_status,
            )
        ok = await self.store.update_envelope(
            surface_id, outcome.envelope, record.recipe_params, expected_updated_at=record.updated_at
        )
        if not ok:
            newer = await self.store.get(surface_id)
            # FILL IN: newer snapshot_at = max snapshot_at across newer.envelope's parrot_data_sources (None when
            #          newer is None) — bounded by S11 409 body {"status":"error","error":"stale refresh","snapshot_at":…}.
            return self.json_response({"status": "error", "error": "stale refresh", "snapshot_at": None}, status=409)
        updated = await self.store.get(surface_id)
        accept = self.negotiation.negotiate(self.request)
        response = await self.negotiation.respond(updated, accept)
        if outcome.warnings:
            response.headers["X-Parrot-Refresh-Warnings"] = json.dumps(outcome.warnings)
        return response
```
**Why**: the recipe path's code moves verbatim below the branch (only the owner_pctx line moves up so both paths share it). The descriptor path never reads `record.tenant` (AC4) and the conditional update makes a lost race visible instead of silently overwriting a newer snapshot (AC15). The `record.refreshable` 409 guard above (L590-597) stays as is — it now also admits linked surfaces (TASK-3786).

### `packages/ai-parrot-server/tests/handlers/test_ui_surfaces_linked_handler.py` (CREATE)
```python
"""FEAT-598 M8 — UISurfacesHandler linked save/refresh (spec §4)."""
from __future__ import annotations

import pytest

pytestmark = pytest.mark.asyncio

# FILL IN: copy the _FakeRequest/_handler/_unwrap/_post/_get/_decode/_make_record/_app helpers from
#          test_ui_surfaces_handler.py:45-171 (do NOT import them — keep that file untouched); fake_store with
#          update_envelope = AsyncMock(return_value=True); app["linked_surface_service"] = a fake service
#          (AsyncMocks for validate_for_persistence / ensure_snapshot / refresh) so no QuerySource runs.
#          Linked envelopes need a valid root component + metadata.extensions.parrot_data_sources.


async def test_save_without_snapshot_executes_once(): ...     # FILL IN: ensure_snapshot awaited once; saved envelope == its return
async def test_save_failure_persists_nothing(): ...           # FILL IN: SnapshotError(404/502) → status; store.save not awaited
async def test_save_guard_missing_403(): ...                  # FILL IN: real LinkedSurfaceService(guard=None) → 403, no save
async def test_save_invalid_linked_envelope_422(): ...        # FILL IN: CatalogValidationError → 422 with errors
async def test_save_baked_envelope_skips_service(): ...       # FILL IN: no sources → service untouched, 201
async def test_refresh_descriptor_path(): ...                 # FILL IN: no recipe → service.refresh(owner ctx); update_envelope(expected_updated_at=record.updated_at)
async def test_refresh_recipe_precedence(): ...               # FILL IN: recipe + sources → runner.run called, service.refresh not
async def test_refresh_conflict_409(): ...                    # FILL IN: update_envelope → False → 409 "stale refresh" + newer snapshot_at
async def test_refresh_all_sources_failed_status(): ...       # FILL IN: error_status 503 → 503
async def test_refresh_linked_needs_no_runner(): ...          # FILL IN: no recipe_runner in app → still 200
async def test_get_never_executes(): ...                      # FILL IN: GET JSON and ?format=html → service/executor never called
```

### FILL IN checklist
- [ ] `_refresh_linked` — newer `snapshot_at` in the 409 body; bounded by S11.
- [ ] Move the existing recipe-path code verbatim below the branch (only `owner_pctx` hoisted).
- [ ] tests — helpers copied + every body; bounded by spec §4 M8 rows.

---

## Acceptance Criteria

- [ ] Linked save without snapshot executes once in owner context and persists the snapshot; failure → 404/503/502 and nothing persisted (AC8).
- [ ] Linked save without a guard → 403; owner denied → 403; invalid linked envelope → 422 (AC14).
- [ ] Refresh: recipe wins when both exist; descriptor path runs `service.refresh` with the owner's context (AC8, AC18).
- [ ] Refresh persists with `expected_updated_at`; lost race → 409 with the newer `snapshot_at` (AC15).
- [ ] `GET` JSON/HTML never executes (AC8).
- [ ] Existing `test_ui_surfaces_handler.py` stays green (AC11).

---

## Validation Commands

- `pytest packages/ai-parrot-server/tests/handlers/test_ui_surfaces_linked_handler.py -q`
- `pytest packages/ai-parrot-server/tests/handlers/test_ui_surfaces_handler.py -q`

---

## Test Specification

See the CREATE test block (spec §4: `test_refresh_descriptor_path`, `test_refresh_recipe_precedence`,
`test_save_without_snapshot_executes_once`, `test_save_failure_persists_nothing`, `test_get_never_executes`,
`test_refresh_conflict_409`).

---

## Agent Instructions

1. Read spec §3 Module 8, AC8/AC14/AC15/AC18, §7 Known Risks.
2. Check TASK-3781 and TASK-3786 are done.
3. Verify the Codebase Contract (line numbers of `_pin_save` / `_refresh` may shift slightly — re-grep).
4. Index → `"in-progress"`; implement; complete every `# FILL IN:`.
5. Run the Validation Commands (worktree: `PYTHONPATH=packages/ai-parrot/src:packages/ai-parrot-server/src`).
6. Move to `sdd/tasks/completed/`, index → `"done"`, Completion Note.

---

## Completion Note

*(Agent fills this in when done)*

**Completed by**:
**Date**:
**Notes**:

**Deviations from spec**: none | describe if any
