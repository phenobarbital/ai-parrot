# TASK-3791: End-to-end linked surface — tool → validate → bake → persist → refresh; no-snapshot persist roundtrip

**Feature**: FEAT-598 — A2UI Linked Surfaces
**Spec**: `sdd/specs/a2ui-linked-surfaces.spec.md`
**Status**: pending
**Priority**: medium
**Estimated effort**: M (2-4h)
**Depends-on**: TASK-3785, TASK-3787, TASK-3788
**Assigned-to**: unassigned

---

## Context

Spec §4 Integration Tests require two cross-package end-to-end tests that no single module task can own:

- `test_linked_surface_end_to_end` — the agent tool (`qs_build_linked_surface`, TASK-3785, fake QuerySource) → envelope →
  `validate_envelope` → `bake_envelope` (the snapshot makes every binding resolvable) → persisted through the real
  `publish_surface` (TASK-3788) → `POST …/refresh` through the real `UISurfacesHandler._refresh` descriptor path (TASK-3787)
  → updated `snapshot_at`.
- `test_linked_surface_no_snapshot_persist_roundtrip` — a `snapshot=False` envelope is published → the save path
  executes once and persists the snapshot (AC8/AC16) → `GET ?format=html` renders **without executing** (AC8).

They live in `ai-parrot-server` because the handler, store and HTML renderer do; the only fakes are the external
boundaries (Postgres connection, QuerySource `QS`/`MultiQS`, an allow-all data-plane guard) — same philosophy as
`tests/integration/test_ui_surfaces_e2e.py` (FEAT-492).

---

## Scope

- Create `packages/ai-parrot-server/tests/integration/test_linked_surfaces_e2e.py` with the two tests above plus a
  refresh-conflict (409, AC15) and a fail-closed (no guard → 403, AC14) end-to-end case.
- Duplicate (do not cross-import) the in-memory Postgres harness from `test_ui_surfaces_e2e.py` (suite convention),
  extended for the conditional `update_envelope(..., expected_updated_at=)` SQL TASK-3786 introduced.

