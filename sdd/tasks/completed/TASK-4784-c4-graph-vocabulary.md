# TASK-4784: C4 vocabulary on the GraphSpec models (V1–V7) + shared fixture

**Feature**: FEAT-754 — C4 architecture diagrams as a `Graph` kind
**Spec**: `sdd/specs/a2ui-c4-diagrams.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: M (2-4h)
**Depends-on**: none
**Assigned-to**: unassigned

---

## Context

Spec §3 Module 1 and §2 Data Models. Every other Python module of FEAT-754 (codec, layout,
lowering, builder) reads the C4 fields this task adds to the existing `GraphSpec` family —
there is no parallel C4 model. This task also creates the ONE shared C4 fixture
(spec §4 "Test Data / Fixtures") so downstream tasks consume it instead of each inventing one.

---

## Scope

- Add `"c4"` to `GraphKind`; add the Literals `C4Level`, `C4ElementType`, `C4BoundaryType`, `RelHint`.
- Add fields: `GraphNode.c4_type` (alias `c4Type`), `.technology`, `.description`;
  `GraphEdge.technology`, `.hint`, `.bidirectional`; `GraphGroup.parent`, `.c4_type` (alias `c4Type`)
  and `populate_by_name=True` on `GraphGroup`; `GraphLayout.shape_in_row` (alias `shapeInRow`, `ge=1`),
  `.boundary_in_row` (alias `boundaryInRow`, `ge=1`); `GraphSpec.level`.
- Append validators V1–V7 (spec §2 Data Models, lines 327–338) to `GraphSpec._validate_graph`,
  plus helper `_group_parent_cycle()` (iterative).
- Export the four new Literals from `models.__all__` and `graph/__init__.py`.
- Create `tests/outputs/a2ui/fixtures/c4_container_diagram.json` (content fixed in spec §4).
- Create `tests/outputs/a2ui/graph/test_models_c4.py` with the M1 tests of spec §4.

**NOT in scope**: the Mermaid codec (TASK-4785/4786), layout (TASK-4787), lowering (TASK-4788),
builder (TASK-4789), re-exports of `to_mermaid_c4`/`from_mermaid_c4`/`compute_c4_positions` (TASK-4793),
any UI change. Do NOT add `Field(description=...)` anywhere.

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot/src/parrot/outputs/a2ui/graph/models.py` | MODIFY | Literals, fields, V1–V7, `_group_parent_cycle` |
| `packages/ai-parrot/src/parrot/outputs/a2ui/graph/__init__.py` | MODIFY | re-export the four Literals |
| `packages/ai-parrot/tests/outputs/a2ui/fixtures/c4_container_diagram.json` | CREATE | shared C4 fixture |
| `packages/ai-parrot/tests/outputs/a2ui/graph/test_models_c4.py` | CREATE | M1 unit tests |

---

## Codebase Contract (Anti-Hallucination)

### Verified Imports
```python
from parrot.outputs.a2ui.graph.models import GraphEdge, GraphGroup, GraphLayout, GraphNode, GraphSpec  # verified: models.py:87,110,141,57,179
from parrot.outputs.a2ui.graph import GraphSpec  # verified: graph/__init__.py:13-28
from pydantic import ValidationError  # pydantic v2, already used by models.py
```

### Existing Signatures to Use
```python
# packages/ai-parrot/src/parrot/outputs/a2ui/graph/models.py  (verified at 65144d730)
__all__ = [ ... "VizSize", ]                                        # lines 30-45; "VizSize" at 44
GraphKind = Literal["flowchart", "state", "sequence", "dag"]        # line 47
class GraphNode(BaseModel):   model_config = ConfigDict(extra="forbid")              # 57 / 76
    id; label; shape; group; state; icon; meta: Optional[dict[str, Any]] = None      # 78-84
class GraphEdge(BaseModel):   ConfigDict(extra="forbid", populate_by_name=True)       # 87 / 101
    from_ = Field(alias="from"); to; label; kind; condition: Optional[str] = None   # 103-107
class GraphGroup(BaseModel):  model_config = ConfigDict(extra="forbid")              # 110 / 120 (NO populate_by_name)
    id: str; label: Optional[str]; nodes: list[str]                                  # 122-124
class GraphLayout(BaseModel): ConfigDict(extra="forbid", populate_by_name=True)       # 141 / 157
    ...; positions: Optional[dict[str, Position]] = None                             # 162
class GraphSpec(BaseModel):   ConfigDict(extra="forbid", populate_by_name=True)       # 179 / 214
    ...; data: Optional[dict[str, dict[str, Any]]] = None                            # 226
    @model_validator(mode="after") def _validate_graph(self) -> GraphSpec            # 229
        # groups check 257-268; `if self.kind == "dag" and self._has_cycle():` 270;
        # manual positions block 273-279; `return self` 281
    def _has_cycle(self) -> bool                                                     # 283 (iterative 3-colour DFS — style to mirror)

# packages/ai-parrot/src/parrot/outputs/a2ui/graph/__init__.py
from .mermaid import MermaidCodecError, from_mermaid, to_mermaid    # line 12
from .models import ( Direction, ... VizSize, )                    # lines 13-28
__all__ = [ ... "VizSize" ... ]                                     # 30-52 ("VizSize" at 48)

# packages/ai-parrot/tests/outputs/a2ui/graph/test_models.py:155  test_no_forbidden_field_names_on_any_graph_model (must keep passing)
# packages/ai-parrot/tests/outputs/a2ui/conformance/test_all_emitters.py:472 — fixture loading pattern: json.loads(Path(...).read_text())
```

