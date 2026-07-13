# TASK-1724: Catalog components: Chart, DataTable, Map (+lowerings)

**Feature**: FEAT-273 — A2UI Protocol Integration — Rendering Core (parrot.outputs.a2ui)
**Spec**: sdd/specs/a2ui-implementation.spec.md
**Status**: pending
**Priority**: high
**Estimated effort**: L (4-8h)
**Depends-on**: TASK-1721
**Assigned-to**: unassigned

---

## Context

Spec §3 Module 3 (Catalog v1 components + lowerings). The Parrot custom
catalog (`https://parrot.dev/catalogs/v1`) ships nine components; this task
implements the three data-visualization ones: **Chart**, **DataTable**, **Map**.

The existing structured-output config models are the **starting vocabulary**
for these component schemas (spec §3 Module 3: "`STRUCTURED_CHART/TABLE/MAP`
config schemas are the starting vocabulary"): `StructuredChartConfig`,
`StructuredTableConfig`, `StructuredMapConfig` in
`packages/ai-parrot/src/parrot/models/outputs.py` already define a
library-agnostic, frontend-mirrored field set (FEAT-218/221). The A2UI
component schemas adapt that vocabulary into catalog `ComponentDefinition`
JSON Schemas — they do NOT import or embed the Pydantic classes into the
envelope wire format.

Per G4/D8, every component ships a **pure, deterministic `lower()`** to a
Basic Catalog tree — no native-only islands. Components without a `lower()`
cannot register (enforced by TASK-1721's registry, not convention).

This task runs in parallel with TASK-1725 (Card/KPICard/Timeline/Form) and
TASK-1726 (Infographic/Report); files are disjoint by construction.

---

## Scope

- Implement `Chart`, `DataTable`, and `Map` catalog components, one module
  each under `packages/ai-parrot/src/parrot/outputs/a2ui/catalog/components/`:
  - JSON Schema for the component payload (`ComponentDefinition.schema_`),
    derived from the corresponding `Structured*Config` field vocabulary
    (adapting, not importing: e.g. Chart keeps `type`, `x`, `y`, `stacked`,
    `showLegend`, `xAxisMode`, `palette`; DataTable keeps `columns`
    (name/type/title/format), `totalRows`, `truncated`; Map keeps `layers`,
    `viewport`, `baseLayer`, `title`, `description`).
  - Embedded LLM `instructions` string per component (A2UI spec requirement;
    consumed by the Module 9 producer prompt).
  - `requires_actions=False` for all three (display-only).
  - A pure deterministic `lower(component, data_model) -> BasicTree` mapping
    the component to Basic Catalog primitives (Text/Row/Column/Card/Image)
    only. Data-model bindings pass through untouched (resolution is the
    Module 6 bake pass, not lowering).
- Register all three via TASK-1721's `@register_component` decorator.
- Write golden-file lowering tests: same input envelope fragment + data model
  → byte-identical lowered tree, compared against committed golden JSON under
  `packages/ai-parrot/tests/outputs/a2ui/golden/`.

**NOT in scope**:
- The other six components (TASK-1725, TASK-1726).
- Any renderer (Module 5, satellite package) — in particular the
  echarts-payload renderer: **ECharts-specific option/config generation stays
  renderer-side in `ai-parrot-visualizations`; the lowered tree contains only
  Basic Catalog primitives, never an ECharts option object**.
- Folium/geo rendering — Map's `lower()` degrades to a static-friendly Basic
  tree (e.g. Card with title/description Text and a layer-summary Column);
  interactive tiles are the folium-map renderer's native path.
- JSON Pointer *resolution* (Module 6 bake pass) — lowering only preserves
  binding strings; catalog-side binding-syntax validation lives in Module 1/2.
- Registry/`ComponentDefinition`/allowlist mechanics (TASK-1721).
- LLM producer usage of `instructions` (TASK-1737).

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot/src/parrot/outputs/a2ui/catalog/components/chart.py` | CREATE | Chart component: schema + instructions + `lower()` |
| `packages/ai-parrot/src/parrot/outputs/a2ui/catalog/components/datatable.py` | CREATE | DataTable component: schema + instructions + `lower()` |
| `packages/ai-parrot/src/parrot/outputs/a2ui/catalog/components/map.py` | CREATE | Map component: schema + instructions + `lower()` |
| `packages/ai-parrot/src/parrot/outputs/a2ui/catalog/components/__init__.py` | CREATE or MODIFY | Import the three modules so registration side-effects run (parallel tasks touch this file — add only your three imports; merge-friendly one-import-per-line) |
| `packages/ai-parrot/tests/outputs/a2ui/test_components_chart_datatable_map.py` | CREATE | Schema, flag, and golden lowering tests |
| `packages/ai-parrot/tests/outputs/a2ui/golden/chart_lowered.json` | CREATE | Golden lowered tree for Chart |
| `packages/ai-parrot/tests/outputs/a2ui/golden/datatable_lowered.json` | CREATE | Golden lowered tree for DataTable |
| `packages/ai-parrot/tests/outputs/a2ui/golden/map_lowered.json` | CREATE | Golden lowered tree for Map |

---

## Codebase Contract (Anti-Hallucination)

> **CRITICAL**: This section contains VERIFIED code references from the actual codebase.
> The implementing agent MUST use these exact imports, class names, and method signatures.
> **DO NOT** invent, guess, or assume any import, attribute, or method not listed here.
> If you need something not listed, VERIFY it exists first with `grep` or `read`.

### Verified Imports

```python
# Vocabulary sources — read for field names/semantics; do NOT wire into the envelope format
from parrot.models.outputs import StructuredChartConfig  # verified: packages/ai-parrot/src/parrot/models/outputs.py:324
from parrot.models.outputs import StructuredTableConfig  # verified: models/outputs.py:535
from parrot.models.outputs import StructuredMapConfig    # verified: models/outputs.py:751
```

Registration decorator and component contract come from **TASK-1721**
(`parrot.outputs.a2ui.catalog` — `register_component`, `ComponentDefinition`,
the `lower()`/BasicTree contract). Those modules do not exist on `dev` yet;
verify the exact import paths and signatures against TASK-1721's committed
code (`sdd/tasks/completed/TASK-1721-*.md` completion note) before writing code.

### Existing Signatures to Use

```python
# packages/ai-parrot/src/parrot/models/outputs.py — vocabulary anchors (line-verified 2026-07-10)
ChartType = Literal[...]                       # :314 — chart type vocabulary ("bar", "line", "map", …)
class StructuredChartConfig(BaseModel):        # :324
    type: ChartType; x: str; y: List[str]      # + stacked, trendline, split_series (alias splitSeries),
                                               #   show_legend (alias showLegend), x_axis_mode, palette,
                                               #   color_by_sign, negative_color, map_name, data (INPUT-ONLY)
class TableColumn(BaseModel):                  # :498 — name / type / title / optional format
class StructuredTableConfig(BaseModel):        # :535
    columns: List[TableColumn]                 # + data (INPUT-ONLY), explanation, total_rows, truncated
class MapLayer(BaseModel):                     # :645
class MapViewport(BaseModel):                  # :711
class MapQuery(BaseModel):                     # :734
class StructuredMapConfig(BaseModel):          # :751
    layers: List[MapLayer]                     # + data (INPUT-ONLY), datasets, viewport, query,
                                               #   base_layer, title, description, explanation
```

Spec §2 contract this task implements against (from TASK-1721):

```python
# parrot/outputs/a2ui/catalog/__init__.py (spec §2 "New Public Interfaces")
def register_component(name: str, *, requires_actions: bool = False): ...   # decorator
# each component implements: def lower(self, component, data_model) -> BasicTree  # pure, deterministic (D8)
```

### Does NOT Exist

- ~~`parrot.outputs.a2ui.catalog.components`~~ — does not exist yet; this task
  (and its parallel siblings) create it.
- ~~A `BasicTree`/Basic-Catalog model on `dev` today~~ — defined by TASK-1721
  (Module 2); verify its real name/shape there before use.
- ~~An ECharts renderer for A2UI~~ — echarts-payload renderer is Module 5
  (satellite); nothing chart-rendering belongs in this task's lowered trees.
- ~~`AbstractClient.completion()`~~ / any LLM call — components are pure data;
  core `parrot.outputs.a2ui` never imports LLM clients (G8 one-way import rule).
- ~~`exec()`/`eval()` anywhere under `parrot/outputs/a2ui*`~~ — G1 invariant;
  the legacy `BaseRenderer.execute_code` sink must not be referenced.

---

## Implementation Notes

### Pattern to Follow

Vocabulary adaptation, not model reuse — e.g. the Chart component schema
mirrors this existing field set (quoted from `models/outputs.py:349` ff.):

```python
# packages/ai-parrot/src/parrot/models/outputs.py:349 — EXISTING code, vocabulary only
type: ChartType = Field(..., description="Chart type")
x: str = Field(..., description="Categorical/label column name")
y: List[str] = Field(..., description="One or more value column names (multi-series)")
```

The `data` field of all three `Structured*Config` models is INPUT-ONLY and
excluded from serialized output — in A2UI the equivalent is the **data model**
(`dataModel` + JSON Pointer bindings), so component schemas must bind rows via
the envelope data model, not carry inline `data` arrays.

### Key Constraints

- `lower()` MUST be pure and deterministic: no clocks, no randomness, no dict
  ordering dependence (serialize goldens with sorted keys), no I/O, no async.
- Lowered trees contain **Basic Catalog primitives only** (Text/Row/Column/
  Card/Image). ECharts config, folium markup, or any renderer-specific payload
  is forbidden in lowered output — that lives renderer-side (Module 5).
- Chart lowering degradation guidance: title/axis-labels as Text, series as a
  tabular Row/Column summary (a chart without a graphics backend degrades to
  its data summary — this is acceptable; AC-fallback fidelity for composites is
  OQ-C, owned by TASK-1726).
- `requires_actions=False` for all three (D10b flag is mandatory on every
  component).
- Each `instructions` string tells the LLM when to pick this component, its
  required fields, and binding rules — keep it terse; SPK-3 (TASK-1727)
  measures how well it works.
- Pydantic v2, Google-style docstrings, strict type hints; no `print`.
- Golden test recipe: build fixture component + data model → `lower()` twice →
  `json.dumps(tree, sort_keys=True).encode()` for both → assert the two byte
  strings are identical AND equal to the committed golden file bytes.

### References in Codebase

- `packages/ai-parrot/src/parrot/models/outputs.py:324/:535/:751` — schema vocabulary.
- `packages/ai-parrot-visualizations/src/parrot/outputs/formats/structured_chart.py`, `structured_table.py`, `structured_map.py` — how the legacy pipeline routes config vs. data (context only; do not extend).
- Spec §4 `test_component_lowering_golden[component]` row — the test contract this task satisfies for its three components.

---

## Acceptance Criteria

- [ ] Chart, DataTable, Map registered in the v1 catalog, each with JSON Schema, embedded `instructions`, `requires_actions=False`, and a `lower()`.
- [ ] Component schemas trace to the `Structured*Config` vocabulary (documented in each module docstring).
- [ ] Lowered trees contain only Basic Catalog primitives; no ECharts/folium/renderer-specific payloads.
- [ ] Golden determinism: for each component, two consecutive `lower()` calls on the same input serialize to byte-identical JSON matching the committed golden file.
- [ ] All tests pass: `pytest packages/ai-parrot/tests/outputs/a2ui/test_components_chart_datatable_map.py -v`
- [ ] No linting errors: `ruff check packages/ai-parrot/src/parrot/outputs/a2ui/catalog/components/`
- [ ] G1 spot check: `grep -rn "exec(\|eval(" packages/ai-parrot/src/parrot/outputs/a2ui/` returns nothing.

---

## Test Specification

> Minimal test scaffold (names + one-line docstrings). The agent must make these pass.

```python
# packages/ai-parrot/tests/outputs/a2ui/test_components_chart_datatable_map.py

class TestChartComponent:
    def test_chart_registered_in_catalog(self):
        """Chart is in the v1 catalog allowlist with requires_actions=False."""

    def test_chart_schema_accepts_structured_vocabulary(self):
        """A payload using type/x/y/showLegend fields validates against the Chart schema."""

    def test_chart_lowering_golden(self):
        """Chart lowers to golden/chart_lowered.json; two runs are byte-identical."""

    def test_chart_lowered_tree_has_no_echarts_config(self):
        """Lowered Chart tree contains only Basic Catalog primitives, no ECharts option keys."""


class TestDataTableComponent:
    def test_datatable_registered_in_catalog(self):
        """DataTable is in the v1 catalog allowlist with requires_actions=False."""

    def test_datatable_lowering_golden(self):
        """DataTable lowers to golden/datatable_lowered.json deterministically."""


class TestMapComponent:
    def test_map_registered_in_catalog(self):
        """Map is in the v1 catalog allowlist with requires_actions=False."""

    def test_map_lowering_golden(self):
        """Map lowers to golden/map_lowered.json deterministically."""

    def test_lowering_preserves_data_bindings(self):
        """JSON Pointer binding strings pass through lower() unresolved."""
```

---

## Agent Instructions

When you pick up this task:

1. **Read the spec** at the path listed above for full context
2. **Check dependencies** — verify `Depends-on` tasks are in `tasks/completed/`
3. **Verify the Codebase Contract** — before writing ANY code:
   - Confirm every import in "Verified Imports" still exists (`grep` or `read` the source)
   - Confirm every class/method in "Existing Signatures" still has the listed attributes
   - Confirm TASK-1721's actual `register_component` / `lower()` / BasicTree contract
   - If anything has changed, update the contract FIRST, then implement
   - **NEVER** reference an import, attribute, or method not in the contract without verifying it exists
4. **Update status** in the per-spec index → `"in-progress"` with your session ID
5. **Implement** following the scope, codebase contract, and notes above
6. **Verify** all acceptance criteria are met
7. **Move this file** to `tasks/completed/TASK-1724-components-chart-datatable-map.md`
8. **Update index** → `"done"`
9. **Fill in the Completion Note** below

---

## Completion Note

*(Agent fills this in when done)*

**Completed by**: sdd-worker (Claude)
**Date**: 2026-07-11
**Notes**: Implemented Chart, DataTable, Map catalog components under
`catalog/components/` (one module each), each with a JSON Schema derived from the
`StructuredChartConfig`/`StructuredTableConfig`/`StructuredMapConfig` vocabulary
(adapted, not imported), embedded `INSTRUCTIONS`, `requires_actions=False`, and a
pure deterministic `lower()` producing Basic Catalog primitives only (Card/Column/
Row/Text). Data-model bindings (`{"$bind": "/pointer"}`) pass through lowering
unresolved. `components/__init__.py` imports the three modules to trigger
registration. Golden files committed under `tests/outputs/a2ui/golden/`; tests
assert two-run byte-identity + committed-golden equality, binding pass-through, and
no ECharts option leakage. 44 tests pass (9 new); ruff clean; no exec/eval.

**Deviations from spec**: none. Golden files were generated from the lowering
implementation and committed as the regression lock (standard golden-test practice).
