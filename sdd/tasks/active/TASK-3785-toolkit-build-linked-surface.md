# TASK-3785: `qs_build_linked_surface` — the agent tool that emits a linked A2UI surface

**Feature**: FEAT-598 — A2UI Linked Surfaces
**Spec**: `sdd/specs/a2ui-linked-surfaces.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: L (4-8h)
**Depends-on**: TASK-3784, TASK-3778, TASK-3780, TASK-3770
**Assigned-to**: unassigned

---

## Context

This is the only producer of linked surfaces an LLM can reach (spec G5: only TOOL-origin builders may emit a
descriptor). `QuerysourceToolkit.build_linked_surface` (generated tool name `qs_build_linked_surface`,
`tool_prefix="qs"`) turns a slug + structured request + a component spec into a `CreateSurface` whose
`metadata.extensions.parrot_data_sources` tells the renderer how to fetch/refresh the rows itself.

Order fixed by spec §3 M7 skeleton: `get_allowed(slug, tenant=)` → `describe_slug` → `params` →
`validate_placeholders` + conditions (`forced_conditions` → `locked`) → `reject_variable_values` →
**one mandatory execution** through the Python executor (`execute_sources`, TASK-3780) → the pure builder
`build_linked_surface` (TASK-3778) with `snapshot=snapshot`. AC3 governs every rule here.

---

## Scope

- Add `QuerysourceToolkit.build_linked_surface(...)` (signature fixed below) and update the module docstring's
  generated-tool list to include `qs_build_linked_surface`.
- Build `params: dict[str, ParamSpec]` from `describe_slug(..., tenant=)` (`required`/`accepts_keywords`, TASK-3782/TASK-3784);
  empty when `detail.variables_supported` is False (spec §7 gotcha).
- `request` → `SourceRequest`; validate placeholders/filter with the existing dialect validators.
- Every `forced_conditions` key → `locked` (and present in `params` with `editable=False`, so `locked ⊆ params`).
- `reject_variable_values` on placeholders, filter and forced values (AC3).
- `conditions = derive_conditions(request, locked=<forced values>)` (S5 — the descriptor's canonical form).
- One `execute_sources({key: source})` call with `pctx=None, guard=None` (agent-tool lane = trusted service behind
  the `programs` allowlist + `forced_conditions`; spec Non-Goal: no `QSPrincipal` here).
- Build the envelope with `build_linked_surface(..., snapshot=snapshot)` and return the FEAT-473 dual-emission shape
  `{"a2ui_envelope": <dict>, "artifacts": [...]}`.
- Tests incl. the S5 parity test `test_toolkit_build_conditions_matches_derive`.

**NOT in scope**: server persistence/refresh (TASK-3787/TASK-3788); `@variables` on `qs_execute_slug` (still allowed there);
principal threading (Non-Goal); multi-source dashboards from the tool (one source per call — dashboards are
composed by the agent from several surfaces or by hand-authored TOOL builders); `transform.ref` resolution beyond
passing the validated `TransformSpec` through (validation of `ref ∈ manifest` is TASK-3777's surface pass).

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot-tools/src/parrot_tools/querysource/toolkit.py` | MODIFY | `build_linked_surface` tool + module docstring |
| `packages/ai-parrot-tools/tests/querysource/test_build_linked_surface_tool.py` | CREATE | tool tests + S5 parity test |

`parrot_tools/querysource/__init__.py` is **not** modified: the tool is a method on the already-exported
`QuerysourceToolkit`; no new public symbol is introduced.

---

## Codebase Contract (Anti-Hallucination)

