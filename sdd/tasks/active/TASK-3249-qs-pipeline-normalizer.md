# TASK-3249: MultiQuery pipeline normaliser (`normalize_pipeline`)

**Feature**: FEAT-558 — QuerysourceToolkit — tenant-scoped query-slug and MultiQuery tools
**Spec**: `sdd/specs/querysource-toolkit-refactor.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: S (< 2h)
**Depends-on**: TASK-3248
**Assigned-to**: unassigned

---

## Context

Spec §3 Module 4 (second half), design research S6. `ComponentRegistry.validate_pipeline()` deliberately skips the
contents of `queries`, `files` and `sources` (`registry.py:365`), so the toolkit needs its own pure walk of the
MultiQS shape to know which slugs a pipeline references (tenant check), which nodes are raw SQL (forbidden when
restricted / `allow_raw_sql=False`), whether external sources are present (`allow_external_sources`, §8 Q1) and which
`Output` steps are destinations (writes, `allow_write`).

---

## Scope

- Append `NormalizedPipeline` and `normalize_pipeline()` to `catalog.py` (after `SlugCatalog`).
- Unit tests for every node form and for malformed input.

**NOT in scope**: classifying `Output` steps into destinations (needs the component catalog — TASK-3253 does it with `output_steps`), tenant checks (callers do them).

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot-tools/src/parrot_tools/querysource/catalog.py` | MODIFY | append normaliser |
| `packages/ai-parrot-tools/tests/querysource/test_pipeline_normalizer.py` | CREATE | unit tests |

---

## Codebase Contract (Anti-Hallucination)

### Verified Imports
```python
from parrot_tools.querysource.errors import InvalidConditionsError   # TASK-3245
# (same module) dataclass, Any already imported by TASK-3248's catalog.py header
```

### Existing Signatures to Use
```python
# MultiQS shape — querysource/queries/multi/__init__.py (installed 4.5.11)
self._queries = query.pop('queries', {})      # :95  mapping name → node dict
self._files = query.pop('files', {})          # :96  mapping name → file spec
raw_sources = query.pop('sources', [])        # :97  list of {source_type: config}   (:280-300 iterates entry.items())
_output = self._options.pop('Output', None)   # :443 list of {StepName: config} dicts (transformations and destinations)
# step keys handled at top level: Info, Join, Concat, Melt, Merge (:356-423); the rest of _options are steps too
# node dict forms — querysource/queries/obj.py:49-63: 'slug' → slug node; 'query' → raw query node (needs 'driver');
#   ThreadQuery.slug → self._query.get('slug', self._name)  (sources/query.py:62)
# QS also accepts 'raw_query' (qs.py:82-87) — treat as raw node too
# registry.validate_pipeline skip_keys = {"queries","files","sources","Output","Transform","Processors"}  (registry.py:365)
```

### Does NOT Exist
- ~~`MultiQS.normalize()`~~ / ~~`ComponentRegistry.walk()`~~ — no library helper; this function is the toolkit's own.
- ~~`queries` as a list~~ — MultiQS expects a mapping; a list is malformed → `InvalidConditionsError`.
- ~~destination classification here~~ — `output_steps` are just names; TASK-3253 classifies them via the catalog.

---

## Implementation Notes

### Key Constraints
- Pure function, no I/O, no querysource import.
- A node with both `slug` and `query` counts as raw (fail closed).
- `step_names` = top-level keys not in `{"queries","files","sources","Output"}`; `output_steps` = the single key of each dict in `Output` (skip non-dict entries but record an issue? → raise `InvalidConditionsError` for malformed entries).

---

## Implementation Blueprint

### Steps (in order)
1. Append the block to `catalog.py` — *why*: the spec keeps normalisation next to the catalog that consumes `slug_nodes`.
2. Complete the `FILL IN` loop; write tests with the proposal's example pipeline (uses `PIPELINE` from `conftest.py`).