**NOT in scope**: any production-code change — a failing assertion is a defect in the owning task's layer and is
recorded in the Completion Note, never weakened to pass; UI (vitest) lanes; live QuerySource / Postgres.

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot-server/tests/integration/test_linked_surfaces_e2e.py` | CREATE | end-to-end linked-surface tests |

---

## Codebase Contract (Anti-Hallucination)

### Verified Imports
```python
from parrot.bots.mixins import InfographicAuthoringMixin                      # test_ui_surfaces_e2e.py:32
from parrot.handlers.models import ui_surfaces as store_module                # test_ui_surfaces_e2e.py:35
from parrot.handlers.models.ui_surfaces import PgUISurfaceStore               # test_ui_surfaces_e2e.py:36
from parrot.handlers.ui_surfaces import UISurfacesHandler                     # test_ui_surfaces_e2e.py:37
from parrot.handlers.ui_surfaces_scope import SurfaceScope                    # test_ui_surfaces_e2e.py:38
from parrot.outputs.a2ui.baking import bake_envelope                          # baking.py:356
from parrot.outputs.a2ui.catalog import ProducerOrigin, validate_envelope     # catalog/__init__.py:499
from parrot.outputs.a2ui.models import CreateSurface                          # models.py:446
from parrot_tools.querysource.toolkit import QuerysourceToolkit               # toolkit.py:58
from parrot_tools.querysource import _qs                                      # _qs.py (QueryModel slot for the catalog fake)
# FEAT-598 net-new, fixed paths:
from parrot.outputs.a2ui.linked import has_data_sources                       # TASK-3769
from parrot.outputs.a2ui.linked.service import LinkedSurfaceService           # TASK-3781
# core executor seam patched by the tests (TASK-3779): parrot.tools.dataset_manager.sources.query_slug._get_qs / _get_multiqs
```

### Existing Signatures to Use
```python
# packages/ai-parrot-server/tests/integration/test_ui_surfaces_e2e.py — harness to DUPLICATE (not import):
class _FakeConnCtx          # L50
def _row_from_insert_args   # L61
class _FakeConn             # L110 (SQL-string dispatch over state.surfaces)
class _FakeAsyncDB          # L251
@pytest.fixture fake_state  # L259 ; @pytest.fixture store L264 (PgUISurfaceStore + monkeypatched _get_db)
class _FakeRequest          # L276 (app, match_info, path, json_body, user_id, query, headers)
def _handler(app, **kw)     # L292 (UISurfacesHandler.__new__ + h._request)
def _unwrap / _get / _post  # L299-311
class _StubResolver         # L325 — app["ui_surfaces_scope_resolver"]
class _MiniBot(InfographicAuthoringMixin)  # L387 — real publish_surface bound call
# app dict keys already used: "ui_surfaces_store" (L443), "ui_surfaces_scope_resolver", "recipe_runner"
#   (handlers/ui_surfaces.py:341-343 `_recipe_runner`). The LinkedSurfaceService / guard wiring key is defined by
#   TASK-3787 in handlers/ui_surfaces.py — READ IT before writing the tests (see FILL IN).
# publish_surface(self, *, kind, title, envelope, recipe_name=None, recipe_owner=None, recipe_params=None,
#   overwrite=False, surface_store=None, user_id=None, session_id=None) -> str   # infographic_authoring.py:440
#   (TASK-3788 adds the LinkedSurfaceService delegation; read its final guard/pctx plumbing before use)
```

### Does NOT Exist
- ~~A live QuerySource or Postgres in CI~~ — fakes only at those boundaries.
- ~~`from ..integration.test_ui_surfaces_e2e import _FakeAsyncDB`~~ — the suite duplicates harnesses by convention.
- ~~`UISurfaceRecord.tenant` driving the executor~~ — each source's tenant comes from the descriptor (AC4).
- ~~A 403 from QuerySource~~ — every QuerySource denial is 404 (`QueryAccessDenied` → 404 `query_not_found`).

---

## Complexity Contract

```json
{
  "schema_version": 1,
  "targets": [
    {"path": "packages/ai-parrot-server/tests/integration/test_linked_surfaces_e2e.py", "action": "CREATE"}
  ],
  "contract_symbols": [
    "sym:packages/ai-parrot-server/src/parrot/handlers/ui_surfaces.py#UISurfacesHandler",
    "sym:packages/ai-parrot-server/src/parrot/handlers/models/ui_surfaces.py#PgUISurfaceStore",
    "sym:packages/ai-parrot/src/parrot/bots/mixins/infographic_authoring.py#InfographicAuthoringMixin.publish_surface",
    "sym:packages/ai-parrot/src/parrot/outputs/a2ui/baking.py#bake_envelope",
    "sym:packages/ai-parrot/src/parrot/outputs/a2ui/catalog/__init__.py#validate_envelope",
    "sym:packages/ai-parrot-tools/src/parrot_tools/querysource/toolkit.py#QuerysourceToolkit"
  ]
}
```

---

## Implementation Notes

### Key Constraints
- `pytestmark = pytest.mark.asyncio` (suite convention).
- Count executions: the fake core `QS` increments a counter on every `query()`; assertions pin
  **1** for the tool, **1** for a no-snapshot save, **0** for any `GET` (JSON and HTML), **1** per refresh.
- The fake guard must record every `(tenant, slug, action)` it is asked about so the test proves the owner's
  `slug:execute` was asserted on save and refresh (AC14/AC18); its interface is whatever TASK-3781's
  `LinkedSurfaceService` calls (read `linked/service.py`).
- HTML leg: `pytest.importorskip("parrot.outputs.a2ui_renderers.interactive_html", …)` exactly like
  `test_ui_surfaces_e2e.py:446-449`.
- The spec's refresh step in `test_linked_surface_end_to_end` is "`_refresh` (fake executor)": use the real
  `_refresh` with the fake core `QS` underneath (the executor itself is real) — the fake sits at QuerySource.

### References in Codebase
- `packages/ai-parrot-server/tests/integration/test_ui_surfaces_e2e.py` — harness + `TestE2E` style.
- `packages/ai-parrot-server/tests/handlers/test_ui_surfaces_linked_store.py` (TASK-3786) — the fake-conn extension for
  the conditional `updated_at` predicate; copy it.

---

## Implementation Blueprint

### Steps (in order)
1. Copy the harness (`test_ui_surfaces_e2e.py:50-340`) and extend `_FakeConn` for the `expected_updated_at`
   predicate — *why*: AC15 needs a store whose conditional update can lose a race.
2. Add fakes: core `QS`/`MultiQS` with an execution counter; allow-all recording guard; catalog `QueryModel` rows —
   *why*: the only external boundaries.
3. Write the four tests — *why*: spec §4 integration rows + AC14/AC15 end-to-end.

### `packages/ai-parrot-server/tests/integration/test_linked_surfaces_e2e.py` (CREATE)
```python
"""FEAT-598 TASK-3791 — end-to-end linked surfaces (spec §4 Integration Tests).

Real components: QuerysourceToolkit.build_linked_surface, validate_envelope, bake_envelope, the real
InfographicAuthoringMixin.publish_surface, PgUISurfaceStore, UISurfacesHandler (_pin_save / _refresh / GET),
LinkedSurfaceService and execute_sources. Fakes ONLY at external boundaries: the Postgres connection (harness
duplicated from test_ui_surfaces_e2e.py by suite convention), QuerySource QS/MultiQS, and a recording
allow-all data-plane guard.
"""

