# TASK-4789: Builder — `build_graph(level=)` + `build_c4_diagram`

**Feature**: FEAT-754 — C4 architecture diagrams as a `Graph` kind
**Spec**: `sdd/specs/a2ui-c4-diagrams.spec.md`
**Status**: pending
**Priority**: medium
**Estimated effort**: S (< 2h)
**Depends-on**: TASK-4787
**Assigned-to**: unassigned

---

## Context

Spec §3 Module 5. Thin delegation: `build_graph` gains a `level` keyword passed into `GraphSpec`;
`build_c4_diagram` wraps it (`groups=boundaries`, `kind="c4"`, `surface_id="c4-diagram"`). Positions
come from `compute_positions`, which dispatches to the C4 layout (TASK-4787). FEAT-755 also edits
`builders.py` — keep the diff to the three anchored lines plus one new function.

---

## Scope

- Import `C4Level` in the existing `from parrot.outputs.a2ui.graph import (...)` block.
- Add `"build_c4_diagram"` to `__all__`.
- Add `level: C4Level | None = None` after `selection` in `build_graph`; pass `level=level` to `GraphSpec(...)`; document it.
- Add `build_c4_diagram` (signature fixed in spec §3 M5).
- Create `test_builders_c4.py` (spec §4 M5 rows + the action half of `test_c4_node_state_and_action_still_work`).

**NOT in scope**: `parrot/outputs/a2ui/__init__.py` (exports no builders).

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot/src/parrot/outputs/a2ui/builders.py` | MODIFY | `level` + `build_c4_diagram` |
| `packages/ai-parrot/tests/outputs/a2ui/test_builders_c4.py` | CREATE | M5 tests |

---

## Codebase Contract (Anti-Hallucination)

### Verified Imports
```python
from parrot.outputs.a2ui.builders import build_graph  # verified: builders.py:330
from parrot.outputs.a2ui.graph import C4Level  # created by TASK-4784 (graph/__init__.py)
from parrot.outputs.a2ui.catalog import ProducerOrigin  # verified: re-exported, used at builders.py:37-41
from parrot.outputs.a2ui.catalog.base import CatalogValidationError, ACTION_NOT_ALLOWED_FOR_LLM  # verified: catalog/base.py:317,78
from parrot.outputs.a2ui.catalog.viz_core import VIZ_CORE_CATALOG_ID  # verified: viz_core/__init__.py:28
from parrot.outputs.a2ui.models import Action, CreateSurface  # verified: builders.py:55
```

### Existing Signatures to Use
```python
# packages/ai-parrot/src/parrot/outputs/a2ui/builders.py (verified at 65144d730)
from parrot.outputs.a2ui.graph import ( Direction, ..., compute_positions, )   # 43-54 (`    compute_positions,` at 53)
__all__ = [ ..., "build_graph", ... ]                                          # 57-68 (`    "build_graph",` at 61)
def build_graph(*, nodes, edges, kind: GraphKind = "flowchart", direction: Direction = "TB", title=None,
                accessible_description=None, size: VizSize = "tile", groups=None, layout=None,
                selection: GraphSelection | dict[str, Any] | None = None,   # line 341
                data_binding=None, data_model=None, action: Action | None = None, compute_layout: bool = True,
                surface_id: str = "graph", origin: ProducerOrigin = ProducerOrigin.TOOL) -> CreateSurface   # 330-348
    # GraphSpec(...) 414-425 (`        selection=selection_model,` at 424); compute_positions 436; build_surface 449-455
```

### Does NOT Exist
- ~~`build_c4_diagram`~~ — created HERE.
- ~~builder exports in `parrot/outputs/a2ui/__init__.py`~~ — none; add nothing there.

---

## Complexity Contract

```json
{
  "schema_version": 1,
  "targets": [
    {"path": "packages/ai-parrot/src/parrot/outputs/a2ui/builders.py", "action": "MODIFY"},
    {"path": "packages/ai-parrot/tests/outputs/a2ui/test_builders_c4.py", "action": "CREATE"}
  ],
  "contract_symbols": [
    "sym:packages/ai-parrot/src/parrot/outputs/a2ui/builders.py#build_graph"
  ]
}
```

---

## Implementation Blueprint

### Steps (in order)
1. Add the import, `__all__` entry, keyword and pass-through — *why*: spec §7 asks for a mechanical merge with FEAT-755.
2. Append `build_c4_diagram` directly after `build_graph`.
3. Write tests.

### `packages/ai-parrot/src/parrot/outputs/a2ui/builders.py` (MODIFY)
```python
# occurrences: 1 (verified: grep -c '    compute_positions,' builders.py) — BEFORE it, inside the import block:
    C4Level,
