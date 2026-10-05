# F003 — Server lane: `UISurfacesHandler` already hosts BOTH worlds

- **Query**: Q004/Q007 (grep + read)
- **Citations**: `packages/ai-parrot-server/src/parrot/handlers/ui_surfaces.py:346-362,617-734`;
  `packages/ai-parrot-server/src/parrot/manager/manager.py:2420-2423`

- Routes (manager.py:2420-2423): `POST/GET /api/v1/ui/surfaces`,
  `/api/v1/ui/surfaces/{surface_id}`, `/{surface_id}/refresh`, `/{surface_id}/share`.
  There is **no per-source data endpoint** today.
- `UISurfacesHandler` already exposes `_linked_service() -> LinkedSurfaceService`
  (ui_surfaces.py:346) **and** `_recipe_runner() -> RecipeRunner | None`
  (ui_surfaces.py:358) — recipes and linked surfaces converge in this handler.
- `_refresh` (ui_surfaces.py:617) dispatches on `record.recipe_name`:
  - recipe surface → `RecipeRunner.run(recipe_name, params, pctx, recipe_owner,
    include_envelope=True)` — this is the "static/recipe surfaces can aggregate with
    Python transformers" lane the source statement refers to.
  - `recipe_name is None` → `_refresh_linked` (ui_surfaces.py:688) →
    `LinkedSurfaceService.refresh(envelope, params, owner_pctx)` — executes slugs
    server-side and persists snapshots (optimistic concurrency, 409 on stale).
- **Identity**: the server refresh always runs with the **owner's**
  `PermissionContext` (`build_principal_context(record.user_id, channel="ui_surfaces")`,
  ui_surfaces.py:647) — "Share-bearer refresh runs with the OWNER's PermissionContext —
  never the bearer's identity (spec Known Risk)".
- Guard: `LinkedGuardRequired` → 403; `AuthorizationRequired` → 403 (fail closed).
