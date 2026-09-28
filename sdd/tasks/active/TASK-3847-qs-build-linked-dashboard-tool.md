# TASK-3847: qs_build_linked_dashboard tool

**Feature**: FEAT-610 — A2UI Linked Surfaces E2E example
**Spec**: `sdd/specs/a2ui-linked-e2e-test.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: L (4-8h)
**Depends-on**: TASK-3846, TASK-3841
**Assigned-to**: unassigned

---

## Context

Spec §2 Overview + §3 Module 2 (FEAT-610), design research S1, S3, S8. One call must emit ONE TOOL-origin
`createSurface` for all 8 widgets; descriptors are legal only on TOOL output (`DATA_SOURCES_NOT_ALLOWED_FOR_LLM`).

---

## Scope

- `build_linked_dashboard(self, widgets, surface_id=None, title=None, snapshot=True) -> dict[str, Any]` (tool
  `qs_build_linked_dashboard`, generated from the public method name).
- Rules: keys unique and JSON-pointer-safe (`^[A-Za-z_][A-Za-z0-9_]*$`) else `InvalidConditionsError`; component type
  in {Chart, DataTable, KPICard}; a KPICard must name `component.value` as a column string (S3); one
  `_build_linked_source` per widget; ONE `execute_sources` call; any failed outcome → `QuerysourceToolkitError`
  naming the key and error; bind with `_bind_component(comp, key)` then force `id = key`.
- `_dashboard_layout(components, widgets, title)` static: root `Column` (id `root`, children = [kpis row?, charts row?,
  *table ids], optional title `Text`), `Row` ids `row_kpis` / `row_charts`, empty rows omitted, every widget reachable
  from `root` (S1). Section inference when `widget.section is None`: KPICard→kpis, Chart→charts, DataTable→table.
- One `builders.build_linked_surface` call; return `{"a2ui_envelope": ..., "artifacts": [{"type": "a2ui_linked_surface",
  "surface_id", "sources": [keys]}]}`.
- Update the pinned tool lists in `test_toolkit_core.py:18,28`; new `test_build_linked_dashboard_tool.py`.

**NOT in scope**: example `WIDGETS` (TASK-3848); docs (TASK-3853).

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot-tools/src/parrot_tools/querysource/toolkit.py` | MODIFY | new tool + layout helper |
| `packages/ai-parrot-tools/tests/querysource/test_toolkit_core.py` | MODIFY | tool lists |
| `packages/ai-parrot-tools/tests/querysource/test_build_linked_dashboard_tool.py` | CREATE | unit tests |

---

## Codebase Contract (Anti-Hallucination)

> Verified against `f20d82332` (dev, 2026-09-29). Re-check line numbers before editing — earlier tasks in this
> feature may have shifted them.

### Verified Imports
```python
from parrot.outputs.a2ui.builders import build_linked_surface          # builders.py:514 (import lazily as _build, like toolkit.py:361)
from parrot.outputs.a2ui.linked.executor import execute_sources        # executor.py:180
from parrot_tools.querysource.errors import InvalidConditionsError     # already imported in toolkit.py (used at :455)
from parrot_tools.querysource.models import DashboardWidget            # TASK-3846
# validate_envelope + origin enum: FILL IN — grep `def validate_envelope` under packages/ai-parrot/src/parrot/outputs/a2ui/ and use its real import for the AC1 test
```
### Existing Signatures to Use
```python
def build_linked_surface(components, sources, frames, *, surface_id: str, snapshot: bool = True, max_snapshot_rows: int = 500,
    catalog_id: str = DEFAULT_CATALOG_ID) -> CreateSurface                  # builders.py:514
async def execute_sources(sources, *, param_overrides=None, pctx=None, guard=None, max_snapshot_rows=None,
    max_fetch_rows: int = 5000) -> ExecutionOutcome                         # executor.py:180 — .outcomes[key].error, .frames[key]
    async def describe_slug(self, slug: str, dry_run: bool = False, tenant: str | None = None) -> SlugDetail  # toolkit.py:210
    def _build_linked_source(self, widget, detail, *, transform=None) -> LinkedDataSource   # TASK-3846, above _linked_params
    @staticmethod
    def _bind_component(component: dict[str, Any], key: str) -> dict[str, Any]   # toolkit.py:442 (setdefault id "root")
# Layout: Row/Column in catalog/basic/layout.py:24,39 — children is a list of component ids.
# test fixtures: `patched_qs` (conftest.py), `fake_core_qs` pattern in test_build_linked_surface_tool.py:16-40
```
### Does NOT Exist
- ~~`qs_build_linked_dashboard`~~ — created here. ~~A `Grid` container~~ — use Row/Column.
- ~~Implicit KPI first column~~ — the KPICard must name its column (S3).

