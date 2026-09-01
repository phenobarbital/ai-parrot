# TASK-2705: End-to-end integration tests for the ui_surfaces plane

**Feature**: FEAT-492 — A2UI Surface Rehydration
**Spec**: `sdd/specs/a2ui-surface-rehydration.spec.md`
**Status**: pending
**Priority**: medium
**Estimated effort**: M (2-4h)
**Depends-on**: TASK-2702, TASK-2703, TASK-2704
**Assigned-to**: unassigned

---

## Context

Spec §3 Module 6 / §4 Integration Tests. Everything is unit-tested per task;
this task proves the seams: publish → bookmark GET (JSON and HTML) from a
fresh session, the refresh flow updating in place, the share lifecycle, and
route registration/ordering after `BotManager.setup_app()`.

---

## Scope

- Implement `packages/ai-parrot-server/tests/integration/test_ui_surfaces_e2e.py`
  covering exactly the spec §4 integration table:
  - `test_e2e_publish_get_json_get_html` — publish via the mixin (store
    real/fixture-backed, renderer real if importable else skip-marked HTML
    leg) → GET JSON envelope matches → GET HTML contains `<html` and an
    ECharts `<script>` for a chart surface.
  - `test_e2e_pin_then_bookmark_new_session` — POST pin → GET with a fresh
    authenticated client context (same owner) → 200 + envelope.
  - `test_e2e_refresh_flow` — recipe-backed surface → refresh with a param
    override (stub RecipeRunner returning a refreshed
    `metadata["source_envelope"]`) → GET shows refreshed dataModel and
    advanced `updated_at`.
  - `test_e2e_share_lifecycle` — mint → GET with token (200, claim recorded,
    appears in the bearer's shared-with-me list) → refresh with token (200,
    owner pctx asserted) → revoke → GET 410.
  - `test_integration_routes_registered` — after `BotManager.setup_app()`,
    all eight routes resolve; `/a2ui/surfaces/{id}` and `/a2ui/capabilities`
    match before the bare `{agent_id}/a2ui` pattern.
- Follow the environment conventions of the existing FEAT-469 e2e suite
  (`tests/integration/test_a2ui_e2e.py`) — reuse its fixtures/skips for
  DB-less CI where applicable.

**NOT in scope**: new implementation code; fixing defects found (file them
in the Completion Note; fixes are follow-up commits within this feature's
worktree).

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot-server/tests/integration/test_ui_surfaces_e2e.py` | CREATE | E2E suite |

---

## Codebase Contract (Anti-Hallucination)

> Verified 2026-09-01 against `dev`.

### Verified Imports
```python
# The FEAT-469 e2e suite to mirror (fixtures, app bootstrap, skip markers):
#   packages/ai-parrot-server/tests/integration/test_a2ui_e2e.py   (exists — verified)
# Feature modules (verify all landed):
from parrot.handlers.ui_surfaces import UISurfacesHandler, SurfaceNegotiationService   # TASK-2702
from parrot.handlers.models.ui_surfaces import PgUISurfaceStore, UISurfaceRecord       # TASK-2700
from parrot.outputs.a2ui.models import CreateSurface                                   # models.py:446
```

### Existing Signatures to Use
```python
# Spec §4 fixtures (reproduce):
@pytest.fixture
def sample_envelope() -> dict:
    """Minimal valid CreateSurface dump — surfaceId + one chart component +
    dataModel {"filters": {"window": "all", "plan": "All"}}."""

@pytest.fixture
def mock_recipe_runner(monkeypatch):
    """RecipeRunner.run stub returning a RenderedArtifact whose
    metadata['source_envelope'] carries a refreshed envelope dump."""
```

### Does NOT Exist
- ~~`artifacts/a2ui_live/` test fixtures~~ — do not reference (known phantom
  path; the real example artifacts live in `artifacts/a2ui_deterministic_refresh/`)
- ~~a public surfaces endpoint without auth~~ — every route is authenticated
  or share-token gated
- ~~HTML pre-baked column~~ — HTML is rendered on the fly; assert content,
  not storage

---

## Implementation Notes

### Key Constraints
- Test isolation: unique surface ids per test; clean up rows created against
  a real test DB (or run the store against a fixture/ephemeral schema).
- The HTML leg requires ai-parrot-visualizations — mark with
  `pytest.importorskip("parrot.outputs.a2ui_renderers.interactive_html")`
  style so DB-less/renderer-less CI degrades to skip, not fail.
- Assert the shared-service property indirectly in the mirror-route test:
  identical body for identical Accept across both routes.

### References in Codebase
- `packages/ai-parrot-server/tests/integration/test_a2ui_e2e.py` — suite style
- `packages/ai-parrot/tests/handlers/test_infographic_handler.py` — TestClient idiom

---

## Acceptance Criteria

- [ ] All five integration tests implemented and passing:
      `pytest packages/ai-parrot-server/tests/integration/test_ui_surfaces_e2e.py -v`
- [ ] Suite passes (or cleanly skips renderer/DB legs) in a DB-less environment
- [ ] Full feature test sweep green:
      `pytest packages/ai-parrot-server/tests/handlers/test_ui_surfaces_store.py packages/ai-parrot-server/tests/handlers/test_ui_surfaces_handler.py packages/ai-parrot-server/tests/handlers/test_a2ui_surfaces_route.py packages/ai-parrot/tests/tools/test_recipe_runner_envelope.py -v`
- [ ] No linting errors on the test file

---

## Test Specification

```python
# packages/ai-parrot-server/tests/integration/test_ui_surfaces_e2e.py
async def test_e2e_publish_get_json_get_html(): ...
async def test_e2e_pin_then_bookmark_new_session(): ...
async def test_e2e_refresh_flow(): ...
async def test_e2e_share_lifecycle(): ...
async def test_integration_routes_registered(): ...
```

---

## Agent Instructions

1. **Read the spec** (§4, §5 Acceptance Criteria — this task closes most of them).
2. **Check dependencies** — TASK-2702, TASK-2703, TASK-2704 in `sdd/tasks/completed/`.
3. **Verify the Codebase Contract** — all feature imports must resolve.
4. **Update status** in `sdd/tasks/index/a2ui-surface-rehydration.json` → `"in-progress"`.
5. **Implement**, **verify**, **move to completed**, update index, fill Completion Note.

---

## Completion Note

*(Agent fills this in when done)*

**Completed by**:
**Date**:
**Notes**:

**Deviations from spec**:
