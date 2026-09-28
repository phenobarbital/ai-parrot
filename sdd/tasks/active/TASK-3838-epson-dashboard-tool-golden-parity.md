# TASK-3838: Epson dashboard TOOL, golden envelope and Python↔TS parity harness

**Feature**: FEAT-611 — A2UI Linked Surfaces E2E (parallel track)
**Spec**: `sdd/specs/a2ui-linked-e2e-parallel.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: L (4-8h)
**Depends-on**: TASK-3833, TASK-3834
**Assigned-to**: unassigned

---

## Context

Spec §3 Module 8, scenario S2 (§2), and §9 S4/S6/S10. The core `QuerysourceToolkit.build_linked_surface`
builds one component over one source (toolkit.py:339-413). S2 needs a multi-widget, multi-source surface
with a join, `transform.ops`, a param-driven FilterBar and a local FilterBar. Only
`builders.build_linked_surface` can compose that. This task adds a thin, **example-scoped** TOOL (§9 S10,
so no new core API). The TOOL authorizes every source **before** any row is fetched (§9 S4). It also
adds one shared parity fixture that the Python lane and the TS lane must both satisfy (§9 S6).

Dependencies:
- TASK-3833 fixes TS `deriveConditions` (no `limit`; `_offset` only when truthy) and makes `setParam`
  ignore undeclared names. Without those fixes, `parity.test.ts` cannot pass.
- TASK-3834 adds FilterBar `param` validation (`FILTER_PARAM_UNKNOWN_SOURCE` / `FILTER_PARAM_UNDECLARED`)
  to `_validate_linked_sources`. The TOOL's FilterBar must pass that validation.

---

## Scope

- Implement `build_epson_activity_dashboard(...)` in `examples/agents/a2ui/linked_e2e/dashboard_tool.py`.
  It composes the descriptors, pre-authorizes them, calls `execute_sources`, then calls
  `build_linked_surface`, and returns the toolkit-shaped dict.
- Generate and commit the golden `linked_epson_dashboard.json`. Generate it from the TOOL over the
  parity fixture's input rows, with `snapshot_at` normalized.
- Write the shared parity fixture `epson_dashboard_params.json`. It holds the descriptors, the raw input
  rows per slug, the param cases (declared / undeclared / locked) with expected conditions and ignored
  names, and the expected transformed rows per source.
- Python tests: golden equality + `validate_envelope(TOOL)`; unauthorized guard blocks before any fetch;
  parity (conditions + ignored + rows).
- TS test `parity.test.ts`, which reads the same JSON through `readFileSync`, plus its pytest wrapper.

**NOT in scope**:
- The core toolkit's own pctx/guard behavior (§8 Q4, escalated).
- The FilterBar validation code (TASK-3834).
- The TS drift fixes (TASK-3833).
- The agent, server or runner that call this TOOL (TASK-3839).
- `transform.ref`.

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `examples/agents/a2ui/linked_e2e/dashboard_tool.py` | CREATE | Example TOOL `build_epson_activity_dashboard` |
| `packages/ai-parrot/src/parrot/outputs/a2ui/linked/contract/fixtures/envelopes/linked_epson_dashboard.json` | CREATE | Golden envelope (TOOL output, fixed `snapshot_at`) |
| `packages/ai-parrot/src/parrot/outputs/a2ui/linked/contract/fixtures/parity/epson_dashboard_params.json` | CREATE | Shared Python↔TS parity fixture |
| `packages/ai-parrot/tests/outputs/a2ui/linked/test_epson_dashboard_golden.py` | CREATE | Golden + TOOL validation + unauthorized-blocked tests |
| `packages/ai-parrot/tests/outputs/a2ui/linked/test_epson_dashboard_parity.py` | CREATE | Python side of the parity fixture |
| `packages/ai-parrot-server/ui/src/lib/components/agents/canvas/a2ui/linked/parity.test.ts` | CREATE | TS side of the parity fixture |
| `packages/ai-parrot-server/tests/ui/test_vitest_a2ui_linked_parity.py` | CREATE | pytest wrapper for `parity.test.ts` |

---

## Codebase Contract (Anti-Hallucination)

### Verified Imports
```python
from parrot.outputs.a2ui.builders import build_linked_surface            # builders.py:514
from parrot.outputs.a2ui.linked.models import (                          # models.py
    LinkedDataSource, ParamSpec, SourceRequest, TransformSpec,           # :192, :19, :30, :178
)
from parrot.outputs.a2ui.linked.conditions import derive_conditions       # conditions.py:17
from parrot.outputs.a2ui.linked.executor import execute_sources          # executor.py:180
from parrot.outputs.a2ui.linked import executor as executor_mod          # used by test_service.py:15; _conditions_for at executor.py:153
from parrot.outputs.a2ui.linked.dsl import apply_transform, frame_from_records, frame_to_records  # dsl.py:81, :48, :55
from parrot.outputs.a2ui.catalog import ProducerOrigin, validate_envelope  # catalog/__init__.py (re-export, used by test_contract_envelopes.py:16)
from parrot.outputs.a2ui.models import CreateSurface                     # used by test_contract_envelopes.py:20
from parrot.auth.exceptions import AuthorizationRequired                 # auth/exceptions.py:12
from parrot.auth.permission import build_principal_context              # auth/permission.py:166
from parrot.tools.dataset_manager.sources.resolver import PhysicalResources  # resolver.py:47
import parrot.outputs.a2ui.linked as linked_pkg                          # contract dir = Path(linked_pkg.__file__).parent / "contract"
import parrot.tools.dataset_manager.sources.query_slug as query_slug     # _get_qs :30, _get_multiqs :43 (monkeypatch targets)
```
```ts
import { deriveConditions } from './conditions';                 // conditions.ts:11
import { applyTransform } from './dsl';                          // dsl.ts:32 (rows, spec, frames)
import { createLinkedLane } from './index';                      // index.ts:140 (sources, {baseUrl, headers, transformsBase, onUpdate})
import { readFileSync } from 'node:fs'; import { resolve } from 'node:path';  // pattern: conditions.test.ts:2-7
```

### Existing Signatures to Use
```python
# builders.py:514-523 — builds and validates (TOOL origin) a CreateSurface; raises ValueError when a bound axis
# is missing or non-numeric, or a source has no frame (:540). When a source's snapshot_at is None it stamps
# datetime.now(timezone.utc) (:547), so the golden test MUST normalize snapshot_at.
def build_linked_surface(components, sources, frames, *, surface_id: str, snapshot: bool = True,
                         max_snapshot_rows: int = 500, catalog_id: str = DEFAULT_CATALOG_ID) -> CreateSurface