### Does NOT Exist
- ~~`C4Level`, `C4ElementType`, `C4BoundaryType`, `RelHint`~~, ~~`GraphSpec.level`~~, ~~`GraphGroup.parent`~~ — created HERE.
- ~~`GraphSpec.boundaries`~~ — boundaries ARE `groups`.
- ~~`neighbor` / `back_neighbor` RelHint values~~ — must be rejected.
- ~~`tests/outputs/a2ui/graph/conftest.py`~~ — do NOT create; load the fixture with `json.loads(Path(...).read_text())`.
- ~~`GraphLayout.group_boxes`~~ — never on the wire.

---

## Complexity Contract

```json
{
  "schema_version": 1,
  "targets": [
    {"path": "packages/ai-parrot/src/parrot/outputs/a2ui/graph/models.py", "action": "MODIFY"},
    {"path": "packages/ai-parrot/src/parrot/outputs/a2ui/graph/__init__.py", "action": "MODIFY"},
    {"path": "packages/ai-parrot/tests/outputs/a2ui/fixtures/c4_container_diagram.json", "action": "CREATE"},
    {"path": "packages/ai-parrot/tests/outputs/a2ui/graph/test_models_c4.py", "action": "CREATE"}
  ],
  "contract_symbols": [
    "sym:packages/ai-parrot/src/parrot/outputs/a2ui/graph/models.py#GraphNode",
    "sym:packages/ai-parrot/src/parrot/outputs/a2ui/graph/models.py#GraphEdge",
    "sym:packages/ai-parrot/src/parrot/outputs/a2ui/graph/models.py#GraphGroup",
    "sym:packages/ai-parrot/src/parrot/outputs/a2ui/graph/models.py#GraphLayout",
    "sym:packages/ai-parrot/src/parrot/outputs/a2ui/graph/models.py#GraphSpec",
    "sym:packages/ai-parrot/src/parrot/outputs/a2ui/graph/models.py#GraphSpec._validate_graph"
  ]
}
```

---

## Implementation Notes

### Key Constraints
- No new field name or enum value may contain colour/color/palette/font, `hex` or `px`
  (`test_catalog_parity.py:77-87`); add no `Field(description=...)`.
- All validation failures are `ValueError` raised inside `_validate_graph` (pydantic wraps them into `ValidationError`).
- `technology`/`description` are allowed on every kind (V2 does not cover them); V7 restricts technology only for C4 person/system families.

---

## Implementation Blueprint

### Steps (in order)
1. Edit `GraphKind` and add the four Literals right below it — *why*: every field below references them.
2. Append the new fields after each model's last field (anchors below) — *why*: additive, keeps existing field order and wire output.
3. Change `GraphGroup.model_config` to `ConfigDict(extra="forbid", populate_by_name=True)` — *why*: `c4_type` has an alias and Python constructors use the field name.
4. Insert V1–V7 between the manual-positions block and `return self` — *why*: existing invariants (unknown nodes, membership) must fire first so V3 messages are about groups only.
5. Add `_group_parent_cycle` after `_has_cycle` — *why*: V3 acyclicity, iterative like `_has_cycle`.
6. Extend `__all__` in models.py and the import/`__all__` in `graph/__init__.py`.
7. Write the fixture verbatim from spec §4 and the tests; run validation.