### `packages/ai-parrot-tools/src/parrot_tools/querysource/catalog.py` (MODIFY)
```python
# occurrences: 1 (verified after TASK-3248: grep -c '^class SlugCatalog:' packages/ai-parrot-tools/src/parrot_tools/querysource/catalog.py)
# AFTER — append at END OF FILE, below the `SlugCatalog` class body written by TASK-3248
_SECTION_KEYS = ("queries", "files", "sources", "Output")
_RAW_NODE_KEYS = ("query", "raw_query")


@dataclass
class NormalizedPipeline:
    """Flat view of a MultiQS pipeline dict (design research S6)."""
    slug_nodes: dict[str, str]          # node name → slug
    raw_nodes: list[str]                # node names carrying query/raw_query
    has_files: bool
    has_sources: bool
    step_names: list[str]               # top-level keys other than queries/files/sources/Output
    output_steps: list[str]             # step names inside Output (transformations + destinations)


def normalize_pipeline(pipeline: dict[str, Any]) -> NormalizedPipeline:
    """Walk the MultiQS shape (multi/__init__.py:95-97,443; obj.py:49-63); raise InvalidConditionsError when malformed."""
    if not isinstance(pipeline, dict):
        raise InvalidConditionsError("pipeline must be a JSON object")
    queries = pipeline.get("queries") or {}
    if not isinstance(queries, dict):
        raise InvalidConditionsError("'queries' must be a mapping of node name → {slug | query}")
    slug_nodes: dict[str, str] = {}
    raw_nodes: list[str] = []
    for name, node in queries.items():
        if not isinstance(node, dict):
            raise InvalidConditionsError(f"query node '{name}' must be an object")
        # FILL IN: raw if any key in _RAW_NODE_KEYS present (even alongside 'slug'); else slug = node.get('slug', name);
        #          record into raw_nodes / slug_nodes — bounded by obj.py:49-63 and sources/query.py:62
    files = pipeline.get("files") or {}
    sources = pipeline.get("sources") or []
    output = pipeline.get("Output") or []
    if not isinstance(output, list) or any(not isinstance(step, dict) or len(step) != 1 for step in output):
        raise InvalidConditionsError("'Output' must be a list of single-key step objects")
    return NormalizedPipeline(
        slug_nodes=slug_nodes,
        raw_nodes=raw_nodes,
        has_files=bool(files),
        has_sources=bool(sources),
        step_names=[k for k in pipeline if k not in _SECTION_KEYS],
        output_steps=[next(iter(step)) for step in output],
    )
```
**Why this shape**: mirrors exactly how MultiQS pops the sections; slug default to the node name copies
`ThreadQuery.slug`; a node mixing `slug` and `query` is treated as raw so tenancy cannot be bypassed.

### FILL IN checklist
- [ ] `catalog.py::normalize_pipeline` node loop — raw vs slug classification; bounded by obj.py:49-63, sources/query.py:62

---

## Acceptance Criteria

- [ ] The proposal's example pipeline → `slug_nodes == {"pokemon_all_fso_odoo": "pokemon_all_fso_odoo_new", "pokemon_warehouses_kiosks": "pokemon_warehouses_kiosk_all_fso"}`, `raw_nodes == ["node_1789431043582_1d32g"]`, `step_names == ["Join"]`, `output_steps == ["tableOutput"]`.
- [ ] A node without `slug` uses its name as slug; `files`/`sources` flags set; list-typed `queries` or non-dict pipeline raises `InvalidConditionsError`.
- [ ] `pytest packages/ai-parrot-tools/tests/querysource/test_pipeline_normalizer.py -v` passes; `ruff check` clean.

---

## Test Specification

```python
# packages/ai-parrot-tools/tests/querysource/test_pipeline_normalizer.py
import pytest
from parrot_tools.querysource.catalog import normalize_pipeline
from parrot_tools.querysource.errors import InvalidConditionsError

EXAMPLE = {"queries": {"pokemon_all_fso_odoo": {"slug": "pokemon_all_fso_odoo_new"},
                       "pokemon_warehouses_kiosks": {"slug": "pokemon_warehouses_kiosk_all_fso"},
                       "node_1789431043582_1d32g": {"query": "select * from hisense.stores", "driver": "pg"}},
           "Join": [{"type": "left", "left": "pokemon_all_fso_odoo", "right": "pokemon_warehouses_kiosks", "using": ["warehouse_alias"]}],
           "Output": [{"tableOutput": {"flavor": "postgresql", "tablename": "all_fso_odoo_new", "schema": "pokemon"}}]}

def test_example_pipeline():
    n = normalize_pipeline(EXAMPLE)
    assert n.slug_nodes == {"pokemon_all_fso_odoo": "pokemon_all_fso_odoo_new", "pokemon_warehouses_kiosks": "pokemon_warehouses_kiosk_all_fso"}
    assert n.raw_nodes == ["node_1789431043582_1d32g"] and n.step_names == ["Join"] and n.output_steps == ["tableOutput"]
    assert not n.has_files and not n.has_sources

def test_node_defaults_to_its_name_and_sources_flag():
    n = normalize_pipeline({"queries": {"epson_field_activity": {}}, "sources": [{"s3": {"bucket": "b"}}], "files": {"f": "x.csv"}})
    assert n.slug_nodes == {"epson_field_activity": "epson_field_activity"} and n.has_sources and n.has_files

@pytest.mark.parametrize("bad", [[], {"queries": []}, {"queries": {"a": "slug"}}, {"queries": {}, "Output": ["x"]}])
def test_malformed(bad):
    with pytest.raises(InvalidConditionsError):
        normalize_pipeline(bad)
```

---

## Agent Instructions

1. Read spec §3 Module 4 (NormalizedPipeline) and §6 MultiQS anchors.
2. Verify TASK-3248 completed and `class SlugCatalog:` occurs once; update index → `in-progress`.
3. Append the block, complete the `FILL IN`, tests, `ruff`.
4. Move this file to `sdd/tasks/completed/`, update index → `done`, fill the Completion Note.

---

## Completion Note

*(Agent fills this in when done)*

**Completed by**:
**Date**:
**Notes**:

**Deviations from spec**: none