# _validate_axes (builders.py:477): Chart x must exist and y must be numeric; DataTable columns[].name must exist;
# KPICard value bound as {"path": "/<key>/rows/0/<col>"} → that col must exist (_rows_key :460-474).

# models.py — every model has extra="forbid" and populate_by_name=True (:13)
class LinkedDataSource: kind="query_slug"; slug: str (REQUIRED — no transform-only source exists); tenant; is_multiquery;
    multi_output; conditions (required); request (required); params: dict[str, ParamSpec]; locked: list[str]
    (each must be in params, :218-223); transform; target (JSON pointer); snapshot_at; snapshot_truncated; refresh
class LinkedSources  # key must equal the target root token (:226-235)
# Join JSON: {"op":"join","with":"targets","how":"inner|left","on":[{"left":"program","right":"program"}]} (:159)
# GroupBy {"op":"group_by","by":[...],"aggregate":{col: sum|avg|count|min|max}} (:101) — by=[] is NOT usable (pandas groupby([]) fails)
# Derive {"op":"derive","name":..,"expr": str column | StrictInt | StrictFloat | {"operator":"+|-|*|/","left":..,"right":..}} (:127-141)
# Sort {"op":"sort","by":[{"column":..,"direction":"asc|desc"}]} (:108-117)

# executor.py:153-177 — _conditions_for(src, overrides, *, max_fetch_rows) -> (conditions, ignored)
#   locked and undeclared override names → ignored (sorted); conditions = derive_conditions(...) + {"querylimit": min(limit or cap, cap)}
# executor.py:180-188 — execute_sources(sources, *, param_overrides=None, pctx=None, guard=None, max_snapshot_rows=None,
#   max_fetch_rows=5000) -> ExecutionOutcome. It NEVER raises for data or authorization errors: a denied source
#   becomes SourceOutcome(error=...) (:216-220). outcome.frames = the transformed frames (:221).
#   AuthorizingDataSource fails OPEN when pctx is None (authorizing.py:12, "None → fail-open").

# service.py:87-107 — the pre-authorization pattern to mirror:
#   await guard.authorize_source(pctx, PhysicalResources(source_type="query_slug", source_id=f"{tenant or 'public'}:{slug}"))
#   raises AuthorizationRequired(tool_name=..., message=...) on deny

# toolkit.py:400-413 — the return shape to mirror:
#   {"a2ui_envelope": envelope.model_dump(mode="json", by_alias=True, exclude_none=True),
#    "artifacts": [{"type": "a2ui_linked_surface", "surface_id": ..., "sources": [...], "slug": ..., "tenant": ...}]}

# catalog/__init__.py:517-622 _validate_linked_sources: source.conditions MUST equal
#   derive_conditions(source.request, locked={n: conditions.get(n) for n in locked}) (:599-607) → build conditions with derive_conditions.
# catalog/parrot/filterbar.py:29-71 — filters[] items require column, label, options[{label,value}]; optional multiple;
#   optional param {source, name} (both required, additionalProperties false). No date-range type exists.
# catalog/parrot/kpicard.py:15-53 — component "KPICard" (singular; there is NO "KPICards"), required label + value.
# Row / Column are Basic-catalog layout primitives (catalog/basic/layout.py); linked_dashboard_join.json uses Column.

# test_contract_envelopes.py:22 — ENVELOPES = sorted(glob("fixtures/envelopes/*.json")), and
#   test_envelope_fixture_contract (:139-150) is parametrized over EVERY file there. So adding
#   linked_epson_dashboard.json automatically enrolls it: it must be TOOL-valid, LLM-rejected
#   (DATA_SOURCES_NOT_ALLOWED_FOR_LLM), bakeable (bake_envelope) and schema.json-valid. The explicit
#   regenerable list (:127-136) is NOT auto — this task's own golden test covers regeneration.
# pyproject.toml:983 packages "contract/fixtures/*/*.json", so a new fixtures/parity/ dir ships with no manifest edit.

