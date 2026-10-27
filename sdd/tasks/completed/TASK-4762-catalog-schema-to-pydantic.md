# TASK-4762: catalog/_model.py — JSON Schema → Pydantic for structured_output

**Feature**: FEAT-755 — Inline A2UI Component Routing
**Spec**: `sdd/specs/inline-a2ui-component-routing.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: L (4-8h)
**Depends-on**: none
**Assigned-to**: unassigned

---

## Context

Spec §3 Module 6a. The emitter advertises the component's schema to the LLM as
`structured_output` rather than serializing it into the prompt. That needs a Pydantic
model per component, generated from the registered `ComponentDefinition.schema_`.

**This is the riskiest task in the feature.** The catalog's object schemas are loose
*on purpose* — `KPICARD_SCHEMA["value"]` and `["delta"]` carry a `description` but no
`type` (number | string | binding), `["series"]` is `{"type": ["array","object"]}`,
`["higherIsBetter"]` is `["boolean","null"]` where null and omitted differ by design,
and a `{"path": "/pointer"}` binding may replace ANY property value. A generator that
tightens any of this makes a legal config unauthorable, and the failure is **invisible**:
the LLM simply never emits that shape and the card silently degrades.

Hence AC-6 and the G6-fidelity check: anything that validates against `schema_` must
also validate against the generated model.

Note the repo already derives the *other* direction (`catalog/parrot/_derive.py:88`,
Pydantic → JSON Schema). Both directions now coexist; that cost was weighed and
accepted (spec §8).

---

## Scope

- Create `catalog/_model.py` with `model_from_schema(schema, *, name)` and `component_model(component, catalog_id=None)`.
- Implement the loose-vocabulary mapping rules exactly (untyped → `Any`, type lists → `Union`, enums → `Literal`, nested objects/arrays recursive, optional unless `required`, descriptions carried verbatim, `extra="allow"`).
- Add `SOURCE_MODEL = GraphSpec` to `GraphComponent` and have `component_model` prefer it.
- Cache per `(catalog_id, component)` with a clearable cache for tests.
- Write `test_catalog_model.py` including the fidelity property check.

**NOT in scope**: The prompt builder (TASK-4763), the emitter (TASK-4765), and any change to an existing catalog `SCHEMA` — the three hand-written schemas stay exactly as they are (that was the rejected alternative in spec §8).

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot/src/parrot/outputs/a2ui/catalog/_model.py` | CREATE | JSON Schema → Pydantic generator + per-component lookup |
| `packages/ai-parrot/src/parrot/outputs/a2ui/catalog/viz_core/graph.py` | MODIFY | Declare SOURCE_MODEL = GraphSpec |
| `packages/ai-parrot/tests/outputs/a2ui/test_catalog_model.py` | CREATE | Unit + fidelity tests |

---

## Codebase Contract (Anti-Hallucination)

> **CRITICAL**: VERIFIED code references from the actual codebase. Use these exact
> imports, class names, and method signatures. DO NOT invent, guess, or assume any
> import, attribute, or method not listed here. Verified against `e21bc561e+ (dev @ 2026-10-27, re-verified at /sdd-task time)`.

### Verified Imports
```python
from pydantic import BaseModel, ConfigDict, Field, create_model

from parrot.outputs.a2ui.catalog import CatalogError, get_component  # verified: catalog/__init__.py:209
# In graph.py only — GraphSpec is ALREADY imported there; do NOT add an import:
from parrot.outputs.a2ui.graph import GraphEdge, GraphSpec, to_mermaid  # verified: viz_core/graph.py:27
```

### Existing Signatures to Use
```python
# parrot/outputs/a2ui/catalog/__init__.py:209
def get_component(name: str, catalog_id: str | None = None) -> RegisteredComponent: ...

# parrot/outputs/a2ui/catalog/base.py:293-297
@dataclass
class RegisteredComponent:
    definition: ComponentDefinition
    component_cls: type          # <- SOURCE_MODEL is read off THIS

# parrot/outputs/a2ui/catalog/base.py:234,258-266
class ComponentDefinition(BaseModel):
    name: str; catalog_id: str; schema_: dict[str, Any] = Field(alias="schema")
    instructions: str = ""; requires_actions: bool = False; tool_only: bool = False

# parrot/outputs/a2ui/catalog/viz_core/graph.py:35,73
GRAPH_SCHEMA: dict[str, Any] = derive_schema(GraphSpec, binding_fields=("data",), required=("nodes", "edges"))
class GraphComponent:
    SCHEMA = GRAPH_SCHEMA         # :73
    INSTRUCTIONS = GRAPH_INSTRUCTIONS

# The loose vocabulary this generator MUST preserve — parrot/outputs/a2ui/catalog/parrot/kpicard.py
#   "value":          {"description": ...}                      <- NO "type" key
#   "delta":          {"description": ...}                      <- NO "type" key
#   "series":         {"type": ["array", "object"], ...}
#   "higherIsBetter": {"type": ["boolean", "null"], ...}
#   "trend":          {"type": "string", "enum": ["up","down","flat"]}
#   "format":         {"type": "string", "enum": ["percent","currency","number"]}
```

### Does NOT Exist
- ~~`model_from_schema` / `component_model` / `catalog/_model.py`~~ — this task CREATES them; grep over `packages/*/src` returns 0 hits.
- ~~a `SOURCE_MODEL` attribute on any catalog component~~ — none declares one today; `register_component` reads only `SCHEMA`/`INSTRUCTIONS` off the class (`catalog/__init__.py:179-180`).
- ~~a `source_model` / `model` field on `ComponentDefinition`~~ — the definition has no model field; reach the class through `RegisteredComponent.component_cls`.
- ~~`pydantic.json_schema.models_json_schema` as an inverse~~ — Pydantic ships NO JSON-Schema→model direction; `create_model` is the tool.
- ~~changing `KPICARD_SCHEMA` / `INFOCARD_SCHEMA` / `TIMELINE_SCHEMA`~~ — explicitly rejected in spec §8; the generator adapts to them, not the reverse.

---

## Complexity Contract

```json
{
  "schema_version": 1,
  "targets": [
    {
      "path": "packages/ai-parrot/src/parrot/outputs/a2ui/catalog/_model.py",
      "action": "CREATE"
    },
    {
      "path": "packages/ai-parrot/src/parrot/outputs/a2ui/catalog/viz_core/graph.py",
      "action": "MODIFY"
    },
    {
      "path": "packages/ai-parrot/tests/outputs/a2ui/test_catalog_model.py",
      "action": "CREATE"
    }
  ],
  "contract_symbols": [
    "sym:packages/ai-parrot/src/parrot/outputs/a2ui/catalog/__init__.py#get_component",
    "sym:packages/ai-parrot/src/parrot/outputs/a2ui/catalog/base.py#ComponentDefinition",
    "sym:packages/ai-parrot/src/parrot/outputs/a2ui/catalog/base.py#RegisteredComponent",
    "sym:packages/ai-parrot/src/parrot/outputs/a2ui/catalog/viz_core/graph.py#GraphComponent",
    "sym:packages/ai-parrot/src/parrot/outputs/a2ui/graph/models.py#GraphSpec"
  ]
}
```

---

## Implementation Notes

### Key Constraints
- **Never tighten the schema.** This is AC-6 and the whole risk of the task:
  - a property with no `type` → `Any` (NOT `str`);
  - `{"type": ["array","object"]}` → `Union[list, dict]`;
  - `{"type": ["boolean","null"]}` → `Optional[bool]` **with a default that distinguishes omitted from null** — `higherIsBetter` has four meaningful outcomes (`True` / `False` / `None` / absent) and collapsing any two is a defect;
  - every property Optional unless named in the schema's `required`;
  - `model_config = ConfigDict(extra="allow")` so a `{"path": "/pointer"}` binding is accepted in place of any value.
- Carry each property's `description` verbatim into `Field(description=...)` — the provider sees the catalog's own words, which is how G6 stays true.
- `enum` → `Literal[...]`; nested `object` / `array` `items` recurse through the same rules.
- **Source model wins**: `getattr(component_cls, "SOURCE_MODEL", None)` is returned verbatim when present. Round-tripping `GraphSpec` through `GRAPH_SCHEMA` would discard its validators (`kind="dag"` rejects cycles) — that is exactly why `Graph` declares one.
- Cache per `(catalog_id, component)`; expose a cache-clear for tests (`unregister_component` is used for test isolation).
- `component_model` raises `KeyError` for an unregistered component — same contract as `get_component`.

### References in Codebase
- `parrot/outputs/a2ui/catalog/parrot/_derive.py:88` — `derive_schema`, the opposite direction; read its docstring for the binding-field convention.
- `parrot/outputs/a2ui/catalog/parrot/kpicard.py` — the loosest schema; use it as the generator's hardest test case.
- `parrot/outputs/a2ui/catalog/viz_core/graph.py:35,73` — where `SOURCE_MODEL` goes.
- `parrot/outputs/a2ui/graph/models.py` — `GraphSpec` and its validators (re-exported from `parrot.outputs.a2ui.graph`, which is the path `graph.py:27` actually imports).

---

## Implementation Blueprint

> **Executor-ready starting point.** Write each block to its declared path nearly
> verbatim, then complete every `# FILL IN:` marker. Business-logic branches, edge
> cases and test bodies are `FILL IN` stubs by design. Never change a signature,
> class name, or file path the blueprint fixes.

### Steps (in order)
1. Write `model_from_schema` with the mapping rules — *why*: every rule exists because a specific catalog property would otherwise become unauthorable.
2. Add `component_model` with the SOURCE_MODEL-first lookup and the cache — *why*: `Graph` must keep its validators, and generation per request would be wasteful.
3. Declare `SOURCE_MODEL = GraphSpec` on `GraphComponent` — *why*: one line that preserves the dag-cycle check.
4. Write the fidelity property test — *why*: AC-6 is the only guard against the silent-narrowing failure mode.

### `packages/ai-parrot/src/parrot/outputs/a2ui/catalog/_model.py` (CREATE)
```python
"""Catalog JSON Schema -> Pydantic model, for ``structured_output`` (FEAT-755).

The emitter advertises a component's schema to the LLM as a Pydantic model rather
than serializing JSON Schema into the prompt. The catalog's schemas are deliberately
loose, and this generator MUST preserve that looseness: a model stricter than its
schema makes a legal config unauthorable, and the failure is invisible.

The opposite direction lives in ``catalog/parrot/_derive.py`` (Pydantic -> schema).
"""
from __future__ import annotations

import logging
from typing import Any, Literal, Mapping, Optional, Union

from pydantic import BaseModel, ConfigDict, Field, create_model

logger = logging.getLogger(__name__)

__all__ = ["model_from_schema", "component_model", "clear_model_cache"]

_CACHE: dict[tuple[Optional[str], str], type[BaseModel]] = {}


def _python_type(prop: Mapping[str, Any], *, name: str) -> Any:
    """Map ONE JSON-Schema property to a Python annotation.

    Rules (each exists for a real catalog property — do not "simplify"):
      * no ``type`` key        -> ``Any``        (KPICard ``value`` / ``delta``)
      * ``["array","object"]`` -> ``Union[list, dict]``  (KPICard ``series``)
      * ``["boolean","null"]`` -> ``Optional[bool]``     (KPICard ``higherIsBetter``)
      * ``enum``               -> ``Literal[...]``
      * ``object`` / ``array`` -> a nested model built by the same rules
    """
    # FILL IN: the mapping table above — bounded by AC-1/AC-2/AC-6


def model_from_schema(schema: Mapping[str, Any], *, name: str) -> type[BaseModel]:
    """Build a Pydantic v2 model from a catalog component's JSON Schema.

    Every property is Optional unless listed in ``schema["required"]``; each field
    carries the schema's ``description`` verbatim; ``extra="allow"`` so a binding
    descriptor (``{"path": "/pointer"}``) is accepted in place of any value.

    Returns a NEW type on each call — callers cache (see :func:`component_model`).
    """
    # FILL IN: walk schema["properties"], build the create_model kwargs,
    #          __config__=ConfigDict(extra="allow") — bounded by AC-1..AC-3


def component_model(component: str, catalog_id: Optional[str] = None) -> type[BaseModel]:
    """The model to advertise as ``structured_output`` for ``component``.

    Returns ``component_cls.SOURCE_MODEL`` verbatim when the component declares one
    (only ``Graph`` does in v1 — round-tripping ``GraphSpec`` through ``GRAPH_SCHEMA``
    would discard its validators), else generates from ``definition.schema_``.

    Raises:
        KeyError: If ``component`` is not registered (same contract as ``get_component``).
    """
    from parrot.outputs.a2ui.catalog import get_component  # local: avoids an import cycle

    # FILL IN: cache lookup -> get_component -> SOURCE_MODEL or model_from_schema
    #          — bounded by AC-4/AC-5


def clear_model_cache() -> None:
    """Drop every cached model (test isolation, pairs with ``unregister_component``)."""
    _CACHE.clear()
```
**Why this shape**: `_python_type` is split out so each loose-vocabulary rule is independently testable — that is where the silent-narrowing bug would live. The catalog import is function-local because `catalog/__init__.py` imports the component modules, which would otherwise cycle through this one.

