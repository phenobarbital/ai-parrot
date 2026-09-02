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

**Completed by**: sdd-worker (Claude)
**Date**: 2026-09-01
**Notes**:

All 5 integration tests implemented and passing, wiring REAL feature
components throughout: the actual `InfographicAuthoringMixin.publish_surface`
(called as a genuine bound method on a lightweight `_MiniBot(
InfographicAuthoringMixin)` instance — real `self`, so every mixin
helper including `_lazy_import_ui_surfaces_models` works, just without the
heavy `PandasAgent` composition), the real `PgUISurfaceStore`/
`UISurfaceRecord`, the real `UISurfacesHandler`/`A2UIHandler`/
`SurfaceNegotiationService`. Only the Postgres connection itself is faked
(`_FakeAsyncDB`, byte-for-byte the same harness TASK-2700's own
`test_ui_surfaces_store.py` uses, duplicated here per this feature's
established one-fake-harness-per-file convention) — keeps the suite
DB-less, per spec. `test_e2e_publish_get_json_get_html`'s HTML leg is
guarded with `pytest.importorskip("parrot.outputs.a2ui_renderers
.interactive_html")` so a renderer-less environment degrades to skip, not
fail; in THIS dev venv the renderer is installed so it exercises for real.
`test_integration_routes_registered` asserts BOTH registration order
(`router.resources()` — proves the literal `capabilities`/`surfaces`
segments were registered before the bare `{agent_id}/a2ui` pattern) AND
live resolution (`router.resolve()` for all eight URL shapes, asserting
none is a `MatchInfoError` — aiohttp's "no matching route").

**Defect check (task's own instruction — record found defects here, do NOT
weaken assertions to pass)**: none found. Every assertion in the final
suite reflects actual, correct behavior of TASK-2700–2704's implementation.
One test author mistake was caught and fixed during writing (not a
defect): `test_e2e_pin_then_bookmark_new_session` initially asserted the
POST-returned `surface_id` equals the inline envelope's own `surfaceId`
field — wrong assumption; `UISurfacesHandler._pin_save` (TASK-2702) always
mints a fresh UUID for the row's primary key regardless of the envelope's
own `surfaceId` (a renderer-scoped identifier, not the store's key) — this
is correct, by-design behavior, not a bug. Fixed the test's assertion, not
the implementation.

Full feature sweep (AC's literal command) needed to run as TWO separate
`pytest` invocations, not one: `packages/ai-parrot-server/tests/...` +
`packages/ai-parrot/tests/tools/test_recipe_runner_envelope.py` together in
a single command hit `_pytest.pathlib.ImportPathMismatchError` on
`tests.conftest` — the two workspace packages both have a
`tests/__init__.py`, so pytest's module-identity resolution collides when
collecting both trees in one process. This is a known, pre-existing
project characteristic (see the `worktree-test-setup-and-jira-shim-gotcha`
memory note: "run the two packages' test trees in SEPARATE pytest
invocations — their conftest module names collide"), not something this
task introduced or could fix within its own scope. Ran as two commands
instead: 51 passed (ai-parrot-server: store + handler + a2ui route + this
e2e suite) + 4 passed (ai-parrot: recipe runner envelope) = 55/55 green.

`ruff check` on the new file: fully clean.

**Deviations from spec**:
- The task file's own Scope text says the HTML leg should show "an ECharts
  `<script>` for a chart surface" — verified against the ACTUAL renderer
  `SurfaceNegotiationService._respond_html` uses (TASK-2702:
  `InteractiveHTMLRenderer`, `packages/ai-parrot-visualizations/.../
  interactive_html.py`): its own module docstring says "vendored Chart.js
  v4... vendored ECharts bundle" — it ships BOTH bundles but its class
  docstring is explicit: "Self-contained interactive HTML renderer
  (vendored Chart.js + vanilla JS)" for the Chart component path this test
  exercises. The task file's "ECharts" phrasing is stale/imprecise (likely
  conflated with the separate `EChartsRenderer` class in `echarts.py`).
  Verified via the renderer's OWN existing tests
  (`ai-parrot-visualizations/tests/outputs/a2ui_renderers/
  test_interactive_html.py`) before writing the assertion — per the
  Cardinal Rule to verify before using anything not in the Codebase
  Contract. Asserts what the renderer actually produces (`<html`, `<script`,
  and the literal word "chart" in the rendered doc) rather than a
  library-specific string that would be false for this renderer.