# FakeQS pattern: packages/ai-parrot-server/tests/integration/test_linked_surfaces_e2e.py:202-233
#   (monkeypatch query_slug._get_qs / _get_multiqs → class FakeQS(**kwargs) with async query(output_format=None) -> (df, None), async close())
#   QuerySlugSource calls qs_cls(slug=self.slug, conditions=merged, **kwargs) (query_slug.py:214), so FakeQS can key frames on kwargs["slug"].
# Guard fake pattern: packages/ai-parrot/tests/outputs/a2ui/linked/test_service.py:23-34 (_FakeGuard with deny set).
```
```ts
// conditions.test.ts:7 / dsl.test.ts:7 — the fixture dir is reached from the UI cwd:
//   resolve(process.cwd(), '../../ai-parrot/src/parrot/outputs/a2ui/linked/contract/fixtures/<dir>')
//   (vitest cwd = packages/ai-parrot-server/ui; readFileSync avoids vite's server.fs import restrictions)
// index.ts:140 createLinkedLane(sources, opts); lane.start() fetches every source on mount (on_mount policy);
//   lane.setParam(source, name, value) re-fetches one source; runSource builds
//   deriveConditions({...request, placeholders: {...placeholders, ...overrides}}, lockedValues(src)) (:172-175).
// fetch.ts:49 body = {...conditions, querylimit: Math.min(src.request.limit ?? cap, cap)}; cap = DEFAULT_MAX_FETCH_ROWS = 5000
// api/querysource.ts:22-35 queryUrl → `${base}/api/v3/queries/${slug}` (no tenant); postQuery → fetch(url, {method:'POST', body: JSON.stringify(body)})
// fetch.test.ts:20 — vi.spyOn(globalThis, 'fetch').mockResolvedValue(new Response(JSON.stringify(rows))) pattern
```
```python
# packages/ai-parrot-server/tests/ui/_vitest.py — run_vitest(*files) skips when pnpm or ui/node_modules is absent
# packages/ai-parrot-server/tests/ui/test_vitest_a2ui_linked_dsl.py — the 10-line wrapper pattern
```

### Does NOT Exist
- ~~A transform-only / derived `LinkedDataSource` without a `slug`~~: `slug` is required (models.py:197). A
  "derived" source (attainment, kpis) is another `query_slug` source over `epson_field_activity` that
  joins the `targets` sibling in its own `transform.ops`. This is the same shape as `linked_dashboard_join.json`.
- ~~A `KPICards` component~~: use three `KPICard` components inside a `Row`.
- ~~A date-range FilterBar filter type~~: each filter is a `ChoicePicker` over `options[]`.
- ~~A distinct-count aggregate~~: the aggregates are only `sum|avg|count|min|max`.
- ~~`group_by` with `by: []`~~: use a constant `derive` key.
- ~~A multi-widget helper in `QuerysourceToolkit`~~ (spec §6 Does NOT Exist).
- ~~`execute_sources` raising on a denied source~~: it swallows the error into `SourceOutcome.error`. The
  TOOL has to pre-authorize the sources itself.
- ~~An `examples` Python package~~: `examples/` has no `__init__.py`. Tests load `dashboard_tool.py` by path
  with `importlib.util.spec_from_file_location` (pattern: `packages/ai-parrot/tests/test_workday_models.py:28`).
- ~~A `contract/fixtures/parity/` directory~~: this task creates it.

---

## Complexity Contract

```json
{
  "schema_version": 1,
  "targets": [
    {"path": "examples/agents/a2ui/linked_e2e/dashboard_tool.py", "action": "CREATE"},
    {"path": "packages/ai-parrot/src/parrot/outputs/a2ui/linked/contract/fixtures/envelopes/linked_epson_dashboard.json", "action": "CREATE"},
    {"path": "packages/ai-parrot/src/parrot/outputs/a2ui/linked/contract/fixtures/parity/epson_dashboard_params.json", "action": "CREATE"},
    {"path": "packages/ai-parrot/tests/outputs/a2ui/linked/test_epson_dashboard_golden.py", "action": "CREATE"},
    {"path": "packages/ai-parrot/tests/outputs/a2ui/linked/test_epson_dashboard_parity.py", "action": "CREATE"},
    {"path": "packages/ai-parrot-server/ui/src/lib/components/agents/canvas/a2ui/linked/parity.test.ts", "action": "CREATE"},
    {"path": "packages/ai-parrot-server/tests/ui/test_vitest_a2ui_linked_parity.py", "action": "CREATE"}
  ],
  "contract_symbols": [
    "sym:packages/ai-parrot/src/parrot/outputs/a2ui/builders.py#build_linked_surface",
    "sym:packages/ai-parrot/src/parrot/outputs/a2ui/linked/models.py#LinkedDataSource",
    "sym:packages/ai-parrot/src/parrot/outputs/a2ui/linked/models.py#ParamSpec",
    "sym:packages/ai-parrot/src/parrot/outputs/a2ui/linked/models.py#SourceRequest",
    "sym:packages/ai-parrot/src/parrot/outputs/a2ui/linked/models.py#TransformSpec",
    "sym:packages/ai-parrot/src/parrot/outputs/a2ui/linked/conditions.py#derive_conditions",
    "sym:packages/ai-parrot/src/parrot/outputs/a2ui/linked/executor.py#execute_sources",
    "sym:packages/ai-parrot/src/parrot/outputs/a2ui/linked/executor.py#_conditions_for",
    "sym:packages/ai-parrot/src/parrot/outputs/a2ui/linked/dsl.py#apply_transform",
    "sym:packages/ai-parrot/src/parrot/outputs/a2ui/linked/dsl.py#frame_from_records",
    "sym:packages/ai-parrot/src/parrot/outputs/a2ui/linked/dsl.py#frame_to_records",
    "sym:packages/ai-parrot/src/parrot/outputs/a2ui/catalog/__init__.py#validate_envelope",
    "sym:packages/ai-parrot/src/parrot/auth/exceptions.py#AuthorizationRequired",
    "sym:packages/ai-parrot/src/parrot/auth/permission.py#build_principal_context",
    "sym:packages/ai-parrot/src/parrot/tools/dataset_manager/sources/resolver.py#PhysicalResources",
    "sym:packages/ai-parrot/src/parrot/tools/dataset_manager/sources/query_slug.py#_get_qs",
    "sym:packages/ai-parrot-server/ui/src/lib/components/agents/canvas/a2ui/linked/conditions.ts#deriveConditions",
    "sym:packages/ai-parrot-server/ui/src/lib/components/agents/canvas/a2ui/linked/dsl.ts#applyTransform",
    "sym:packages/ai-parrot-server/ui/src/lib/components/agents/canvas/a2ui/linked/index.ts#createLinkedLane",
    "sym:packages/ai-parrot-server/tests/ui/_vitest.py#run_vitest"
  ]
}
```

---

## Implementation Notes

### Decided composition (do not renegotiate)
Sources (the key equals the target root):
| key | slug | request.placeholders | params | transform.ops |
|---|---|---|---|---|
| `targets` | `epson_program_targets` | `{}` | `{}` | none |
| `activity` | `epson_field_activity` | `{firstdate, lastdate}` | `firstdate`/`lastdate` = `ParamSpec(type="date", accepts_keywords=True)` | none |
| `attainment` | `epson_field_activity` | same as activity | same | join `targets` (left, on program) → group_by `[program]` `{visits: sum, target: max}` → derive `attainment = (visits*100)/target` → sort `attainment desc` |
| `kpis` | `epson_field_activity` | same | same | group_by `[program, store_id]` `{visits: sum}` → join `targets` (left, on program) → group_by `[program]` `{visits: sum, store_id: count, target: max}` → derive `k = 1` → group_by `[k]` `{visits: sum, store_id: sum, target: sum}` → derive `attainment_pct = (visits*100)/target` |

Components:
- `root` Column with children `[kpi_row, date_filters, program_filter, chart, table]`.
- `kpi_row` Row with children `[kpi_visits, kpi_stores, kpi_attainment]`.
- The three KPICards bind `value` to `/kpis/rows/0/visits`, `/kpis/rows/0/store_id` and `/kpis/rows/0/attainment_pct`.
- `chart` is a Chart, `type: bar`, `x: day`, `y: [visits]`, bound to `/activity/rows`.
- `table` is a DataTable with columns program/visits/target/attainment, bound to `/attainment/rows`.
- `date_filters` is a FilterBar with two filters:
  - "From": column `day`, param `{source: activity, name: firstdate}`, options FDOM, YESTERDAY, and the ISO start of the fixture range.
  - "To": column `day`, param `{source: activity, name: lastdate}`, options TODAY, YESTERDAY.
- `program_filter` is a FilterBar with one local filter: column `program`, no `param`. Its options come
  from `programs`, or, when that is None, from the sorted unique `program` values of the targets frame.

Why this shape:
- A FilterBar filter is a `ChoicePicker`, so a "date range" is two preset pickers.
- A `param` names ONE source. In the browser lane it therefore re-queries only `activity` (the chart).
- The server lane `/refresh {params:{firstdate,lastdate}}` broadcasts flat params to every source
  (service.py:161-171), so there all three activity-backed sources re-query. Record this asymmetry in
  the module docstring.
- The KPI "stores visited" is distinct stores per program, summed across programs. A store active in
  two programs therefore counts twice. The DSL has no distinct count; document this too.
- Compute percentages as `(visits*100)/target`, never `(visits/target)*100`. pandas `to_json` rounds
  floats to 10 significant digits while JS does not, so `0.4*100 = 40.00000000000001` would break parity.
  Choose fixture numbers whose division is exact.

### Key Constraints
- The TOOL is example code (§9 S10). It must not add or modify anything under `packages/`.
- Authorize before fetching (§9 S4):
  - When a `guard` is given, `pctx` must be non-None, because `AuthorizingDataSource` fails open on a
    None pctx. If pctx is None, raise `AuthorizationRequired`.
  - Call `guard.authorize_source` once per unique `(tenant, slug)` BEFORE `execute_sources`.
  - After execution, raise when any outcome has an `error`.
  - With `guard=None`, run unguarded and log a warning. This path is only for offline/golden use.
- Build every `conditions` with `derive_conditions(request, locked={})`, because
  `_validate_linked_sources` compares the two (:599-607).
- The golden must be deterministic: FakeQS frames come from the parity fixture's `input_frames`, and
  every source's `snapshot_at` is overwritten with `"2026-09-25T00:00:00Z"` before comparison and before writing.
- If Python and TS disagree on the parity fixture, do NOT edit the expected values to match one lane.
  Stop and report the drift, because TASK-3833 owns the TS lane.

### References in Codebase
- `packages/ai-parrot/tests/outputs/a2ui/linked/test_contract_envelopes.py:47-99` — descriptor + `_dump` pattern
- `packages/ai-parrot/src/parrot/outputs/a2ui/linked/contract/fixtures/envelopes/linked_dashboard_join.json` — join shape
- `packages/ai-parrot/src/parrot/outputs/a2ui/linked/contract/fixtures/conditions/locked_override.json` — locked semantics

---

## Implementation Blueprint

### Steps (in order)
1. Create `epson_dashboard_params.json` first. The golden test's FakeQS and both parity tests read their
   input rows from it, so this file is the single dataset.
2. Write `dashboard_tool.py` (blocks A and B). It is a pure composition, so nothing else is needed before it.
3. Write `test_epson_dashboard_golden.py`. Run it once with `PARROT_REGEN_GOLDEN=1` to write
   `linked_epson_dashboard.json`, then run it without the flag. The golden must be TOOL output and must never be hand-written.
4. Run `test_contract_envelopes.py`. The new golden is auto-enrolled in `test_envelope_fixture_contract`
   (TOOL-valid, LLM-rejected, bakeable, schema-valid), so a failure there means the golden is wrong.
5. Write `test_epson_dashboard_parity.py`. Python is the reference executor.
6. Write `parity.test.ts` and its wrapper, and run them. TS must match the same fixture byte-for-byte on rows and conditions.

### `examples/agents/a2ui/linked_e2e/dashboard_tool.py` (CREATE) — block A: descriptors
```python
"""S2 example TOOL: Epson activity dashboard over linked sources (FEAT-611 spec §3 M8).

Example-scoped (spec §9 S10): composes descriptors, pre-authorizes them, executes, builds. No core API.
Browser lane: the date FilterBar re-queries only `activity` (a FilterBar param names one source).
Server lane: POST /refresh {params:{firstdate,lastdate}} broadcasts to every activity-backed source.
KPI "stores visited" = distinct stores per program, summed (the DSL has no distinct count).
"""
from __future__ import annotations

