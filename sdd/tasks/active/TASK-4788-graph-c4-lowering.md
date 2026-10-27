# TASK-4788: Catalog — C4 lowering, instructions, authoring notes, utterances

**Feature**: FEAT-754 — C4 architecture diagrams as a `Graph` kind
**Spec**: `sdd/specs/a2ui-c4-diagrams.spec.md`
**Status**: pending
**Priority**: medium
**Estimated effort**: M (2-4h)
**Depends-on**: TASK-4785
**Assigned-to**: unassigned

---

## Context

Spec §3 Module 4 and the lowered tree in §2 Data Models (lines 354-367). `GraphComponent.lower()`
gains a C4 branch; non-C4 output must stay byte-identical (`golden/graph_lowered.json`). The two
FEAT-755 hand-off constants are published here. `GRAPH_SCHEMA` is derived — never edited.

---

## Scope

- Append the fixed C4 sentence to `GRAPH_INSTRUCTIONS` (spec §3 M4).
- Add `GRAPH_C4_AUTHORING_NOTES: Final[str]` and `GRAPH_C4_UTTERANCES: Final[tuple[str, ...]]` (10 EN/ES phrases, verbatim from spec).
- `_edge_extensions` adds `parrot_technology` when `edge.technology` is set.
- Add `_c4_children(spec)`; in `lower()` for `kind == "c4"`: caption `"C4 <level> diagram"`, default description
  `"C4 <level> diagram of N elements and M relationships"`, boundary-list (omitted with no groups), element-list,
  edge text `"<from> → <to> (<label>) via <technology>"`, Card extension `parrot_c4_level`.
- Create `golden/graph_c4_lowered.json` (generated with the `_dump` helper pattern) and `test_components_graph_c4.py`.