### Verified Imports
```python
import pandas as pd                                                           # already used by results.py
from parrot_tools.querysource import _qs                                      # toolkit.py:18
from parrot_tools.querysource.dialect import build_conditions, validate_filter, validate_placeholders  # dialect.py:165,134,124
from parrot_tools.querysource.errors import InvalidConditionsError, QuerysourceToolkitError   # errors.py:31,8
from parrot_tools.querysource.models import SlugDetail                        # models.py:32
# TASK-3782: from parrot_tools.querysource.dialect import reject_variable_values
# FEAT-598 core (net-new, fixed module paths — import INSIDE the method, see Key Constraints):
from parrot.outputs.a2ui.linked.models import (LinkedDataSource, ParamSpec, RefreshPolicy, SourceRequest,
                                               TransformSpec)                 # TASK-3769
from parrot.outputs.a2ui.linked.conditions import derive_conditions          # TASK-3770
from parrot.outputs.a2ui.linked.executor import execute_sources              # TASK-3780
from parrot.outputs.a2ui.builders import build_linked_surface                # TASK-3778
```

### Existing Signatures to Use
```python
# packages/ai-parrot-tools/src/parrot_tools/querysource/toolkit.py (after TASK-3784)
"""… Generated tool names (tool_prefix 'qs'): qs_get_dialect_reference, qs_list_slugs, qs_describe_slug, qs_execute_slug,
qs_list_components, qs_validate_pipeline, qs_run_multiquery and — only when allow_write=True — qs_save_multiquery."""  # L1-5
class QuerysourceToolkit(AbstractToolkit):                                       # L58; tool_prefix "qs" L66
    self.forced_conditions: dict[str, Any]                                       # L92
    self.max_rows: int                                                           # L91
    async def _post_execute(self, tool_name, result, /, **kwargs)                # L128 (dict passes through untouched)
    async def describe_slug(self, slug, dry_run=False, tenant=None) -> SlugDetail  # TASK-3784 (calls get_allowed FIRST)
    async def _get_catalog(self) -> list[Any]:                                   # L245 — insert the new tool ABOVE it
# dialect.py
def validate_placeholders(placeholders: dict[str, Any], allowed: set[str]) -> None   # L124
def validate_filter(filter, *, strict: bool = True) -> list[str]                    # L134
def build_conditions(*, placeholders, filter, fields, ordering, grouping, limit, offset, refresh, max_rows, forced)  # L165
    # payload = placeholders; filter → "filter"; fields/ordering/grouping when non-empty;
    # querylimit = min(limit or max_rows, max_rows) (ALWAYS present); offset → "_offset"; refresh → "refresh": True;
    # forced merged last ({**payload, **forced})
# packages/ai-parrot/src/parrot/outputs/a2ui/builders.py — builder precedent: Chart/DataTable bind rows via
#   props["data"] = {"path": …} (build_chart L130-131, build_datatable L196-197)
# FEAT-598 net-new signatures (spec §3):
#   build_linked_surface(components: Sequence[dict], sources: Mapping[str, LinkedDataSource], frames: Mapping[str, pd.DataFrame],
#       *, surface_id: str, snapshot: bool = True, max_snapshot_rows: int = 500, catalog_id: str = DEFAULT_CATALOG_ID) -> CreateSurface
#   async execute_sources(sources, *, param_overrides=None, pctx=None, guard=None, max_snapshot_rows=None,
#       max_fetch_rows=5000) -> ExecutionOutcome   # outcomes[key]: SourceOutcome(rows, snapshot_at, truncated, error, ignored_params)
#   derive_conditions(request: SourceRequest, *, locked: Mapping[str, Any]) -> dict[str, Any]
```

### Does NOT Exist
- ~~`qs_build_linked_surface` / `QuerysourceToolkit.build_linked_surface`~~ — net-new here.
- ~~`LinkedSurfaceToolkit`, `parrot_tools/linked_surfaces.py`~~ — NOT built (superseded 2026-09-24).
- ~~`ExecutionResult.dtypes`, `SourceOutcome.frame`~~ — the executor returns **records**; see FILL IN on dtypes.
- ~~`QSPrincipal` / `pctx` on this lane~~ — Non-Goal.
- ~~`supports_tenant_multiquery`~~ — never built (AC5).
- ~~`ToolResult.metadata["dtypes"]`, `QSourceTool`~~ — hard-cut / never existed.

---

## Complexity Contract