from __future__ import annotations

import json
import logging
from types import SimpleNamespace

import pandas as pd
import pytest

from parrot.bots.mixins import InfographicAuthoringMixin
from parrot.handlers.models.ui_surfaces import PgUISurfaceStore
from parrot.handlers.ui_surfaces import UISurfacesHandler
from parrot.handlers.ui_surfaces_scope import SurfaceScope
from parrot.outputs.a2ui.baking import bake_envelope
from parrot.outputs.a2ui.catalog import ProducerOrigin, validate_envelope
from parrot.outputs.a2ui.models import CreateSurface
from parrot_tools.querysource import _qs
from parrot_tools.querysource.toolkit import QuerysourceToolkit

pytestmark = pytest.mark.asyncio

# FILL IN: paste _FakeConnCtx, _row_from_insert_args, _row_allowed_groups, _row_visible, _FakeConn, _FakeAsyncDB,
# fake_state, store, _FakeRequest, _handler, _unwrap, _get, _post, _decode, _StubResolver, _MiniBot verbatim from
# test_ui_surfaces_e2e.py:50-398; extend _FakeConn's UPDATE branch for the `AND updated_at = $N` predicate exactly as
# TASK-3786's test_ui_surfaces_linked_store.py does — bounded by AC15 (conditional update returns no row on a stale value)


@pytest.fixture
def fake_core_qs(monkeypatch):
    """Patch parrot.tools.dataset_manager.sources.query_slug._get_qs/_get_multiqs; count query() calls."""
    state = SimpleNamespace(executions=0, kwargs=[], frame=pd.DataFrame(
        {"day": pd.date_range("2026-09-01", periods=3, tz="UTC"), "visits": [1, 2, 3], "program": ["epson"] * 3}
    ))
    # FILL IN: FakeQS(**kw) appends kw; async query(output_format=None) → (state.frame.copy(), None) and
    # state.executions += 1; async close(); same for FakeMultiQS; monkeypatch both lazy slots (TASK-3779) — bounded by
    # AC17 (querylimit present in conditions, close awaited)
    raise NotImplementedError


@pytest.fixture
def allow_guard():
    """Recording allow-all guard shaped as LinkedSurfaceService expects (read linked/service.py, TASK-3781)."""
    # FILL IN: object recording (tenant, slug, action) and allowing everything — bounded by AC14/AC18
    raise NotImplementedError


@pytest.fixture
def app(store, allow_guard):
    # FILL IN: {"ui_surfaces_store": store, "ui_surfaces_scope_resolver": _StubResolver(SurfaceScope(...owner...)),
    # "linked_surface_service": LinkedSurfaceService(guard=allow_guard)} — TASK-3787 reads app["linked_surface_service"]
    # (falls back to LinkedSurfaceService(guard=app.get("dataplane_guard"))); TASK-3788 reads bot._linked_surface_service /
    # bot._dataplane_guard — bounded by TASK-3787/TASK-3788's wiring
    raise NotImplementedError


