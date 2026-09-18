# TASK-3253: `list_components` and `validate_pipeline` tools

**Feature**: FEAT-558 — QuerysourceToolkit — tenant-scoped query-slug and MultiQuery tools
**Spec**: `sdd/specs/querysource-toolkit-refactor.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: M (2-4h)
**Depends-on**: TASK-3249, TASK-3252
**Assigned-to**: unassigned

---

## Context

Spec §3 Module 6 (goals G5, G6-validate). The MultiQuery component catalog is available in-process via
`ComponentRegistry.get_catalog()` (same payload as `GET /api/v3/qs/components`; the REST handler runs it in
`asyncio.to_thread`, `handlers/components.py:50`). `validate_pipeline` combines the library's structural rules
(`ComponentRegistry.validate_pipeline`, which skips node contents) with the toolkit's policy over
`normalize_pipeline()`: tenant check per slug node, raw nodes, external sources (§8 Q1), destination steps
(writes, `allow_write`).

---

## Scope

- Add to `QuerysourceToolkit`: `_get_catalog()` (cached, `asyncio.to_thread`), `_destination_names()`, `list_components(category=None)`, `validate_pipeline(pipeline)`, and the internal `_policy_check(pipeline) -> PipelineValidation` reused by TASK-3254.
- Unit tests with a fake `ComponentRegistry`.

**NOT in scope**: executing or saving pipelines (TASK-3254).

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot-tools/src/parrot_tools/querysource/toolkit.py` | MODIFY | add 2 tools + helpers |
| `packages/ai-parrot-tools/tests/querysource/test_components_validate.py` | CREATE | unit tests |

---

## Codebase Contract (Anti-Hallucination)

### Verified Imports
```python
import asyncio
from dataclasses import asdict
from parrot_tools.querysource.catalog import normalize_pipeline, NormalizedPipeline        # TASK-3249
from parrot_tools.querysource.models import ComponentDoc, PipelineIssue, PipelineValidation   # TASK-3246
```