```json
{
  "schema_version": 1,
  "targets": [
    {"path": "packages/ai-parrot-tools/src/parrot_tools/querysource/toolkit.py", "action": "MODIFY"},
    {"path": "packages/ai-parrot-tools/tests/querysource/test_build_linked_surface_tool.py", "action": "CREATE"}
  ],
  "contract_symbols": [
    "sym:packages/ai-parrot-tools/src/parrot_tools/querysource/toolkit.py#QuerysourceToolkit",
    "sym:packages/ai-parrot-tools/src/parrot_tools/querysource/toolkit.py#QuerysourceToolkit.describe_slug",
    "sym:packages/ai-parrot-tools/src/parrot_tools/querysource/dialect.py#build_conditions",
    "sym:packages/ai-parrot-tools/src/parrot_tools/querysource/dialect.py#validate_placeholders",
    "sym:packages/ai-parrot-tools/src/parrot_tools/querysource/dialect.py#validate_filter",
    "sym:packages/ai-parrot/src/parrot/outputs/a2ui/builders.py#build_chart",
    "sym:packages/ai-parrot/src/parrot/outputs/a2ui/builders.py#build_datatable"
  ]
}
```

---

## Implementation Notes

### Key Constraints
- **Import the core linked modules inside the method**, not at `toolkit.py` module level — `parrot.outputs.a2ui.linked.executor`
  pulls pandas + dataset_manager; keeping FEAT-558's import-time cost unchanged is the precedent of `_qs` laziness.
- Tool docstring is the LLM contract: explain `request` shape (`placeholders`, `filter`, `fields`, `ordering`,
  `grouping`, `limit`, `offset`), `component` shape (`{"component": "Chart"|"DataTable"|"KPICard", …props}` — omit
  the data binding, the tool adds it), `snapshot` (embed ≤500 current rows), UDF keywords (TODAY, YESTERDAY, FDOM,
  LDOM, CURRENT_YEAR, CURRENT_MONTH, LAST_YEAR) and that `@variables` are rejected.
- AC3 verbatim: "always executes the slug once, validates axes against the fetched columns/dtypes, embeds ≤500 rows
  only when `snapshot=True` (`snapshot_truncated` when cut), derives `conditions` from `request`, maps
  `forced_conditions` keys to `locked`, rejects any `@`-prefixed value, and emits `origin=TOOL`."
- Execution happens even when `snapshot=False` — axis validation needs the real frame (spec G6).
- A failed execution (`SourceOutcome.error`) raises `QuerysourceToolkitError` with the error text; never emit an
  envelope for a slug that did not run.
- `tenant` is copied verbatim into the descriptor; never inferred (AC4).

### References in Codebase
- `toolkit.py:190-243` (`execute_slug`) — validation order to mirror.
- `packages/ai-parrot-tools/tests/querysource/conftest.py` — `patched_qs` / `fake_rows` reuse.

---

## Implementation Blueprint

### Steps (in order)
1. Update the module docstring tool list — *why*: it documents generated tool names (spec Edit Site `toolkit.py:3`).
2. Add `build_linked_surface` above `_get_catalog` with the fixed signature — *why*: spec M7 skeleton.
3. Add two private helpers `_linked_params` and `_bind_component` — *why*: keep each block < 80 lines and each
   rule testable.
4. Write the tests (order, locked, `@` rejection, snapshot on/off, tenant MultiQuery, S5 parity).

### `packages/ai-parrot-tools/src/parrot_tools/querysource/toolkit.py` (MODIFY)

**Block A — module docstring**
```python
# occurrences: 1 (verified: grep -c "Generated tool names (tool_prefix 'qs')" packages/ai-parrot-tools/src/parrot_tools/querysource/toolkit.py)
# REPLACE lines 3-4 (verified: toolkit.py:3-4) with:
Generated tool names (tool_prefix 'qs'): qs_get_dialect_reference, qs_list_slugs, qs_describe_slug, qs_execute_slug,
qs_build_linked_surface, qs_list_components, qs_validate_pipeline, qs_run_multiquery and — only when allow_write=True —
qs_save_multiquery.
```