import logging
from typing import Any

from parrot.auth.exceptions import AuthorizationRequired
from parrot.outputs.a2ui.builders import build_linked_surface
from parrot.outputs.a2ui.linked.conditions import derive_conditions
from parrot.outputs.a2ui.linked.executor import execute_sources
from parrot.outputs.a2ui.linked.models import LinkedDataSource, ParamSpec, SourceRequest, TransformSpec
from parrot.tools.dataset_manager.sources.resolver import PhysicalResources

logger = logging.getLogger("examples.a2ui.linked_e2e.dashboard_tool")

SURFACE_ID = "linked-epson-dashboard"
ACTIVITY_SLUG = "epson_field_activity"
TARGETS_SLUG = "epson_program_targets"
_JOIN_TARGETS = {"op": "join", "with": "targets", "how": "left", "on": [{"left": "program", "right": "program"}]}
_PCT = {"operator": "/", "left": {"operator": "*", "left": "visits", "right": 100}, "right": "target"}

ATTAINMENT_OPS: list[dict[str, Any]] = [
    _JOIN_TARGETS,
    {"op": "group_by", "by": ["program"], "aggregate": {"visits": "sum", "target": "max"}},
    {"op": "derive", "name": "attainment", "expr": _PCT},
    {"op": "sort", "by": [{"column": "attainment", "direction": "desc"}]},
]
KPI_OPS: list[dict[str, Any]] = [
    {"op": "group_by", "by": ["program", "store_id"], "aggregate": {"visits": "sum"}},
    _JOIN_TARGETS,
    {"op": "group_by", "by": ["program"], "aggregate": {"visits": "sum", "store_id": "count", "target": "max"}},
    {"op": "derive", "name": "k", "expr": 1},
    {"op": "group_by", "by": ["k"], "aggregate": {"visits": "sum", "store_id": "sum", "target": "sum"}},
    {"op": "derive", "name": "attainment_pct", "expr": _PCT},
]