### `packages/ai-parrot/src/parrot/outputs/a2ui/graph/models.py` (MODIFY)
```python
# occurrences: 1 (verified: grep -c 'GraphKind = Literal\["flowchart", "state", "sequence", "dag"\]' models.py)
# REPLACE line 47 with:
GraphKind = Literal["flowchart", "state", "sequence", "dag", "c4"]
# ... and insert right after the VizSize Literal (line 54):
#: C4 abstraction level (Mermaid header: C4Context / C4Container / C4Component / C4Dynamic).
C4Level = Literal["context", "container", "component", "dynamic"]
#: C4 element type — exactly the 20 Mermaid C4 element macros, snake_case on the wire.
C4ElementType = Literal[
    "person", "person_ext", "system", "system_ext", "system_db", "system_db_ext",
    "system_queue", "system_queue_ext", "container", "container_ext", "container_db",
    "container_db_ext", "container_queue", "container_queue_ext", "component",
    "component_ext", "component_db", "component_db_ext", "component_queue", "component_queue_ext",
]
#: C4 boundary type — Enterprise_Boundary / System_Boundary / Container_Boundary / Boundary (generic).
C4BoundaryType = Literal["enterprise", "system", "container", "generic"]
#: Relationship placement hint — Mermaid Rel_U / Rel_D / Rel_L / Rel_R / Rel_Back.
RelHint = Literal["up", "down", "left", "right", "back"]

# occurrences: 1 (verified: grep -c '    "VizSize",' models.py) — AFTER line 44 in __all__:
    "C4BoundaryType",
    "C4ElementType",
    "C4Level",
    "RelHint",
# FILL IN: keep __all__ alphabetical if it is today — bounded by existing ordering

# occurrences: 1 — AFTER `    meta: Optional[dict[str, Any]] = None` (models.py:84)
    c4_type: Optional[C4ElementType] = Field(default=None, alias="c4Type")
    technology: Optional[str] = None
    description: Optional[str] = None
# NOTE: GraphNode has extra="forbid" without populate_by_name — FILL IN: add populate_by_name=True
#       to GraphNode.model_config (line 76) too, because c4_type has an alias — bounded by AC-1.

# occurrences: 1 — AFTER `    condition: Optional[str] = None` (models.py:107)
    technology: Optional[str] = None
    hint: Optional[RelHint] = None
    bidirectional: Optional[bool] = None

# occurrences: 1 — AFTER `    nodes: list[str]` (models.py:124)
    parent: Optional[str] = None
    c4_type: Optional[C4BoundaryType] = Field(default=None, alias="c4Type")

# occurrences: 1 — AFTER `    positions: Optional[dict[str, Position]] = None` (models.py:162)
    shape_in_row: Optional[int] = Field(default=None, alias="shapeInRow", ge=1)
    boundary_in_row: Optional[int] = Field(default=None, alias="boundaryInRow", ge=1)

# occurrences: 1 — AFTER `    data: Optional[dict[str, dict[str, Any]]] = None` (models.py:226)
    level: Optional[C4Level] = None
```

```python
# INSIDE _validate_graph — after the manual-positions block, BEFORE `        return self` (models.py:281;
# `return self` alone occurs more than once in the file — attach after the block that starts with
# `        if self.layout is not None and self.layout.engine == "manual":`)
        self._validate_c4()

# NEW method on GraphSpec (keeps _validate_graph short):
    def _validate_c4(self) -> None:
        """V1–V7 (spec §2 Data Models). Raises ValueError on the first violation."""
        is_c4 = self.kind == "c4"
        groups = self.groups or []
        # V1: c4 => level set and every node has c4_type
        # FILL IN: V1 — message names the offending node id
        # V2: non-c4 => no level / node c4_type / edge hint|bidirectional / group parent|c4_type /
        #     layout shape_in_row|boundary_in_row
        # FILL IN: V2 — message names the field and says it is only valid for kind='c4'
        # V3: group ids unique; parent exists and != self; chain acyclic via _group_parent_cycle()
        # FILL IN: V3 — applies to ALL kinds (duplicate group ids now rejected everywhere)
        # V4: shape_in_row and boundary_in_row both set or both None
        # V5: level == "dynamic" => no edge hint / bidirectional
        # V6: c4 and edge.bidirectional is True => edge.hint is None
        # V7: c4 and node.c4_type startswith ("person", "system") => node.technology is None
        # FILL IN: V4–V7 — bounded by spec §2 lines 327-338

    def _group_parent_cycle(self) -> Optional[str]:
        """Return the first group id whose ``parent`` chain loops back on itself, else None (iterative)."""
        parents = {group.id: group.parent for group in self.groups or []}
        # FILL IN: for each id walk parents with a visited set; return the id when revisited — no recursion
        return None
```
**Why this shape**: the spec fixes field names, aliases and the V1–V7 rules; a separate `_validate_c4`
keeps the existing validator readable. V3's unknown-parent / self-parent checks must run before the
cycle walk so the walk only sees existing ids.

### `packages/ai-parrot/src/parrot/outputs/a2ui/graph/__init__.py` (MODIFY)
```python
# occurrences: 1 (verified: grep -c '"VizSize"' graph/__init__.py → line 48 in __all__)
# Add C4BoundaryType, C4ElementType, C4Level, RelHint to the `from .models import (...)` block (lines 13-28)
# and to __all__ (lines 30-52).
```