**Block A2 — imports**
```python
# occurrences: 1 (verified: grep -c 'from parrot_tools.querysource.dialect import (' toolkit.py) — block at toolkit.py:27-34
# add `reject_variable_values,` to that import block (alphabetical, after `load_variables,`); add `import re` after
# `import copy` (L10) and `import pandas as pd` after `from typing import Any` (L13) — pandas is already imported
# transitively via results.py:11, so no import-time cost change.
```

**Block B — the tool**
```python
# occurrences: 1 (verified: grep -c '    async def _get_catalog(self) -> list[Any]:' toolkit.py)
# BEFORE — insert above `    async def _get_catalog(self) -> list[Any]:` (verified: toolkit.py:245)
    async def build_linked_surface(
        self,
        slug: str,
        component: dict[str, Any],
        request: dict[str, Any] | None = None,
        tenant: str | None = None,
        snapshot: bool = True,
        surface_id: str | None = None,
        target_key: str | None = None,
        refresh: dict[str, Any] | None = None,
        transform: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        """Emit a LINKED A2UI surface for a query-slug: the renderer re-fetches the slug itself (on mount, on demand
        or on an interval ≥30 s) instead of showing baked numbers. `component` is {"component": "Chart"|"DataTable"|
        "KPICard", …props} WITHOUT a data binding (added for you). `request` = {placeholders, filter, fields, ordering,
        grouping, limit, offset} in the qs_execute_slug grammar; relative dates use UDF keywords (TODAY, YESTERDAY,
        FDOM, LDOM, CURRENT_YEAR, CURRENT_MONTH, LAST_YEAR) — '@variables' are rejected. `tenant` selects a QuerySource
        tenant store. The slug is executed once to validate the component's columns; `snapshot=True` also embeds up
        to 500 current rows. `refresh` = {policy: on_mount|manual|interval, interval_seconds}; `transform` = {ops: […]}."""
        from parrot.outputs.a2ui.builders import build_linked_surface as _build
        from parrot.outputs.a2ui.linked.conditions import derive_conditions
        from parrot.outputs.a2ui.linked.executor import execute_sources
        from parrot.outputs.a2ui.linked.models import LinkedDataSource, RefreshPolicy, SourceRequest, TransformSpec

        detail = await self.describe_slug(slug, tenant=tenant)  # get_allowed(slug, tenant=) is its FIRST act
        req = SourceRequest.model_validate(request or {})
        validate_placeholders(dict(req.placeholders), set(detail.placeholders))
        validate_filter(dict(req.filter))
        forced = dict(self.forced_conditions)
        reject_variable_values({**req.placeholders, "filter": req.filter, **forced})
        params, locked = self._linked_params(detail, forced)
        key = target_key or self._default_target_key(slug)
        source = LinkedDataSource(
            slug=slug,
            tenant=tenant,
            is_multiquery=detail.is_multiquery,
            conditions=derive_conditions(req, locked={k: forced[k] for k in locked}),
            request=req,
            params=params,
            locked=locked,
            transform=TransformSpec.model_validate(transform) if transform else None,
            target=f"/{key}/rows",
            refresh=RefreshPolicy.model_validate(refresh or {}),
        )
        self.logger.info("qs_build_linked_surface %s tenant=%s key=%s snapshot=%s", slug, tenant, key, snapshot)
        execution = await execute_sources({key: source})  # ONE mandatory run; pctx/guard None (trusted lane)
        outcome = execution.outcomes[key]
        if outcome.error:
            raise QuerysourceToolkitError(f"query '{slug}' failed while building the linked surface: {outcome.error}")
        # ExecutionOutcome.frames (TASK-3780) keeps the transformed DataFrame with its real dtypes — never rebuild it from
        # `outcome.rows` (ISO strings would lose datetime64 and break the §7 axis rules / AC3).
        frame = execution.frames[key]
        envelope = _build(
            [self._bind_component(component, key)],
            {key: source},
            {key: frame},
            surface_id=surface_id or f"linked-{key}",
            snapshot=snapshot,
        )
        # FILL IN: artifacts entry — minimal {"type": "a2ui_linked_surface", "surface_id", "sources": [key],
        # "slug", "tenant"} — bounded by the FEAT-473 dual-emission shape {'a2ui_envelope', 'artifacts'} (spec M7)
        artifacts: list[dict[str, Any]] = []
        return {"a2ui_envelope": envelope.model_dump(mode="json", by_alias=True, exclude_none=True), "artifacts": artifacts}
```