---

## Complexity Contract

```json
{
  "schema_version": 1,
  "targets": [
    {
      "path": "packages/ai-parrot-tools/src/parrot_tools/querysource/toolkit.py",
      "action": "MODIFY"
    },
    {
      "path": "packages/ai-parrot-tools/tests/querysource/test_toolkit_core.py",
      "action": "MODIFY"
    },
    {
      "path": "packages/ai-parrot-tools/tests/querysource/test_build_linked_dashboard_tool.py",
      "action": "CREATE"
    }
  ],
  "contract_symbols": [
    "sym:packages/ai-parrot-tools/src/parrot_tools/querysource/toolkit.py#QuerysourceToolkit._bind_component",
    "sym:packages/ai-parrot-tools/src/parrot_tools/querysource/toolkit.py#QuerysourceToolkit.describe_slug"
  ]
}
```

---

## Implementation Notes

- Parallelism: depends on TASK-3846 (uses DashboardWidget + _build_linked_source, toolkit.py) and TASK-3841 (both modify test_toolkit_core.py; @> KPIs need JSONB validation).
- Production data: any live query uses `ENV=prod`, read-only. Never commit tokens, passwords or DSNs.
- Worktree tests: prefix with `PYTHONPATH=packages/ai-parrot/src:packages/ai-parrot-tools/src:packages/ai-parrot-visualizations/src:packages/ai-parrot-server/src`
  as needed; never `uv sync` inside a worktree.

---

## Implementation Blueprint

**Steps (in order)**
1. Insert `build_linked_dashboard` + `_dashboard_layout` directly BEFORE `_build_linked_source` (which TASK-3846 put
   above `def _linked_params`, toolkit.py:415 pre-change) — keeps the linked tools together.
2. Validate every widget before any describe/execute — because a bad key must fail without touching QuerySource.
3. Execute once, build once. 4. Tests; update pinned tool lists.