class TestLinkedSurfacesE2E:
    async def test_linked_surface_end_to_end(self, app, store, fake_core_qs, allow_guard, patched_catalog):
        """tool → envelope → validate_envelope → bake_envelope → publish_surface → POST refresh → newer snapshot_at."""
        # FILL IN: tk = QuerysourceToolkit(dsn="postgres://fake"); out = await tk.build_linked_surface(slug, {Chart…},
        # request={"placeholders": {"firstdate": "YESTERDAY", "lastdate": "TODAY"}}); assert executions == 1;
        # env = CreateSurface.model_validate(out["a2ui_envelope"]); validate_envelope(env, origin=TOOL); bake_envelope(env);
        # surface_id = await _MiniBot("reporter").publish_surface(kind="dashboard", title=…, envelope=env,
        # surface_store=store, user_id="owner-1"); record.refreshable is True (AC8); POST …/refresh via _handler(app,
        # match_info={"surface_id": …}, path=".../refresh", json_body={"params": {}}, user_id="owner-1") → 200,
        # executions == 2 (publish reused the tool snapshot) or 3 — pin the value TASK-3788 documents; snapshot_at advanced;
        # allow_guard saw ("slug:execute", slug) with tenant None — bounded by AC8/AC14/AC18
        raise NotImplementedError

    async def test_linked_surface_no_snapshot_persist_roundtrip(self, app, store, fake_core_qs, patched_catalog):
        """snapshot=False → save executes ONCE and persists rows → GET JSON/HTML never executes."""
        # FILL IN: build with snapshot=False (dataModel[key] == {"rows": []}, snapshot_at None); POST /api/v1/ui/surfaces
        # (pin-save body, _post) → 201/200; persisted envelope has rows + snapshot_at; reset counter; GET JSON and
        # GET ?format=html (importorskip the renderer) → executions still 0 — bounded by AC8/AC16
        raise NotImplementedError

    async def test_linked_refresh_conflict_409(self, app, store, fake_core_qs, patched_catalog):
        # FILL IN: publish, then advance the stored row's updated_at behind the handler's back before update_envelope
        # runs (monkeypatch store.update_envelope wrapper or the fake conn) → 409 {"error": "stale refresh",
        # "snapshot_at": <newer>} and the stored snapshot is NOT overwritten — bounded by AC15
        raise NotImplementedError

    async def test_linked_save_without_guard_fails_closed(self, store, fake_core_qs, patched_catalog):
        # FILL IN: app without a guard-configured service → pin-save of a linked envelope answers 403 and nothing
        # is persisted; executions == 0 — bounded by AC14 (LinkedGuardRequired)
        raise NotImplementedError


@pytest.fixture
def patched_catalog(monkeypatch):
    """public.queries fake for the toolkit's SlugCatalog (conftest.py pattern of ai-parrot-tools, duplicated)."""
    # FILL IN: FakeQueryModel.get/filter/all over one epson_field_activity row (query_raw with {firstdate} {lastdate});
    # monkeypatch _qs.QueryModel and parrot_tools.querysource.catalog.AsyncDB with a FakeAsyncDB — bounded by the
    # ai-parrot-tools tests/querysource/conftest.py fakes (L51-107)
    raise NotImplementedError
```

### FILL IN checklist
- [ ] Harness paste + conditional-update extension (AC15).
- [ ] `fake_core_qs`, `allow_guard`, `app`, `patched_catalog` fixtures (read TASK-3781/TASK-3787/TASK-3788 first).
- [ ] Four test bodies with pinned execution counts.

---

## Acceptance Criteria

- [ ] `test_linked_surface_end_to_end` passes: one tool execution, TOOL-valid + bakeable envelope, `refreshable` true,
      refresh updates `snapshot_at` through the descriptor path.
- [ ] `test_linked_surface_no_snapshot_persist_roundtrip` passes: save executes exactly once; `GET` JSON and HTML
      execute zero times (AC8, AC16).
- [ ] Conflict → 409 with the newer `snapshot_at`, nothing overwritten (AC15); no guard → 403, nothing persisted (AC14).
- [ ] No production code modified by this task.

## Validation Commands

- `pytest packages/ai-parrot-server/tests/integration/test_linked_surfaces_e2e.py -q`

---

## Test Specification

See the CREATE block above.

---

## Agent Instructions

When you pick up this task:

1. **Read the spec** at the path listed above for full context
2. **Check dependencies** — verify `Depends-on` tasks are in `tasks/completed/`
3. **Verify the Codebase Contract** — before writing ANY code:
   - Confirm every import in "Verified Imports" still exists (`grep` or `read` the source) — especially the app key
     and guard interface introduced by TASK-3781/TASK-3787/TASK-3788
   - Confirm every class/method in "Existing Signatures" still has the listed attributes
   - If anything has changed, update the contract FIRST, then implement
   - **NEVER** reference an import, attribute, or method not in the contract without verifying it exists
4. **Update status** in the per-spec index → `"in-progress"` with your session ID
5. **Implement** — start from the Implementation Blueprint blocks, complete every
   `# FILL IN:` marker, and never change a signature or path the blueprint fixes
6. **Verify** all acceptance criteria are met
7. **Move this file** to `sdd/tasks/completed/`
8. **Update index** → `"done"`
9. **Fill in the Completion Note** below

---

## Completion Note

*(Agent fills this in when done)*

**Completed by**: <session or agent ID>
**Date**: YYYY-MM-DD
**Notes**: What was implemented, any deviations from scope, issues encountered.

**Deviations from spec**: none | describe if any