**Block C — helpers (insert directly below Block B)**
```python
    def _linked_params(self, detail: SlugDetail, forced: dict[str, Any]) -> tuple[dict[str, Any], list[str]]:
        """ParamSpec per describe placeholder (empty when variables_supported is False); forced keys → locked."""
        from parrot.outputs.a2ui.linked.models import ParamSpec

        params: dict[str, Any] = {}
        if detail.variables_supported:
            for info in detail.placeholders_detail:
                params[info.name] = ParamSpec(
                    type=info.type, default=info.default, required=info.required, accepts_keywords=info.accepts_keywords
                )
        # FILL IN: for every forced key: if absent from params add ParamSpec(default=value, editable=False); else set
        # editable=False and default=value (model_copy); locked = list(forced) in forced-dict order — bounded by
        # M1 validator locked ⊆ params and AC3 "maps forced_conditions keys to locked"
        raise NotImplementedError

    @staticmethod
    def _default_target_key(slug: str) -> str:
        """dataModel root key for a slug: [A-Za-z0-9_] only, never starting with a digit."""
        # FILL IN: re.sub(r"\W", "_", slug); prefix "s_" when it starts with a digit — bounded by JSON-pointer safety
        raise NotImplementedError

    @staticmethod
    def _bind_component(component: dict[str, Any], key: str) -> dict[str, Any]:
        """Return a wire component dict with id 'root' and its rows binding to /<key>/rows."""
        comp = dict(component)
        comp.setdefault("id", "root")
        # FILL IN: Chart/DataTable → comp["data"] = {"path": f"/{key}/rows"} (builders.py:130-131,196-197 precedent);
        # KPICard: a plain column-name string `value` → {"path": f"/{key}/rows/0/<col>"}; any other component →
        # InvalidConditionsError listing the supported ones — bounded by spec §7 Axis validation (Chart/DataTable/KPICard)
        raise NotImplementedError
```
**Why**: `describe_slug` gives the tenant gate + params in one call (order test: its first act is `get_allowed`);
conditions are *derived* from `request` so M3's `conditions == derive_conditions(...)` check always passes (S5);
the helpers isolate the three judgement calls.