# FILL IN: keep the import list's existing ordering convention

# occurrences: 1 (verified: grep -c '    "build_graph",' builders.py) — AFTER it? NO: __all__ is alphabetical →
# insert `    "build_c4_diagram",` BEFORE `    "build_card",` if alphabetical. FILL IN: keep the existing order rule

# occurrences: 1 (verified: grep -c '    selection: GraphSelection | dict\[str, Any\] | None = None,' builders.py) — AFTER line 341:
    level: C4Level | None = None,

# occurrences: 1 (verified: grep -c '        selection=selection_model,' builders.py) — AFTER line 424:
        level=level,

# Docstring of build_graph: add an Args entry
#     level: ``GraphSpec.level`` — required when ``kind="c4"`` (validated by the model).
```
```python
def build_c4_diagram(
    *,
    level: C4Level,
    nodes: list[GraphNode | dict[str, Any]],
    edges: list[GraphEdge | dict[str, Any]],
    boundaries: list[GraphGroup | dict[str, Any]] | None = None,
    direction: Direction = "TB",
    title: str | None = None,
    accessible_description: str | None = None,
    size: VizSize = "tile",
    layout: GraphLayout | dict[str, Any] | None = None,
    selection: GraphSelection | dict[str, Any] | None = None,
    data_binding: str | None = None,
    data_model: dict[str, Any] | None = None,
    action: Action | None = None,
    compute_layout: bool = True,
    surface_id: str = "c4-diagram",
    origin: ProducerOrigin = ProducerOrigin.TOOL,
) -> CreateSurface:
    """Build a viz-core ``Graph`` envelope with ``kind="c4"``.

    Thin wrapper over :func:`build_graph` (``groups=boundaries``); every validation, layout and origin
    rule is ``build_graph``'s.
    """
    return build_graph(
        nodes=nodes, edges=edges, kind="c4", level=level, direction=direction, title=title,
        accessible_description=accessible_description, size=size, groups=boundaries, layout=layout,
        selection=selection, data_binding=data_binding, data_model=data_model, action=action,
        compute_layout=compute_layout, surface_id=surface_id, origin=origin,
    )
# FILL IN: match build_graph's actual type hints for nodes/edges/groups/layout (builders.py:330-348)
```

### `packages/ai-parrot/tests/outputs/a2ui/test_builders_c4.py` (CREATE)
```python
"""FEAT-754 M5 — build_c4_diagram / build_graph(level=)."""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from parrot.outputs.a2ui import builders
from parrot.outputs.a2ui.builders import build_c4_diagram, build_graph
from parrot.outputs.a2ui.catalog.viz_core import VIZ_CORE_CATALOG_ID

FIXTURE = Path(__file__).resolve().parent / "fixtures" / "c4_container_diagram.json"


def test_build_c4_diagram_fills_positions_and_catalog_id() -> None: ...
def test_build_graph_level_passthrough() -> None: ...
def test_build_c4_diagram_in_all() -> None:
    assert "build_c4_diagram" in builders.__all__
def test_build_c4_diagram_action_tool_origin_only() -> None: ...
def test_c4_node_state_and_action_still_work() -> None: ...
# FILL IN: bodies — map fixture "groups" → boundaries=; read the root component's properties the same way
#          test_builders_graph.py does
```

### FILL IN checklist
- [ ] import/`__all__` ordering; exact type hints; test bodies

---

## Acceptance Criteria

- [ ] `build_c4_diagram(...)` returns a validated `CreateSurface` with `catalogId == VIZ_CORE_CATALOG_ID`, `kind == "c4"`, `level`, complete positions.
- [ ] `build_graph(level=...)` equivalent; `"build_c4_diagram" in builders.__all__`; LLM origin + action rejected.
- [ ] `test_builders_graph.py` passes unchanged.

## Validation Commands
- `pytest packages/ai-parrot/tests/outputs/a2ui/test_builders_c4.py -q`
- `pytest packages/ai-parrot/tests/outputs/a2ui/test_builders_graph.py -q`

---

## Test Specification
Spec §4 M5 rows.

---

## Agent Instructions

Standard FEAT-754 procedure; close with `scripts/sdd/close_task.sh TASK-4789 a2ui-c4-diagrams verified`.

---

## Completion Note

*(Agent fills this in when done)*

**Completed by**: opus (native), attempt 1
**Date**: 2026-10-27
**Notes**: Engine merge-tier validation (wave 3: 4786/4788/4789) green: 163 passed, outcome=completed. Closed with close_task.sh (not finalize_task) because no formal review EvidenceRef was recorded for this delivery; sdd-worker read the merge result and relied on the green merge-tier run.

**Deviations from spec**: none