```python
# packages/ai-parrot-tools/src/parrot_tools/querysource/toolkit.py — BEFORE `    def _build_linked_source(` (occurrences: 1 after TASK-3846 — verify with grep -c)
    async def build_linked_dashboard(
        self,
        widgets: list[dict[str, Any]],
        surface_id: str | None = None,
        title: str | None = None,
        snapshot: bool = True,
    ) -> dict[str, Any]:
        """Emit ONE linked A2UI dashboard surface.

        Each widget ``{key, slug, component, request?, tenant?, section?, refresh?}`` gets its own source, so each
        refreshes independently; KPIs, charts and tables are laid out in rows. Components are Chart, DataTable or
        KPICard without bindings; a KPICard names its aggregate column in ``value``. Raises InvalidConditionsError on
        bad/duplicate keys or grammar; QuerysourceToolkitError when a source fails to execute.
        """
        from parrot.outputs.a2ui.builders import build_linked_surface as _build
        from parrot.outputs.a2ui.linked.executor import execute_sources

        parsed = [DashboardWidget.model_validate(w) for w in widgets]
        # FILL IN: key rules (unique, regex-safe), component-type rule, KPICard `value` must be a str — raise
        #   InvalidConditionsError naming the key — bounded by S3 and spec §3 M2.
        sources = {}
        for widget in parsed:
            detail = await self.describe_slug(widget.slug, tenant=widget.tenant)
            sources[widget.key] = self._build_linked_source(widget, detail)
        self.logger.info("qs_build_linked_dashboard %d widgets snapshot=%s", len(parsed), snapshot)
        execution = await execute_sources(sources, pctx=None, guard=None)
        # FILL IN: any outcome.error → QuerysourceToolkitError(f"source '{key}' failed ...: {error}")
        components = [{**self._bind_component(w.component, w.key), "id": w.key} for w in parsed]
        layout = self._dashboard_layout(components, parsed, title)
        envelope = _build(layout, sources, {k: execution.frames[k] for k in sources},
                          surface_id=surface_id or "linked-dashboard", snapshot=snapshot)
        return {
            "a2ui_envelope": envelope.model_dump(mode="json", by_alias=True, exclude_none=True),
            "artifacts": [{"type": "a2ui_linked_surface", "surface_id": envelope.surface_id, "sources": list(sources)}],
        }

    @staticmethod
    def _dashboard_layout(
        components: list[dict[str, Any]], widgets: list[DashboardWidget], title: str | None
    ) -> list[dict[str, Any]]:
        """Return [root Column, Row(kpis)?, Row(charts)?, *components] with ids = widget keys."""
        # FILL IN: section inference (KPICard→kpis, Chart→charts, DataTable→table); build Row dicts
        #   {"id": "row_kpis", "component": "Row", "children": [...]} only when non-empty; optional title Text id
        #   "title"; root {"id": "root", "component": "Column", "children": [...]} — bounded by S1 (all reachable).
        ...
```
**Why**: `_bind_component` defaults id to "root"; overriding with the key keeps ids unique and matches spec §3 M2.

```python
# packages/ai-parrot-tools/tests/querysource/test_toolkit_core.py — lines 18 and 28: insert `"qs_build_linked_dashboard",` BEFORE `"qs_build_linked_surface",`
# occurrences: 2 (verified: grep -c '        "qs_build_linked_surface",' test_toolkit_core.py) — edit BOTH lists (sorted order)
        "qs_build_linked_dashboard",
```
```python
# packages/ai-parrot-tools/tests/querysource/test_build_linked_dashboard_tool.py — CREATE
"""FEAT-610 TASK-3847 — qs_build_linked_dashboard (AC1, AC2, S1, S3, S8)."""

from __future__ import annotations

import pytest

from parrot_tools.querysource.errors import InvalidConditionsError, QuerysourceToolkitError
from parrot_tools.querysource.toolkit import QuerysourceToolkit

# FILL IN: `fake_core_qs`-style fixture (copy test_build_linked_surface_tool.py:16-40) + an 8-widget list shaped like
#   spec §2's query map (4 KPICard, 2 bar Chart, 1 pie Chart, 1 DataTable).

async def test_build_linked_dashboard_one_envelope(...): ...        # 8 sources, one CreateSurface, root/rows/table; validate_envelope(origin=TOOL)
async def test_build_linked_dashboard_reachability(...): ...        # every id reachable from root; every /key binding has a source
async def test_build_linked_dashboard_kpi_bindings(...): ...        # value → {"path": "/<key>/rows/0/<col>"}
async def test_build_linked_dashboard_duplicate_key(...): ...       # duplicate / unsafe key → InvalidConditionsError
async def test_build_linked_dashboard_source_failure(...): ...      # failed source → QuerysourceToolkitError naming key
async def test_build_linked_dashboard_jsonb_kpi(...): ...           # {"@>": [...]} filter builds (AC2)
```
**FILL IN checklist**
- [ ] validation rules; failure mapping; `_dashboard_layout`; the fixture; all six test bodies; `validate_envelope` import.
- [ ] confirm `QuerysourceToolkitError` import path in toolkit.py (it is raised at :392 today).

---

## Acceptance Criteria

- [ ] One TOOL-origin createSurface with 8 components each bound to its own key; `validate_envelope(..., origin=TOOL)` passes (AC1).
- [ ] Pilates `@>` KPIs build through the tool (AC2).
- [ ] Reachability, KPI binding, duplicate-key and failure tests pass; tool lists updated.

---

## Validation Commands

- `pytest packages/ai-parrot-tools/tests/querysource/test_build_linked_dashboard_tool.py -q`
- `pytest packages/ai-parrot-tools/tests/querysource/test_toolkit_core.py -q`
- `pytest packages/ai-parrot-tools/tests/querysource/test_build_linked_surface_tool.py -q`

---

## Test Specification

| Test | Covers |
|---|---|
| six `test_build_linked_dashboard_*` | AC1, AC2, S1, S3, S8 |
| `test_tool_names_and_write_gate` (update) | tool list |

---

## Agent Instructions

1. Verify the Codebase Contract anchors (`grep -c`) before editing; fix stale entries in this file first.
2. Implement exactly the files listed; no refactors outside scope.
3. `ruff check --fix` the touched Python files; run the Validation Commands.
4. Commit code only: `feat(a2ui-linked-e2e-test): TASK-3847 — qs_build_linked_dashboard tool`.
5. Close with `scripts/sdd/close_task.sh TASK-3847 a2ui-linked-e2e-test verified` and fill the Completion Note.

---

## Completion Note

*(Agent fills this in when done)*