**NOT in scope**: router / emitter / `DEFAULT_OUTPUT_MODE_ROUTES` changes (FEAT-755); a registry slot for authoring notes (spec §8 Q1).

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot/src/parrot/outputs/a2ui/catalog/viz_core/graph.py` | MODIFY | C4 branch + constants |
| `packages/ai-parrot/tests/outputs/a2ui/golden/graph_c4_lowered.json` | CREATE | golden |
| `packages/ai-parrot/tests/outputs/a2ui/test_components_graph_c4.py` | CREATE | M4 tests |

---

## Codebase Contract (Anti-Hallucination)

### Verified Imports
```python
from parrot.outputs.a2ui.catalog.viz_core.graph import GRAPH_SCHEMA, GRAPH_INSTRUCTIONS, GraphComponent  # verified: graph.py:35,42,64
from parrot.outputs.a2ui.catalog.viz_core import VIZ_CORE_CATALOG_ID  # verified: viz_core/__init__.py:28
from parrot.outputs.a2ui.catalog import catalog_instructions  # verified: catalog/__init__.py:314
from parrot.outputs.a2ui.catalog.base import BasicNode, to_components  # verified: catalog/base.py:111,174
from typing import Any, Final
```

### Existing Signatures to Use
```python
# packages/ai-parrot/src/parrot/outputs/a2ui/catalog/viz_core/graph.py (verified at 65144d730)
GRAPH_SCHEMA = derive_schema(GraphSpec, binding_fields=("data",), required=("nodes", "edges"))  # 35-39
GRAPH_INSTRUCTIONS = (                                             # 42-51
def _edge_extensions(edge: GraphEdge) -> dict[str, Any]            # 54-60
@register_component("Graph", catalog_id=VIZ_CORE_CATALOG_ID)       # 63
class GraphComponent:                                              # 64
    def lower(self, component: Component, data_model: dict[str, Any]) -> BasicTree   # 76
        # graph_props 95; spec = GraphSpec.model_validate 96; description 98-100; children 102-108;
        # title 109-112; caption 113-119 (`text=f"Graph ({spec.kind}, {spec.direction})",` at 116);
        # edge list 121-138; graph-source 140-146; Card 148-153 (extensions {"parrot_variant": "graph"})
# tests: packages/ai-parrot/tests/outputs/a2ui/test_components_graph.py:18-19 `_dump` (json.dumps sort_keys=True, indent=2), :51 test_graph_lower_golden
```

### Does NOT Exist
- ~~`AUTHORING_NOTES` on `ComponentDefinition` / `GraphComponent`~~ — module constants only.
- ~~`OutputMode.C4` / `OutputMode.STRUCTURED_C4`~~.
- ~~any edit to `GRAPH_SCHEMA`~~ — it is derived.

---

## Complexity Contract

```json
{
  "schema_version": 1,
  "targets": [
    {"path": "packages/ai-parrot/src/parrot/outputs/a2ui/catalog/viz_core/graph.py", "action": "MODIFY"},
    {"path": "packages/ai-parrot/tests/outputs/a2ui/golden/graph_c4_lowered.json", "action": "CREATE"},
    {"path": "packages/ai-parrot/tests/outputs/a2ui/test_components_graph_c4.py", "action": "CREATE"}
  ],
  "contract_symbols": [
    "sym:packages/ai-parrot/src/parrot/outputs/a2ui/catalog/viz_core/graph.py#GraphComponent.lower",
    "sym:packages/ai-parrot/src/parrot/outputs/a2ui/catalog/viz_core/graph.py#_edge_extensions"
  ]
}
```

---

## Implementation Notes

### Key Constraints
- No colour/font vocabulary in any new string (parity regex).
- Every non-C4 kind takes exactly today's code path — fork on `spec.kind == "c4"` only around description, caption, the two new lists and the Card extensions.
- Element text: `"<label or id> [<c4Type>] · <technology>? — <description>?"`; boundary text `"<label or id> (<c4Type> boundary)"` with `parrot_c4_type` (`generic` when None) and `parrot_depth`.

---

## Implementation Blueprint

### Steps (in order)
1. Append the instruction sentence and add the two constants.
2. Extend `_edge_extensions` (adds key only when set → non-C4 golden unaffected).
3. Add `_c4_children` and fork `lower()`.
4. Generate the golden from the shared fixture, inspect it by hand, commit; write tests.

### `.../catalog/viz_core/graph.py` (MODIFY)
```python
# occurrences: 1 (verified: grep -c 'GRAPH_INSTRUCTIONS = (' graph.py) — append inside the tuple, as its last string:
    " For a software-architecture diagram set kind=\"c4\" with level (context/container/component/dynamic), give every"
    " node a c4Type (person, system, container, component, *_ext, *_db, *_queue) plus description (technology only on"
    " containers/components), and model boundaries as groups (c4Type enterprise/system/container, nested via parent)."

GRAPH_C4_AUTHORING_NOTES: Final[str] = (
    # FILL IN: numbered plain-text guide — spec §3 M4 bullet 2 (one element per real system/container, externals as
    #          *_ext, persons first, verb-phrase labels, technology on containers/components, ≤ 15 elements,
    #          boundaries only with ≥ 2 members, never positions/action)
)
GRAPH_C4_UTTERANCES: Final[tuple[str, ...]] = (
    "C4 context diagram of the platform",
    "draw a C4 container diagram of this system",
    "show the architecture as a C4 diagram",
    "component diagram of the API service",
    "system context diagram with external systems",
    "diagrama de contexto C4 de la plataforma",
    "diagrama de contenedores de la aplicación",
    "dibuja la arquitectura del sistema como C4",
    "diagrama de componentes del servicio",
    "diagrama de contexto con los sistemas externos",
)

# in _edge_extensions (graph.py:54-60), before return:
#     if edge.technology: ext["parrot_technology"] = edge.technology   # FILL IN: match local variable name


def _c4_children(spec: GraphSpec) -> list[BasicNode]:
    """Boundary-list and element-list Columns for a kind="c4" spec (order and roles per spec §2 Data Models)."""
    # FILL IN: boundary depth via parent chain; element parrot_group from groups membership — spec §2 lines 359-362
    raise NotImplementedError

# occurrences: 1 (verified: grep -c 'text=f"Graph ({spec.kind}, {spec.direction})",' graph.py → line 116)
# FILL IN: in lower(): c4 description default (98-100), caption text "C4 {spec.level} diagram",
#          children.extend(_c4_children(spec)) before the edge list, edge text with " via <technology>",
#          Card extensions {"parrot_variant": "graph", "parrot_c4_level": spec.level} — non-C4 unchanged
```

### `packages/ai-parrot/tests/outputs/a2ui/test_components_graph_c4.py` (CREATE)
```python
"""FEAT-754 M4 — C4 lowering of the viz-core Graph component."""
from __future__ import annotations

import json
from pathlib import Path

from parrot.outputs.a2ui.catalog import catalog_instructions
from parrot.outputs.a2ui.catalog.viz_core import VIZ_CORE_CATALOG_ID
from parrot.outputs.a2ui.catalog.viz_core import graph as graph_mod

HERE = Path(__file__).resolve().parent
FIXTURE = HERE / "fixtures" / "c4_container_diagram.json"
GOLDEN = HERE / "golden" / "graph_c4_lowered.json"


def _dump(tree) -> str:
    return json.dumps(tree.model_dump(exclude_none=True), sort_keys=True, indent=2)  # FILL IN: mirror test_components_graph.py:18-19 exactly


def test_graph_c4_lower_golden() -> None: ...
def test_graph_c4_lower_roles_and_order() -> None: ...
def test_graph_c4_lower_source_is_c4_mermaid() -> None: ...
def test_graph_c4_authoring_notes_and_utterances() -> None: ...
def test_graph_instructions_mention_c4() -> None: ...
# FILL IN: bodies — build the Component the same way test_components_graph.py does
```

### FILL IN checklist
- [ ] authoring notes text; `_edge_extensions` addition; `_c4_children`; `lower()` fork
- [ ] golden generated and committed; test bodies

---

## Acceptance Criteria

- [ ] C4 lowering matches golden `graph_c4_lowered.json`; `golden/graph_lowered.json` byte-identical.
- [ ] `GRAPH_INSTRUCTIONS` mentions `kind="c4"`; constants exported; parity tests pass.

## Validation Commands
- `pytest packages/ai-parrot/tests/outputs/a2ui/test_components_graph_c4.py -q`
- `pytest packages/ai-parrot/tests/outputs/a2ui/test_components_graph.py -q`
- `pytest packages/ai-parrot/tests/outputs/a2ui/test_catalog_parity.py -q`

---

## Test Specification
Spec §4 M4 rows.

---

## Agent Instructions

Standard FEAT-754 procedure; close with `scripts/sdd/close_task.sh TASK-4788 a2ui-c4-diagrams verified`.

---

## Completion Note

*(Agent fills this in when done)*

**Completed by**:
**Date**:
**Notes**:

**Deviations from spec**: none