def _date_params() -> dict[str, ParamSpec]:
    return {
        "firstdate": ParamSpec(type="date", accepts_keywords=True),
        "lastdate": ParamSpec(type="date", accepts_keywords=True),
    }


def build_sources(firstdate: str, lastdate: str) -> dict[str, LinkedDataSource]:
    """Return the four descriptors in dependency-friendly insertion order (targets first)."""
    dated = SourceRequest(placeholders={"firstdate": firstdate, "lastdate": lastdate})
    plain = SourceRequest()

    def _src(key: str, slug: str, request: SourceRequest, ops: list | None, params: dict) -> LinkedDataSource:
        return LinkedDataSource(
            slug=slug,
            conditions=derive_conditions(request, locked={}),  # must equal catalog re-derivation (:599-607)
            request=request,
            params=params,
            transform=TransformSpec.model_validate({"ops": ops}) if ops else None,
            target=f"/{key}/rows",
        )

    return {
        "targets": _src("targets", TARGETS_SLUG, plain, None, {}),
        "activity": _src("activity", ACTIVITY_SLUG, dated, None, _date_params()),
        "attainment": _src("attainment", ACTIVITY_SLUG, dated, ATTAINMENT_OPS, _date_params()),
        "kpis": _src("kpis", ACTIVITY_SLUG, dated, KPI_OPS, _date_params()),
    }
```
**Why this shape**: a `slug` is required on every source, so each "derived" source re-reads
`epson_field_activity` and joins its `targets` sibling. The executor's topological order runs `targets`
first (executor.py:97-150). `build_sources` is public so the parity fixture and the tests can rebuild the
exact descriptors without calling the TOOL.

### `examples/agents/a2ui/linked_e2e/dashboard_tool.py` (CREATE) — block B: components + TOOL (append below block A)
```python
def build_components(programs: list[str]) -> list[dict[str, Any]]:
    """Return the S2 component list (ids are stable: the golden compares them)."""
    kpi = lambda cid, label, col: {"id": cid, "component": "KPICard", "label": label,  # noqa: E731
                                   "value": {"path": f"/kpis/rows/0/{col}"}}
    return [
        {"id": "root", "component": "Column",
         "children": ["kpi_row", "date_filters", "program_filter", "chart", "table"]},
        {"id": "kpi_row", "component": "Row", "children": ["kpi_visits", "kpi_stores", "kpi_attainment"]},
        kpi("kpi_visits", "Total visits", "visits"),
        kpi("kpi_stores", "Stores visited", "store_id"),
        kpi("kpi_attainment", "% attainment", "attainment_pct"),
        {"id": "date_filters", "component": "FilterBar", "title": "Date range", "filters": [
            # FILL IN: the "From" filter {column:"day", label:"From", options:[FDOM, YESTERDAY, <fixture ISO start>],
            #   param:{source:"activity", name:"firstdate"}} and the "To" filter (TODAY, YESTERDAY; name:"lastdate")
            #   — bounded by filterbar.py:29-71 (options[{label,value}] required) and TASK-3834's validation
        ]},
        {"id": "program_filter", "component": "FilterBar", "title": "Program", "filters": [
            {"column": "program", "label": "Program", "multiple": True,
             "options": [{"label": p, "value": p} for p in programs]},
        ]},
        {"id": "chart", "component": "Chart", "type": "bar", "x": "day", "y": ["visits"],
         "data": {"path": "/activity/rows"}},
        {"id": "table", "component": "DataTable", "data": {"path": "/attainment/rows"},
         "columns": [{"name": c} for c in ("program", "visits", "target", "attainment")]},
    ]


async def build_epson_activity_dashboard(
    firstdate: str = "FDOM", lastdate: str = "TODAY", programs: list[str] | None = None,
    snapshot: bool = True, *, pctx: Any = None, guard: Any = None,
) -> dict[str, Any]:
    """Compose the S2 linked dashboard; returns {"a2ui_envelope": <inner CreateSurface>, "artifacts": [...]}.

    Raises:
        AuthorizationRequired: guard given without pctx, or the guard denies any (tenant, slug) — before any fetch.
        RuntimeError: any source failed during execution (its stable error code is in the message).
    """
    sources = build_sources(firstdate, lastdate)
    if guard is not None:
        if pctx is None:
            raise AuthorizationRequired(tool_name="build_epson_activity_dashboard",
                                        message="a caller PermissionContext is required when a guard is configured")
        # FILL IN: for each unique (src.tenant, src.slug): await guard.authorize_source(pctx,
        #   PhysicalResources(source_type="query_slug", source_id=f"{tenant or 'public'}:{slug}")) — let
        #   AuthorizationRequired propagate — bounded by §9 S4 and service.py:87-107 (same resource string)
    else:
        logger.warning("build_epson_activity_dashboard: no data-plane guard — unguarded (offline/golden use only)")
    outcome = await execute_sources(sources, pctx=pctx, guard=guard)
    failed = {k: o.error for k, o in outcome.outcomes.items() if o.error is not None}
    if failed:
        raise RuntimeError(f"epson dashboard sources failed: {failed}")
    # FILL IN: when programs is None derive sorted(unique targets frame "program" values) — bounded by
    #   outcome.frames["targets"] (the transformed frame; executor.py:221)
    envelope = build_linked_surface(build_components(programs or []), sources, outcome.frames,
                                    surface_id=SURFACE_ID, snapshot=snapshot)
    logger.info("built %s with sources=%s snapshot=%s", SURFACE_ID, list(sources), snapshot)
    return {
        "a2ui_envelope": envelope.model_dump(mode="json", by_alias=True, exclude_none=True),
        "artifacts": [{"type": "a2ui_linked_surface", "surface_id": envelope.surface_id,
                       "sources": list(sources), "slug": ACTIVITY_SLUG, "tenant": None}],
    }