### `packages/ai-parrot/src/parrot/outputs/a2ui/catalog/viz_core/graph.py` (MODIFY)
```python
# occurrences: 1 (verified: grep -c '    SCHEMA = GRAPH_SCHEMA' packages/ai-parrot/src/parrot/outputs/a2ui/catalog/viz_core/graph.py)
# AFTER — insert directly below `    SCHEMA = GRAPH_SCHEMA` (verified: viz_core/graph.py:73)
    SOURCE_MODEL = GraphSpec  # FEAT-755: component_model() returns this verbatim, so
                              # GraphSpec's validators (kind="dag" rejects cycles) survive
                              # instead of being lost to a schema round-trip.
```
**Why**: `GraphSpec` is already imported in this module for `derive_schema` (`:35`), so this adds a reference, not an import. One line buys back every validator on the hardest component to author.

### `packages/ai-parrot/tests/outputs/a2ui/test_catalog_model.py` (CREATE)
```python
"""Catalog schema -> Pydantic generation (FEAT-755 TASK-4762)."""
from __future__ import annotations

import pytest

from parrot.outputs.a2ui.catalog._model import clear_model_cache, component_model, model_from_schema


@pytest.fixture(autouse=True)
def _clean_cache():
    clear_model_cache()
    yield
    clear_model_cache()


class TestLooseVocabulary:
    # FILL IN: untyped "value"/"delta" accept a number, a string AND {"path": "/p"};
    #          "series" accepts both a list and a dict;
    #          "higherIsBetter" round-trips True / False / None / omitted as FOUR
    #          distinguishable outcomes (assert on model_dump(exclude_unset=True));
    #          "trend" enum accepts "up" and rejects "sideways";
    #          a property absent from `required` is Optional
    #          — bounded by AC-1/AC-2/AC-3

class TestSourceModel:
    # FILL IN: component_model("Graph") IS GraphSpec (identity, not a generated type);
    #          a cyclic kind="dag" payload still raises;
    #          KPICard/InfoCard/Timeline return generated models;
    #          the same call twice returns the SAME cached type;
    #          an unregistered name raises KeyError
    #          — bounded by AC-4/AC-5

class TestFidelity:
    """G6: the generated model is never stricter than its catalog schema."""
    # FILL IN: for each of KPICard/InfoCard/Timeline/Graph, take the configs the
    #          conformance fixtures already use, assert jsonschema-validity against
    #          definition.schema_ AND successful model_validate() on component_model()
    #          — bounded by AC-6
```
**Why**: `TestFidelity` is the task's real deliverable. Without it a narrowing bug ships silently, because a too-strict model does not raise — the LLM just stops producing that shape.

### FILL IN checklist
- [ ] `_model.py::_python_type` — the five mapping rules; bounded by AC-1/AC-2/AC-6
- [ ] `_model.py::model_from_schema` — property walk, required handling, `extra="allow"`; bounded by AC-1..AC-3
- [ ] `_model.py::component_model` — SOURCE_MODEL-first lookup + cache; bounded by AC-4/AC-5
- [ ] `test_catalog_model.py` — the three test classes, fidelity included; bounded by AC-1..AC-6

---

## Acceptance Criteria