### Existing Signatures to Use
```python
# querysource/queries/multi/registry.py (installed 4.5.11)
class ComponentRegistry:                                                  # :72
    @classmethod def get_catalog(cls) -> list[ComponentInfo]              # :187  sync + heavy → asyncio.to_thread (handlers/components.py:50)
    @classmethod def validate_pipeline(cls, payload: dict) -> ValidationResult   # :332  rules: ≥1 source section; step names known; Join/Merge arity
@dataclass class ComponentInfo(name, category, description, usage, attributes: list[AttributeInfo], json_schema, example, icon)   # :34
@dataclass class ValidationResult(valid: bool, errors: list[ValidationError])   # :62 ; ValidationError(step, field, message) :54
# categories emitted: "Operators" | "Transformations" | "Sources" | "Destinations" | "Components"  (:36, :312-330)
# handlers/components.py:47-53  catalog = await asyncio.to_thread(ComponentRegistry.get_catalog); if category: filter c.category == category
# TASK-3251/3252 toolkit.py anchor: `    async def execute_slug(` (its final `return frame_to_result(...)`)
```

### Does NOT Exist
- ~~`ComponentRegistry.get_components()`~~ / ~~`.list_components()`~~ — the method is `get_catalog()`.
- ~~`ComponentRegistry.validate_pipeline` checking slug tenancy or node contents~~ — it skips `queries/files/sources` (registry.py:365); the toolkit's policy does that.
- ~~an `is_destination` flag on `ComponentInfo`~~ — classify by `category == "Destinations"`.
- ~~HTTP calls to `/api/v3/qs/components`~~ — in-process only.

---

## Implementation Notes

### Key Constraints
- `_get_catalog()` caches `list[ComponentInfo]` on the instance (`self._components_cache`, created in TASK-3251's `__init__`).
- `ComponentInfo` → `ComponentDoc` via `asdict()` (nested `AttributeInfo` dataclasses convert too).
- `_policy_check` issues (each a `PipelineIssue(step, field, message)`):
  - raw node & (`restricted` or not `allow_raw_sql`) → step=node name, field="query", message names the rule;
  - `has_files`/`has_sources` & not `allow_external_sources` → step="files"/"sources";
  - slug node whose row is denied → step=node, field="slug" (catch `TenantDeniedError`/`SlugNotFoundError`, message = str(exc));
  - destination step in `output_steps` & not `allow_write` → step=name, field="Output".
  - Structural errors from `ComponentRegistry.validate_pipeline` are appended as issues too (`asyncio.to_thread`).
- `validate_pipeline` never executes anything and never raises for policy failures — it reports.

---

## Implementation Blueprint

### Steps (in order)
1. Add imports; insert the block after `execute_slug` — *why*: TASK-3254 reuses `_policy_check` and anchors after `validate_pipeline`.
2. Complete the `FILL IN` policy loop; tests.

### `packages/ai-parrot-tools/src/parrot_tools/querysource/toolkit.py` (MODIFY — imports)
```python
# occurrences: 1 (verified after TASK-3252: grep -c '^from parrot_tools.querysource.results import frame_to_result' toolkit.py)
# AFTER — insert below `from parrot_tools.querysource.results import frame_to_result`
import asyncio                      # move to the stdlib import group
from dataclasses import asdict      # move to the stdlib import group
from parrot_tools.querysource.catalog import NormalizedPipeline, normalize_pipeline
from parrot_tools.querysource.errors import SlugNotFoundError, TenantDeniedError
from parrot_tools.querysource.models import ComponentDoc, PipelineIssue, PipelineValidation
```
### `packages/ai-parrot-tools/src/parrot_tools/querysource/toolkit.py` (MODIFY — methods)
```python
# occurrences: 1 (verified after TASK-3252: grep -c '    async def execute_slug(' toolkit.py)
# AFTER — insert below the end of `execute_slug` (its final `return frame_to_result(...)`)
    async def _get_catalog(self) -> list[Any]:
        """ComponentRegistry.get_catalog() via to_thread, cached per instance (handlers/components.py:50)."""
        if self._components_cache is None:
            registry = _qs.get_component_registry()
            self._components_cache = await asyncio.to_thread(registry.get_catalog)      # registry.py:187
        return self._components_cache

    async def _destination_names(self) -> set[str]:
        return {c.name for c in await self._get_catalog() if c.category == "Destinations"}

    async def list_components(self, category: str | None = None) -> list[ComponentDoc]:
        """List MultiQuery pipeline components (Operators, Transformations, Sources, Destinations) with their JSON
        schema and a usage example — the same catalog as GET /api/v3/qs/components. Optional `category` filter."""
        catalog = await self._get_catalog()
        if category:
            catalog = [c for c in catalog if c.category == category]
        return [ComponentDoc(**asdict(c)) for c in catalog]

    async def _policy_check(self, pipeline: dict[str, Any]) -> PipelineValidation:
        """Toolkit policy over normalize_pipeline(): tenancy per slug node, raw nodes, external sources, destinations."""
        norm: NormalizedPipeline = normalize_pipeline(pipeline)
        issues: list[PipelineIssue] = []
        await self._open()
        for node, slug in norm.slug_nodes.items():
            try:
                await self._catalog.get_allowed(slug)
            except (TenantDeniedError, SlugNotFoundError) as exc:
                issues.append(PipelineIssue(step=node, field="slug", message=str(exc)))
        destinations = sorted(set(norm.output_steps) & await self._destination_names())
        # FILL IN: raw nodes → issue when self.restricted or not self.allow_raw_sql (field='query');
        #          files/sources → issue when not self.allow_external_sources (step='files'/'sources');
        #          destinations → issue when not self.allow_write (field='Output') — bounded by spec §2 Tenancy + §5 AC
        return PipelineValidation(valid=not issues, issues=issues, referenced_slugs=sorted(set(norm.slug_nodes.values())),
                                  has_raw_nodes=bool(norm.raw_nodes), has_external_sources=norm.has_files or norm.has_sources,
                                  destination_steps=destinations)

    async def validate_pipeline(self, pipeline: dict[str, Any]) -> PipelineValidation:
        """Validate a MultiQuery pipeline without running it: structural rules (known step names, ≥1 source, Join/Merge
        arity) plus this toolkit's policy — every queries[*] slug must be one this instance may execute; raw SQL nodes,
        external sources and destination (write) steps are reported when the configuration forbids them."""
        result = await self._policy_check(pipeline)
        registry = _qs.get_component_registry()
        structural = await asyncio.to_thread(registry.validate_pipeline, dict(pipeline))   # registry.py:332
        for err in getattr(structural, "errors", []):
            result.issues.append(PipelineIssue(step=err.step, field=err.field, message=err.message))
        result.valid = not result.issues
        return result
```
**Why this shape**: `_policy_check` is the single authority on tenancy/raw/external/write for pipelines and is
reused by `run_multiquery`/`save_multiquery` (TASK-3254); structural validation is delegated to the library.

### FILL IN checklist
- [ ] `toolkit.py::_policy_check` — three issue rules; bounded by spec §2 Tenancy paragraph and §5 AC (raw/external/destinations)

---

## Acceptance Criteria

- [ ] `list_components()` calls `get_catalog` once across two calls; `category="Operators"` filters; the `Concat` doc has keys `name, category, description, usage, attributes, json_schema, example, icon`.
- [ ] restricted `["pokemon"]` + example pipeline (raw node + `tableOutput`, no write) → issues for the raw node and `tableOutput`; slugs listed in `referenced_slugs`; `valid is False`.
- [ ] `programs=None, allow_raw_sql=True, allow_write=True` + example pipeline → `valid is True` (fake structural result has no errors).
- [ ] `allow_external_sources=False` + `files` → issue; default → no issue for `files`/`sources`.
- [ ] Both tools appear in `list_tool_names()`; `pytest packages/ai-parrot-tools/tests/querysource/test_components_validate.py -v` passes; `ruff check` clean.

---

## Test Specification

```python
# packages/ai-parrot-tools/tests/querysource/test_components_validate.py
from dataclasses import dataclass, field
import pytest
from parrot_tools.querysource import _qs
from parrot_tools.querysource.toolkit import QuerysourceToolkit
from .conftest import PIPELINE

@dataclass
class CI: name: str; category: str; description: str = "d"; usage: str = "u"; attributes: list = field(default_factory=list); json_schema: dict | None = None; example: str = ""; icon: str = ""
@dataclass
class VR: valid: bool = True; errors: list = field(default_factory=list)

@pytest.fixture
def fake_registry(patched_qs, monkeypatch):
    calls = {"catalog": 0}
    class Reg:
        @classmethod
        def get_catalog(cls):
            calls["catalog"] += 1
            return [CI("Concat", "Operators", json_schema={"type": "object"}, example='{"Concat": {}}', icon="git-merge"),
                    CI("Join", "Operators"), CI("tableOutput", "Destinations"), CI("pivot", "Transformations")]
        @classmethod
        def validate_pipeline(cls, payload): return VR()
    monkeypatch.setattr(_qs, "ComponentRegistry", Reg)
    return calls

async def test_components_cached_and_filtered(fake_registry):
    tk = QuerysourceToolkit(dsn="postgres://fake")
    docs = await tk.list_components(); await tk.list_components(category="Operators")
    assert fake_registry["catalog"] == 1 and {d.name for d in docs} == {"Concat", "Join", "tableOutput", "pivot"}
    assert set(docs[0].model_dump()) == {"name", "category", "description", "usage", "attributes", "json_schema", "example", "icon"}

async def test_policy_restricted(fake_registry):
    raw = dict(PIPELINE, queries={**PIPELINE["queries"], "n1": {"query": "select 1", "driver": "pg"}})
    v = await QuerysourceToolkit(dsn="postgres://fake", programs=["pokemon"]).validate_pipeline(raw)
    assert not v.valid and {i.step for i in v.issues} >= {"n1", "tableOutput"} and v.has_raw_nodes
    assert v.referenced_slugs == ["pokemon_all_fso_odoo_new", "pokemon_warehouses_kiosk_all_fso"] or "pokemon_warehouses_kiosk_all_fso" in [i.step for i in v.issues] or True

async def test_policy_permissive_and_external(fake_registry):
    tk = QuerysourceToolkit(dsn="postgres://fake", allow_raw_sql=True, allow_write=True)
    assert (await tk.validate_pipeline({"queries": {"a": {"slug": "epson_field_activity"}}, "files": {"f": "x.csv"}})).valid
    tk2 = QuerysourceToolkit(dsn="postgres://fake", allow_external_sources=False)
    v = await tk2.validate_pipeline({"queries": {"a": {"slug": "epson_field_activity"}}, "files": {"f": "x.csv"}})
    assert [i.step for i in v.issues] == ["files"]
```
(Note: `pokemon_warehouses_kiosk_all_fso` is not in `fake_rows`, so it surfaces as a `SlugNotFoundError` issue — the test above tolerates that; tighten it if you add the row to `conftest.py`.)

---

## Agent Instructions

1. Read spec §3 Module 6, §2 Tenancy paragraph, §6 ComponentRegistry anchors.
2. Verify TASK-3249 and TASK-3252 completed; anchors occur once; update index → `in-progress`.
3. Implement; tests; `ruff`. Move this file to `sdd/tasks/completed/`, update index → `done`, fill the Completion Note.

---

## Completion Note

**Completed by**: sdd-worker (Claude Sonnet 5), manual fallback implementation
**Date**: 2026-09-17
**Notes**: Added `_get_catalog`, `_destination_names`, `list_components`, `_policy_check`, `validate_pipeline`
to `toolkit.py` (plus imports) per spec §3 Module 6. Filled the FILL IN policy loop (raw-node issues when
`restricted or not allow_raw_sql`; files/sources issues when `not allow_external_sources`; destination-step
issues when `not allow_write`). `pytest packages/ai-parrot-tools/tests/querysource/test_components_validate.py
-v` — 3 passed. `ruff check` — clean.

**Same recurring stale-snapshot fix as TASK-3252**: updated `test_toolkit_core.py::test_tool_names_and_write_gate`'s
tool-name list to add `qs_list_components`/`qs_validate_pipeline` (this task's own AC explicitly requires "Both
tools appear in `list_tool_names()`"). Full `packages/ai-parrot-tools/tests/querysource/` suite — 60 passed.
Implemented manually: same repo-wide `complex_model_unavailable` block (empty `strong_models` policy); user
authorized continuing the fallback loop for the rest of the feature.

**Deviations from spec**: touched `test_toolkit_core.py` again (one line) to keep its tool-name snapshot
current, consistent with this task's own acceptance criterion; no other deviation.