```
**Why this shape**:
- The return shape copies toolkit.py:400-413 exactly, so TASK-3835's lift (a dict result carrying an
  `a2ui_linked_surface` artifact) covers this TOOL with no special case.
- `pctx` and `guard` are keyword-only, so TASK-3839's agent wrapper can inject them without the LLM seeing them.
- Do not rename `build_sources`, `build_components` or `SURFACE_ID`, because the tests import them.

### `packages/ai-parrot/src/parrot/outputs/a2ui/linked/contract/fixtures/parity/epson_dashboard_params.json` (CREATE)
```json
{
  "description": "FEAT-611 S2 parity: same descriptors + params + input frames => same conditions and rows in Python and TS",
  "max_fetch_rows": 5000,
  "input_frames": {
    "epson_field_activity": "FILL IN: >=6 rows {day:'2026-09-0N' (ISO date STRING), visits:int, program:'epson'|'pokemon', store_id:int}; at least one store in two programs; choose visits/targets so (visits*100)/target is exact",
    "epson_program_targets": "FILL IN: [{program:'epson', target:int}, {program:'pokemon', target:int}]"
  },
  "sources": "FILL IN: {targets, activity, attainment, kpis} = build_sources('2026-09-01','2026-09-07') dumped with model_dump(mode='json', by_alias=True)",
  "locked_source": "FILL IN: one extra descriptor (key 'activity_locked', slug epson_field_activity) with params {firstdate, lastdate, program} and locked ['program'], conditions from derive_conditions(request, locked={'program':'epson'})",
  "param_cases": [
    {"id": "declared", "source": "activity", "overrides": {"firstdate": "2026-09-02"}, "expected_ignored": [],
     "expected_conditions": "FILL IN: {firstdate:'2026-09-02', lastdate:'2026-09-07', querylimit:5000}"},
    {"id": "undeclared", "source": "activity", "overrides": {"store_id": 7}, "expected_ignored": ["store_id"],
     "expected_conditions": "FILL IN: base activity conditions + querylimit (undeclared never reaches the wire)"},
    {"id": "locked", "source": "activity_locked", "overrides": {"program": "pokemon"}, "expected_ignored": ["program"],
     "expected_conditions": "FILL IN: locked program stays 'epson' + querylimit"}
  ],
  "expected_rows": "FILL IN: {targets, activity, attainment, kpis} = frame_to_records(apply_transform(...)) computed by the Python reference and pasted verbatim"
}
```
**Why**:
- Replace every `"FILL IN: ..."` string value with real JSON. No FILL IN string may remain in the committed file.
- The key names are fixed, because both test files read them.
- `expected_rows` comes from the Python reference executor (spec §3 M5). TS must then match it.
- The ISO date strings keep `day` out of the pandas datetime round-trip, so the two lanes cannot differ on date formatting.

### `packages/ai-parrot/tests/outputs/a2ui/linked/test_epson_dashboard_golden.py` (CREATE)
```python
"""FEAT-611 M8 — Epson dashboard TOOL: golden equality, TOOL validation, unauthorized blocked before rows."""
from __future__ import annotations

import importlib.util
import json
import os
from pathlib import Path
from types import SimpleNamespace

import pytest

import parrot.outputs.a2ui.linked as linked_pkg
import parrot.tools.dataset_manager.sources.query_slug as query_slug
from parrot.auth.exceptions import AuthorizationRequired
from parrot.auth.permission import build_principal_context
from parrot.outputs.a2ui.catalog import ProducerOrigin, validate_envelope
from parrot.outputs.a2ui.linked.dsl import frame_from_records
from parrot.outputs.a2ui.models import CreateSurface

pytestmark = pytest.mark.asyncio
REPO = Path(__file__).resolve().parents[6]
TOOL_PATH = REPO / "examples/agents/a2ui/linked_e2e/dashboard_tool.py"
FIXTURES = Path(linked_pkg.__file__).parent / "contract" / "fixtures"
GOLDEN = FIXTURES / "envelopes" / "linked_epson_dashboard.json"
PARITY = json.loads((FIXTURES / "parity" / "epson_dashboard_params.json").read_text())
FIXED_SNAPSHOT_AT = "2026-09-25T00:00:00Z"


def _load_tool():
    spec = importlib.util.spec_from_file_location("_epson_dashboard_tool", TOOL_PATH)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@pytest.fixture
def fake_qs(monkeypatch):
    """Slug-keyed FakeQS (test_linked_surfaces_e2e.py:202-233 pattern) over the parity input frames."""
    state = SimpleNamespace(executions=0, kwargs=[])

    class FakeQS:
        def __init__(self, **kwargs):
            state.kwargs.append(kwargs)
            self._slug = kwargs["slug"]

        async def query(self, output_format=None):
            state.executions += 1
            return frame_from_records(PARITY["input_frames"][self._slug]), None

        async def close(self):
            return None

    monkeypatch.setattr(query_slug, "_get_qs", lambda: FakeQS)
    return state


def _normalized(result: dict) -> dict:
    envelope = json.loads(json.dumps(result["a2ui_envelope"]))
    for source in envelope["metadata"]["extensions"]["parrot_data_sources"].values():
        source["snapshot_at"] = FIXED_SNAPSHOT_AT
    return envelope


def _dump(envelope: dict) -> str:
    return json.dumps(envelope, sort_keys=True, indent=2) + "\n"  # same format as test_contract_envelopes._dump