- [ ] **AC-1**: an untyped property (`value`, `delta`) maps to `Any` and accepts a number, a string, and a `{"path": "/p"}` binding.
- [ ] **AC-2**: `{"type": ["array","object"]}` accepts both a list and a dict; `enum` becomes a `Literal` that rejects an off-list value.
- [ ] **AC-3**: `higherIsBetter` round-trips `True`, `False`, `None` and *omitted* as four distinguishable outcomes; every non-`required` property is Optional; `extra="allow"` is set.
- [ ] **AC-4**: `component_model("Graph") is GraphSpec` (identity), and a cyclic `kind="dag"` payload still raises through it.
- [ ] **AC-5**: models are cached per `(catalog_id, component)` — two calls return the same type; `clear_model_cache()` resets; an unregistered name raises `KeyError`.
- [ ] **AC-6 (G6 fidelity)**: for every component in the v1 allowlist, a config valid against `definition.schema_` also validates against `component_model()` — the generated model is never stricter.
- [ ] `ruff check` clean on all three files.

---

## Validation Commands

> File-level pytest only — no directories, no package roots.

- `pytest packages/ai-parrot/tests/outputs/a2ui/test_catalog_model.py -q`
- `pytest packages/ai-parrot/tests/outputs/a2ui/test_components_graph.py -q`
- `pytest packages/ai-parrot/tests/outputs/a2ui/test_components_card_kpicard_timeline_form.py -q`

---

## Test Specification

Create `packages/ai-parrot/tests/outputs/a2ui/test_catalog_model.py` per the blueprint.

`TestFidelity` is mandatory and is the reason this task exists — source its payloads
from the configs the existing conformance fixtures already build
(`packages/ai-parrot/tests/outputs/a2ui/conformance/test_all_emitters.py`) so the property is checked
against real, known-good data rather than hand-written samples.

The existing component tests in Validation Commands must still pass — adding
`SOURCE_MODEL` is additive and must not change `GRAPH_SCHEMA` or any lowering.

---

## Agent Instructions

When you pick up this task:

1. **Work in the feature worktree** — never on `dev`
   (`python -m scripts.sdd.ensure_worktree --slug inline-a2ui-component-routing --feature-id FEAT-755`)
2. **Read the spec** at `sdd/specs/inline-a2ui-component-routing.spec.md` for full context
3. **Check dependencies** — every `Depends-on` task must be `"done"` in
   `sdd/tasks/index/inline-a2ui-component-routing.json`
4. **Verify the Codebase Contract** — before writing ANY code:
   - Confirm every import in "Verified Imports" still exists (`grep` or `read` the source)
   - Confirm every class/method in "Existing Signatures" still has the listed attributes
   - If anything has changed, update the contract FIRST, then implement
   - **NEVER** reference an import, attribute, or method not in the contract without verifying it exists
5. **Update status** in `sdd/tasks/index/inline-a2ui-component-routing.json` → `"in-progress"`
   (set `started_at`) and commit only that index file
6. **Implement** — start from the Implementation Blueprint blocks, complete every
   `# FILL IN:` marker, and never change a signature or path the blueprint fixes
7. **Verify** all acceptance criteria are met — run the Validation Commands
8. **Commit the code** — stage only the files this task lists (never `git add .` / `-A`)
9. **Close the task** with `scripts/sdd/close_task.sh <ID> inline-a2ui-component-routing verified`
   — it moves this file to `sdd/tasks/completed/` and marks it `"done"` in the
   index; never move or copy the file by hand
10. **Fill in the Completion Note** below, then commit the staged SDD state

---

## Completion Note

**Completed by**: sdd-worker orchestrator; implemented by native/opus (attempt 1)
**Date**: 2026-10-27
**Notes**: Added model_from_schema/component_model/clear_model_cache in catalog/_model.py, Graph SOURCE_MODEL, and tests (62 passed per coder). Fidelity gate clean. Merge-tier validation (chunk 0) green: exit 0. Closed via close_task.sh because finalize_task needs a durable review EvidenceRef that coder_record_review does not return; review recorded as coder-review feedback ids.

**Deviations from spec**: none. Choices beyond blueprint: number->Union[int,float]; unsafe property names get alias; unusable enums fall back to Any.