### `packages/ai-parrot-tools/tests/querysource/test_build_linked_surface_tool.py` (CREATE)
```python
"""FEAT-598 TASK-3785 — qs_build_linked_surface (AC3, AC4, AC5, S5)."""

from __future__ import annotations

import pandas as pd
import pytest

from parrot_tools.querysource.dialect import build_conditions
from parrot_tools.querysource.errors import InvalidConditionsError
from parrot_tools.querysource.toolkit import QuerysourceToolkit

pytest.importorskip("querysource.queries.describe")


@pytest.fixture
def fake_core_qs(patched_qs, monkeypatch):
    """Patch the CORE executor seam: parrot.tools.dataset_manager.sources.query_slug._get_qs/_get_multiqs (TASK-3779)."""
    state: dict = {"qs": [], "mq": []}
    # FILL IN: FakeQS / FakeMultiQS recording kwargs (tenant=, conditions=), query(output_format=…) returning a
    # 12-row DataFrame (day date, visits int, program str), close(); monkeypatch both module functions
    raise NotImplementedError


async def test_build_linked_surface_tool_order(fake_core_qs, monkeypatch):
    # FILL IN: spy tk._catalog.get_allowed + _qs.get_describe order; exactly ONE core QS execution; envelope origin TOOL
    # (validate_envelope(origin=TOOL) passes; origin=LLM fails with DATA_SOURCES_NOT_ALLOWED_FOR_LLM)
    raise NotImplementedError


async def test_forced_conditions_become_locked(fake_core_qs):
    # FILL IN: QuerysourceToolkit(forced_conditions={"program": "epson"}) → source.locked == ["program"],
    # params["program"].editable is False, conditions carry program="epson"
    raise NotImplementedError


async def test_variable_values_rejected(fake_core_qs):
    tk = QuerysourceToolkit(dsn="postgres://fake")
    with pytest.raises(InvalidConditionsError):
        await tk.build_linked_surface(
            "epson_field_activity", {"component": "Chart", "type": "bar", "x": "day", "y": ["visits"]},
            request={"placeholders": {"firstdate": "@today"}},
        )


async def test_snapshot_false_still_executes(fake_core_qs):
    # FILL IN: snapshot=False → one execution, dataModel[key] == {"rows": []}, snapshot_at None (S9)
    raise NotImplementedError


async def test_axis_validation_unknown_column(fake_core_qs):
    # FILL IN: x="nope" → ValueError from the builder naming prop/column; nothing returned
    raise NotImplementedError


async def test_tenant_multiquery_builds(fake_core_qs):
    # FILL IN: tenant="acme" + a multiquery record → MultiQS (not QS) dispatched with tenant="acme"; descriptor
    # tenant == "acme", is_multiquery True — bounded by AC5 (no version gate)
    raise NotImplementedError


def test_toolkit_build_conditions_matches_derive():
    """S5: build_conditions(...) minus its lane-time keys equals derive_conditions(...)."""
    from parrot.outputs.a2ui.linked.conditions import derive_conditions
    from parrot.outputs.a2ui.linked.models import SourceRequest

    # FILL IN: parametrise over the TASK-3770 fixtures in parrot/outputs/a2ui/linked/contract/fixtures/conditions/*.json
    # (Path(parrot.outputs.a2ui.linked.__file__).parent / "contract" / "fixtures" / "conditions"); for each:
    # payload = build_conditions(placeholders=…, filter=…, fields=…, ordering=…, grouping=…, limit=…, offset=…,
    # refresh=False, max_rows=5000, forced=<locked>); drop "querylimit" and "refresh"; assert == derive_conditions(
    # SourceRequest(**request), locked=locked) — bounded by S5 and the §7 derive_conditions rules
    raise NotImplementedError
```

### FILL IN checklist
- [ ] Frame reconstruction + date re-parsing; bounded by §7 axis rules / AC3.
- [ ] `artifacts` entry; bounded by FEAT-473 dual-emission shape.
- [ ] `_linked_params` forced → locked; bounded by locked ⊆ params.
- [ ] `_default_target_key`; `_bind_component` per component type.
- [ ] Every test body + `fake_core_qs`.

---

## Acceptance Criteria

- [ ] AC3 holds end-to-end (one execution, axis validation, ≤500-row snapshot only when `snapshot=True`,
      `conditions` derived from `request`, forced → `locked`, `@` rejected, `origin=TOOL`).
- [ ] AC4: descriptor `tenant` is exactly the argument; `QS/MultiQS(tenant=)` receives it.
- [ ] AC5: `tenant != null ∧ is_multiquery` builds and runs through `MultiQS(tenant=)`.
- [ ] S5 parity test passes against every conditions fixture.
- [ ] `qs_build_linked_surface` appears in `QuerysourceToolkit().get_tools()` names.
- [ ] `ruff check` / `black --check` clean.

## Validation Commands

- `pytest packages/ai-parrot-tools/tests/querysource/test_build_linked_surface_tool.py -q`
- `pytest packages/ai-parrot-tools/tests/querysource/test_toolkit_core.py -q`

---

## Test Specification

See the CREATE block above.

---

## Agent Instructions

When you pick up this task:

1. **Read the spec** at the path listed above for full context
2. **Check dependencies** — verify `Depends-on` tasks are in `tasks/completed/`
3. **Verify the Codebase Contract** — before writing ANY code:
   - Confirm every import in "Verified Imports" still exists (`grep` or `read` the source) — in particular the
     FEAT-598 signatures produced by TASK-3769/TASK-3770/TASK-3778/TASK-3780/TASK-3784 (they may differ in detail from the spec skeleton)
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