async def test_epson_dashboard_golden(fake_qs):
    tool = _load_tool()
    result = await tool.build_epson_activity_dashboard("2026-09-01", "2026-09-07")
    actual = _dump(_normalized(result))
    if os.environ.get("PARROT_REGEN_GOLDEN") == "1":
        GOLDEN.write_text(actual)
    assert GOLDEN.read_text() == actual
    validate_envelope(CreateSurface.model_validate(result["a2ui_envelope"]), origin=ProducerOrigin.TOOL)
    assert result["artifacts"][0]["type"] == "a2ui_linked_surface"
    # FILL IN: assert fake_qs.executions == 4 and every kwargs["conditions"]["querylimit"] == 5000 — bounded by executor.py:176


async def test_dashboard_tool_unauthorized_blocked(fake_qs):
    """Guard denies epson_field_activity → AuthorizationRequired, and QS is never executed (§9 S4)."""
    # FILL IN: _FakeGuard(deny={"query_slug:public:epson_field_activity"}) as in test_service.py:23-34;
    #   pctx = build_principal_context("owner-1", channel="ui_surfaces");
    #   with pytest.raises(AuthorizationRequired): await tool.build_epson_activity_dashboard(pctx=pctx, guard=guard)
    #   assert fake_qs.executions == 0 — bounded by §9 S4 (no rows before authorization)


async def test_dashboard_tool_guard_without_pctx_fails_closed(fake_qs):
    # FILL IN: guard given, pctx=None → AuthorizationRequired and executions == 0 — bounded by authorizing.py fail-open note
    ...
```
**Why**:
- Regeneration is opt-in behind `PARROT_REGEN_GOLDEN=1`, so a normal run can never silently rewrite the golden.
- Keep `_dump` byte-compatible with `test_contract_envelopes._dump`, so both tests read the same file format.
- Delete the `...` placeholder when you fill in the last test.

### `packages/ai-parrot/tests/outputs/a2ui/linked/test_epson_dashboard_parity.py` (CREATE)
```python
"""FEAT-611 M8 / §9 S6 — Python side of the shared Epson parity fixture (conditions, ignored params, rows)."""
from __future__ import annotations

import json
from pathlib import Path

import pytest

import parrot.outputs.a2ui.linked as linked_pkg
from parrot.outputs.a2ui.linked import executor as executor_mod
from parrot.outputs.a2ui.linked.dsl import apply_transform, frame_from_records, frame_to_records
from parrot.outputs.a2ui.linked.models import LinkedDataSource

FIXTURE = json.loads(
    (Path(linked_pkg.__file__).parent / "contract/fixtures/parity/epson_dashboard_params.json").read_text()
)


def _descriptor(key: str) -> LinkedDataSource:
    raw = FIXTURE["locked_source"] if key == "activity_locked" else FIXTURE["sources"][key]
    return LinkedDataSource.model_validate(raw)


@pytest.mark.parametrize("case", FIXTURE["param_cases"], ids=lambda c: c["id"])
def test_parity_conditions(case):
    conditions, ignored = executor_mod._conditions_for(
        _descriptor(case["source"]), case["overrides"], max_fetch_rows=FIXTURE["max_fetch_rows"]
    )
    assert conditions == case["expected_conditions"]
    assert list(conditions) == list(case["expected_conditions"])  # key order is part of the contract
    assert ignored == case["expected_ignored"]


def test_parity_rows():
    raw = {slug: frame_from_records(rows) for slug, rows in FIXTURE["input_frames"].items()}
    frames: dict = {}
    for key in ("targets", "activity", "attainment", "kpis"):  # dependency order (targets first)
        src = _descriptor(key)
        frames[key] = apply_transform(raw[src.slug], src.transform, frames=frames)
        assert frame_to_records(frames[key]) == FIXTURE["expected_rows"][key], key
```
**Why**: this uses the reference executor's private `_conditions_for` on purpose. Its (conditions, ignored)
pair is exactly what `execute_sources` would send and warn about, so the fixture pins the wire and not a re-implementation.

### `packages/ai-parrot-server/ui/src/lib/components/agents/canvas/a2ui/linked/parity.test.ts` (CREATE)
```ts
// FEAT-611 M8 / §9 S6: the TS lane reproduces the shared Epson parity fixture (conditions on the wire + rows).
import { readFileSync } from 'node:fs';
import { resolve } from 'node:path';
import { afterEach, describe, expect, it, vi } from 'vitest';
import { applyTransform } from './dsl';
import { createLinkedLane } from './index';

const FX = JSON.parse(readFileSync(resolve(process.cwd(),
  '../../ai-parrot/src/parrot/outputs/a2ui/linked/contract/fixtures/parity/epson_dashboard_params.json'), 'utf8'));

afterEach(() => vi.restoreAllMocks());

describe('epson dashboard parity — rows', () => {
  it('applyTransform matches the Python reference rows', () => {
    const frames: Record<string, Record<string, unknown>[]> = {};
    for (const key of ['targets', 'activity', 'attainment', 'kpis']) {
      const src = FX.sources[key];
      frames[key] = applyTransform(FX.input_frames[src.slug], src.transform, frames);
      expect(frames[key]).toEqual(FX.expected_rows[key]);
    }
  });
});

describe('epson dashboard parity — conditions on the wire', () => {
  it.each(FX.param_cases)('$id', async (fxCase: any) => {
    const bodies: Record<string, unknown>[] = [];
    vi.spyOn(globalThis, 'fetch').mockImplementation(async (_url, init) => {
      bodies.push(JSON.parse(String((init as RequestInit).body)));
      return new Response(JSON.stringify(FX.input_frames['epson_field_activity']));
    });
    const key = fxCase.source as string;
    const src = key === 'activity_locked' ? FX.locked_source : FX.sources[key];
    const lane = createLinkedLane({ [key]: { ...src, refresh: { policy: 'manual' } } } as any, {
      baseUrl: '', headers: () => ({}), transformsBase: '', onUpdate: () => {},
    });
    await lane.setParam(key, Object.keys(fxCase.overrides)[0], Object.values(fxCase.overrides)[0]);
    // FILL IN: declared case → exactly one body, equal (and same key order) to expected_conditions;
    //   ignored cases (expected_ignored non-empty) → ZERO fetches (TASK-3833 makes setParam a no-op for
    //   undeclared/locked names), then call lane.refreshAll() and assert the single body equals
    //   expected_conditions minus `refresh` (refreshAll sets refresh:true — strip it before comparing) —
    //   never loosen the equality — bounded by §9 S6 and index.ts setParam/refreshAll after TASK-3833
    lane.stop();
  });
});
```
**Why**:
- Use `readFileSync` with the `process.cwd()`-relative path, because the conditions/dsl tests already do
  (conditions.test.ts:7). A JSON `import` from outside the vite root would hit `server.fs` restrictions.
- Keep the fixture file as the only source of the expected values.
- `refresh: manual` stops `start()` from being needed. `setParam` alone drives the single fetch.

### `packages/ai-parrot-server/tests/ui/test_vitest_a2ui_linked_parity.py` (CREATE)
```python
"""FEAT-611 (TASK-3838): run the Epson Python↔TS parity vitest from pytest."""