### `packages/ai-parrot/tests/outputs/a2ui/fixtures/c4_container_diagram.json` (CREATE)
Copy verbatim the JSON in spec §4 "Test Data / Fixtures" (lines 827-845), pretty-printed with 2-space indent.

### `packages/ai-parrot/tests/outputs/a2ui/graph/test_models_c4.py` (CREATE)
```python
"""FEAT-754 M1 — C4 vocabulary and validators V1–V7 on GraphSpec."""
from __future__ import annotations

import json
from pathlib import Path

import pytest
from pydantic import ValidationError

from parrot.outputs.a2ui.graph.models import GraphSpec

FIXTURE = Path(__file__).resolve().parent.parent / "fixtures" / "c4_container_diagram.json"


def _c4() -> dict:
    return json.loads(FIXTURE.read_text())


def test_fixture_validates() -> None:
    spec = GraphSpec.model_validate(_c4())
    assert spec.kind == "c4" and spec.level == "container"


def test_c4_requires_level_and_c4_type() -> None: ...           # FILL IN (V1)
def test_c4_fields_rejected_on_other_kinds() -> None: ...       # FILL IN (V2; technology/description accepted on flowchart)
def test_group_parent_must_exist_and_be_acyclic() -> None: ...  # FILL IN (V3 + duplicate group ids)
def test_shape_in_row_and_boundary_in_row_together() -> None: ...  # FILL IN (V4 + ge=1)
def test_dynamic_rejects_hint_and_bidirectional() -> None: ...  # FILL IN (V5)
def test_c4_rejects_bidirectional_hint_and_person_system_technology() -> None: ...  # FILL IN (V6, V7)
def test_c4_rejects_neighbor_hints() -> None: ...               # FILL IN
def test_c4_node_state_still_works() -> None: ...               # FILL IN: state="failed" on a C4 node validates
```
**Why**: test names fixed by spec §4. The `build_c4_diagram(action=...)` half of
`test_c4_node_state_and_action_still_work` belongs to TASK-4789 (builder does not exist yet).

### FILL IN checklist
- [ ] `GraphNode.model_config` gains `populate_by_name=True` (alias added)
- [ ] `_validate_c4` V1–V7 bodies and messages — bounded by spec §2 lines 327-338
- [ ] `_group_parent_cycle` iterative walk
- [ ] every test body in `test_models_c4.py`

---

## Acceptance Criteria

- [ ] `GraphKind` accepts `"c4"`; fields/aliases exactly as spec §2; V1–V7 raise `ValidationError`.
- [ ] Fixture validates as a `GraphSpec`.
- [ ] Existing `graph/test_models.py` (incl. `test_no_forbidden_field_names_on_any_graph_model`) and `test_catalog_parity.py` pass unchanged.
- [ ] `ruff check` and `black --check` clean on touched Python files.

## Validation Commands
- `pytest packages/ai-parrot/tests/outputs/a2ui/graph/test_models_c4.py -q`
- `pytest packages/ai-parrot/tests/outputs/a2ui/graph/test_models.py -q`
- `pytest packages/ai-parrot/tests/outputs/a2ui/test_catalog_parity.py -q`

---

## Test Specification
See the blueprint block for `test_models_c4.py`; spec §4 rows tagged M1.

---

## Agent Instructions

1. Work in the feature worktree (`python -m scripts.sdd.ensure_worktree --slug a2ui-c4-diagrams --feature-id FEAT-754`).
2. Read the spec; verify the Codebase Contract; mark the task in-progress in `sdd/tasks/index/a2ui-c4-diagrams.json`.
3. Implement from the blueprint, complete every `FILL IN`, run the Validation Commands with `PYTHONPATH=packages/ai-parrot/src`.
4. Commit only the listed files; close with `scripts/sdd/close_task.sh TASK-4784 a2ui-c4-diagrams verified`; fill the Completion Note.

---

## Completion Note

*(Agent fills this in when done)*

**Completed by**: gpt-5.6-terra (codex), attempt 1
**Date**: 2026-10-27
**Notes**: pytest wave-1 merge tier: 17 passed (engine run); vitest A2UIGraph+ECharts 17/17 passed (run by sdd-worker). Engine task/merge-tier gate's vitest runner stayed red (`pnpm exec vitest`: "Command vitest not found" in the validation sandbox, exit 254) although the same command passes from a normal shell; merged on explicit user authorization (manual `git merge --no-ff`) with sdd-worker-run test evidence. finalize_task not used: it requires a green engine validation ref.

**Deviations from spec**: none