from ._vitest import run_vitest


def test_a2ui_linked_parity_vitest() -> None:
    """parity.test.ts reproduces the shared epson_dashboard_params.json fixture."""
    run_vitest("src/lib/components/agents/canvas/a2ui/linked/parity.test.ts")
```
**Why**: this is the same wrapper as `test_vitest_a2ui_linked_dsl.py`. The validation contract accepts
pytest node ids only. `run_vitest` skips when node tooling is absent, so a skip is **not** a pass. Record the
real vitest outcome in the Completion Note (spec §5: vitest must run for real).

### FILL IN checklist
- [ ] `dashboard_tool.py::build_components` — the two date filters (options + `param`). Bounded by filterbar.py:29-71 and TASK-3834 validation.
- [ ] `dashboard_tool.py::build_epson_activity_dashboard` — the pre-authorization loop. Bounded by §9 S4 and service.py:87-107.
- [ ] `dashboard_tool.py::build_epson_activity_dashboard` — `programs` derived from the targets frame when None. Bounded by executor.py:221.
- [ ] `epson_dashboard_params.json` — every `"FILL IN"` value replaced with real JSON. Bounded by exact-division data and the key names the tests read.
- [ ] `test_epson_dashboard_golden.py` — execution-count/querylimit asserts, the unauthorized test, and the guard-without-pctx test. Bounded by §9 S4.
- [ ] `parity.test.ts` — the wire-body assertions for the declared and ignored cases. Bounded by §9 S6 and TASK-3833's `setParam`.

---

## Acceptance Criteria

- [ ] `build_epson_activity_dashboard()` returns `{"a2ui_envelope", "artifacts":[{"type":"a2ui_linked_surface"}]}`, and `validate_envelope(..., TOOL)` passes (including TASK-3834's FilterBar checks).
- [ ] With a guard that denies `query_slug:public:epson_field_activity`, the TOOL raises `AuthorizationRequired` and QS executes 0 times (§9 S4).
- [ ] `linked_epson_dashboard.json` equals the TOOL output (normalized `snapshot_at`), and `test_contract_envelopes.py::test_envelope_fixture_contract[linked_epson_dashboard.json]` passes.
- [ ] Python and TS produce identical conditions (declared / undeclared / locked) and identical rows for `epson_dashboard_params.json` (spec §5).
- [ ] Vitest actually ran (not skipped) for `parity.test.ts`. The outcome is recorded in the Completion Note.
- [ ] `ruff check examples/agents/a2ui/linked_e2e/dashboard_tool.py packages/ai-parrot/tests/outputs/a2ui/linked/test_epson_dashboard_golden.py packages/ai-parrot/tests/outputs/a2ui/linked/test_epson_dashboard_parity.py` is clean.
- [ ] No file under `packages/*/src` changed except the two new fixture JSON files.

---

## Validation Commands

> File-level pytest only — no directories, no package roots.

- `pytest packages/ai-parrot/tests/outputs/a2ui/linked/test_epson_dashboard_golden.py -q`
- `pytest packages/ai-parrot/tests/outputs/a2ui/linked/test_epson_dashboard_parity.py -q`
- `pytest packages/ai-parrot/tests/outputs/a2ui/linked/test_contract_envelopes.py -q`
- `pytest packages/ai-parrot-server/tests/ui/test_vitest_a2ui_linked_parity.py -q`

---

## Test Specification

See the blueprint blocks for the three Python test files and the vitest file. Required node ids:
- `test_epson_dashboard_golden.py::test_epson_dashboard_golden`
- `test_epson_dashboard_golden.py::test_dashboard_tool_unauthorized_blocked`
- `test_epson_dashboard_golden.py::test_dashboard_tool_guard_without_pctx_fails_closed`
- `test_epson_dashboard_parity.py::test_parity_conditions[declared|undeclared|locked]`
- `test_epson_dashboard_parity.py::test_parity_rows`
- `test_vitest_a2ui_linked_parity.py::test_a2ui_linked_parity_vitest`

---

## Agent Instructions

When you pick up this task:

1. **Work in the feature worktree**. Never work on `base_branch`
   (`python -m scripts.sdd.ensure_worktree --slug a2ui-linked-e2e-parallel --feature-id FEAT-611`).
2. **Read the spec** at the path listed above for full context.
3. **Check dependencies**. TASK-3833 and TASK-3834 must be `"done"` in `sdd/tasks/index/a2ui-linked-e2e-parallel.json`.
4. **Verify the Codebase Contract** before writing any code. Re-grep every listed path:line.
5. **Update status** to `"in-progress"` (set `started_at`), and commit only the index file.
6. **Implement** from the blueprint blocks, and complete every `FILL IN`.
7. **Verify**: run the Validation Commands, with vitest running for real (Node ≥24, `pnpm install --frozen-lockfile` in `packages/ai-parrot-server/ui`).
8. **Commit** only the files this task lists.
9. **Close** with `scripts/sdd/close_task.sh TASK-3838 a2ui-linked-e2e-parallel verified`.
10. **Fill in the Completion Note**.

---

## Completion Note

*(Agent fills this in when done)*

**Completed by**: <session or agent ID>
**Date**: YYYY-MM-DD
**Notes**: What was implemented, any deviations from scope, issues encountered. Record the vitest run result (ran / skipped).

**Deviations from spec**: none | describe if any
