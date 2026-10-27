# TASK-4785: Mermaid C4 emitter (`to_mermaid_c4`) + `to_mermaid` dispatch

**Feature**: FEAT-754 — C4 architecture diagrams as a `Graph` kind
**Spec**: `sdd/specs/a2ui-c4-diagrams.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: M (2-4h)
**Depends-on**: TASK-4784
**Assigned-to**: unassigned

---

## Context

Spec §3 Module 2, emission half. The codec is split in two tasks: this one creates
`graph/mermaid_c4.py` with the macro tables, `C4_LOSSY_FIELDS` and the canonical emitter, and
routes `to_mermaid(spec)` for `kind="c4"`. TASK-4786 adds the parser to the same file.
TASK-4788 (lowering) needs only this half (`graph-source` text).

---

## Scope

- Create `graph/mermaid_c4.py` with `__all__`, `C4_LOSSY_FIELDS`, `_LEVEL_HEADER`, `_ELEMENT_MACRO`,
  `_BOUNDARY_MACRO`, `_REL_MACRO`, `to_mermaid_c4`, `_emit_element`, `_emit_boundary_open`, `_emit_rel`.
- Implement the canonical emission grammar of spec §3 M2 (header, title, elements with nested
  boundaries at 4-space indent per depth, relationships, `UpdateLayoutConfig`), trailing newline.
- Add the `kind == "c4"` branch to `to_mermaid` (function-local import) and list the C4 dialect in
  `mermaid.py`'s module docstring.
- Create `graph/test_mermaid_c4.py` with emission tests.

**NOT in scope**: `from_mermaid_c4` and the `from_mermaid` dispatch (TASK-4786); round-trip tests
(TASK-4786); re-export from `graph/__init__.py` (TASK-4793).

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot/src/parrot/outputs/a2ui/graph/mermaid_c4.py` | CREATE | tables + emitter |
| `packages/ai-parrot/src/parrot/outputs/a2ui/graph/mermaid.py` | MODIFY | `to_mermaid` C4 dispatch + docstring |
| `packages/ai-parrot/tests/outputs/a2ui/graph/test_mermaid_c4.py` | CREATE | emission tests |

---

## Codebase Contract (Anti-Hallucination)

### Verified Imports
```python
from parrot.outputs.a2ui.graph.mermaid import MermaidCodecError, _escape_label, _IDENT  # verified: mermaid.py:126,146,109
from parrot.outputs.a2ui.graph.models import GraphEdge, GraphGroup, GraphNode, GraphSpec  # verified: models.py:87,110,57,179
from parrot.outputs.a2ui.graph.mermaid import to_mermaid  # verified: mermaid.py:206
```

### Existing Signatures to Use
```python
# packages/ai-parrot/src/parrot/outputs/a2ui/graph/mermaid.py (verified at 65144d730)
# docstring lines 1-51; label collapsing rule (label == id → None) documented at 38-40
_IDENT = r"[A-Za-z_][A-Za-z0-9_]*"                                 # line 109
class MermaidCodecError(CatalogValidationError):
    def __init__(self, line_no: int, line: str, reason: str)       # lines 126-143
def _escape_label(label: str) -> str                               # line 146 ('"' → '#quot;')
def to_mermaid(spec: GraphSpec) -> str                             # line 206
    if spec.kind == "sequence":                                    # line 218 (C4 branch goes BEFORE it)

# Models (after TASK-4784): GraphSpec.level, GraphNode.c4_type/technology/description,
# GraphEdge.technology/hint/bidirectional, GraphGroup.parent/c4_type, GraphLayout.shape_in_row/boundary_in_row
```

### Does NOT Exist
- ~~`parrot.outputs.a2ui.graph.mermaid_c4`~~ — created HERE.
- ~~`Rel_Neighbor` / `Rel_Back_Neighbor` emission~~ — never emitted.
- ~~`UpdateElementStyle` / `UpdateRelStyle` / `$sprite` / `$tags` / `$link`~~ — never emitted.
- ~~a `direction` line in C4~~ — C4 has no direction form.

---

## Complexity Contract

```json
{
  "schema_version": 1,
  "targets": [
    {"path": "packages/ai-parrot/src/parrot/outputs/a2ui/graph/mermaid_c4.py", "action": "CREATE"},
    {"path": "packages/ai-parrot/src/parrot/outputs/a2ui/graph/mermaid.py", "action": "MODIFY"},
    {"path": "packages/ai-parrot/tests/outputs/a2ui/graph/test_mermaid_c4.py", "action": "CREATE"}
  ],
  "contract_symbols": [
    "sym:packages/ai-parrot/src/parrot/outputs/a2ui/graph/mermaid.py#to_mermaid",
    "sym:packages/ai-parrot/src/parrot/outputs/a2ui/graph/mermaid.py#_escape_label",
    "sym:packages/ai-parrot/src/parrot/outputs/a2ui/graph/mermaid.py#MermaidCodecError"
  ]
}
```

---

## Implementation Notes

### Key Constraints
- Emission order (spec §3 M2): ungrouped nodes (input order) → top-level boundaries in `groups[]` order;
  inside a boundary its direct members (`group.nodes` order) then child boundaries (`groups[]` order).
- Person/System args `(id, "label", "description")`; Container/Component `(id, "label", "technology", "description")`;
  trailing unset args omitted; unset technology before a set description → `""`; label defaults to id.
- Relationships after all elements in `edges[]` order; `level == "dynamic"` → `RelIndex("<n>", ...)` 1-based.
  Rel label is positional-required → `""` when None.
- `UpdateLayoutConfig($c4ShapeInRow="N", $c4BoundaryInRow="M")` last, only when both set.
- Must not mutate the caller's model.

---

## Implementation Blueprint

### Steps (in order)
1. Create `mermaid_c4.py` with the tables — *why*: the parser (TASK-4786) inverts the same dicts.
2. Implement `to_mermaid_c4` and the three `_emit_*` helpers.
3. Insert the dispatch in `to_mermaid` with a function-local import — *why*: `mermaid_c4` imports `mermaid`, a top-level import would cycle.
4. Write emission tests against the shared fixture.

### `packages/ai-parrot/src/parrot/outputs/a2ui/graph/mermaid_c4.py` (CREATE)
```python
"""Mermaid C4 dialect codec for ``GraphSpec(kind="c4")`` (FEAT-754, spec §3 Module 2).

Dependency-free like :mod:`.mermaid`. Emits C4Context / C4Container / C4Component / C4Dynamic
source; the supported subset and the lossy fields are documented in ``docs/outputs/a2ui-v1.md``.
"""

from __future__ import annotations

from typing import Optional

from .mermaid import MermaidCodecError, _escape_label, _IDENT  # noqa: F401  (parser half uses the rest)
from .models import GraphEdge, GraphGroup, GraphNode, GraphSpec

__all__ = ["C4_LOSSY_FIELDS", "from_mermaid_c4", "to_mermaid_c4"]
# FILL IN: until TASK-4786 lands, omit "from_mermaid_c4" from __all__ (ruff F822) — bounded by ruff clean

#: GraphSpec fields (dotted for nested) with no Mermaid C4 representation — the "modulo" set of the
#: round-trip contract. Dotted paths, NOT a pydantic ``exclude`` argument.
C4_LOSSY_FIELDS: frozenset[str] = frozenset(
    {
        "accessible_description", "size", "direction", "selection", "data",
        "layout.engine", "layout.rank_sep", "layout.node_sep", "layout.positions",
        "nodes.shape", "nodes.state", "nodes.icon", "nodes.meta", "nodes.group",
        "edges.kind", "edges.condition",
    }
)

_LEVEL_HEADER: dict[str, str] = {
    "context": "C4Context", "container": "C4Container", "component": "C4Component", "dynamic": "C4Dynamic",
}
_ELEMENT_MACRO: dict[str, str] = {
    # FILL IN: the 20 entries of the spec §3 M2 table (person→Person … component_queue_ext→ComponentQueue_Ext)
}
_MACRO_ELEMENT: dict[str, str] = {macro: c4 for c4, macro in _ELEMENT_MACRO.items()}
_BOUNDARY_MACRO: dict[Optional[str], str] = {
    "enterprise": "Enterprise_Boundary", "system": "System_Boundary", "container": "Container_Boundary",
    "generic": "Boundary", None: "Boundary",
}
_REL_MACRO: dict[tuple[bool, Optional[str]], str] = {
    (True, None): "BiRel", (False, None): "Rel", (False, "back"): "Rel_Back",
    (False, "up"): "Rel_U", (False, "down"): "Rel_D", (False, "left"): "Rel_L", (False, "right"): "Rel_R",
}
_INDENT = "    "


def _quote(value: Optional[str]) -> str:
    """Double-quote a macro string argument, escaping ``"`` as ``#quot;``."""
    # FILL IN: return '"' + (value or "").replace('"', "#quot;") + '"' — keep consistent with _escape_label's #quot;
    raise NotImplementedError


def _emit_element(node: GraphNode, depth: int) -> str:
    """One element macro line at ``depth`` (4-space indent per level)."""
    # FILL IN: person*/system* → (id, label, description); container*/component* → (id, label, technology, description);
    #          drop trailing unset args; "" for unset technology before a set description — bounded by spec §3 M2
    raise NotImplementedError


def _emit_boundary_open(group: GraphGroup, depth: int) -> str:
    """``<Macro>(id, "label") {`` line for a boundary."""
    return f'{_INDENT * depth}{_BOUNDARY_MACRO[group.c4_type]}({group.id}, {_quote(group.label or group.id)}) {{'


def _emit_rel(edge: GraphEdge, index: int, dynamic: bool) -> str:
    """One relationship line; ``index`` is the 1-based position in ``edges[]`` (used only when ``dynamic``)."""
    # FILL IN: dynamic → RelIndex("<index>", from, to, "label"[, "technology"]);
    #          else _REL_MACRO[(bool(edge.bidirectional), edge.hint)]; technology omitted when unset
    raise NotImplementedError


def to_mermaid_c4(spec: GraphSpec) -> str:
    """Emit canonical Mermaid C4 source for a ``kind="c4"`` spec (trailing newline included).

    Raises:
        ValueError: if ``spec.kind != "c4"``.
    """
    if spec.kind != "c4":
        raise ValueError(f"to_mermaid_c4 requires kind='c4', got {spec.kind!r}")
    lines: list[str] = [_LEVEL_HEADER[spec.level]]
    if spec.title and spec.title.strip():
        lines.append(f"title {spec.title.rstrip()}")
    # FILL IN: element traversal (ungrouped first, then boundaries depth-first with "}" closers) — spec §3 M2
    # FILL IN: relationships in edges[] order via _emit_rel
    # FILL IN: UpdateLayoutConfig line when spec.layout and both counts set
    return "\n".join(lines) + "\n"
```
**Why this shape**: tables are module-level so the parser inverts them; the emitter is pure and
never mutates `spec`. `_quote` keeps the `#quot;` convention shared with `_escape_label`.

### `packages/ai-parrot/src/parrot/outputs/a2ui/graph/mermaid.py` (MODIFY)
```python
# occurrences: 1 (verified: grep -c '    if spec.kind == "sequence":' mermaid.py)
# BEFORE — insert above `    if spec.kind == "sequence":` (verified: mermaid.py:218)
    if spec.kind == "c4":
        # Function-local: mermaid_c4 imports this module (MermaidCodecError, label helpers).
        from .mermaid_c4 import to_mermaid_c4

        return to_mermaid_c4(spec)
```
Also add one paragraph to the module docstring (lines 1-51) naming the C4 dialect and pointing to `mermaid_c4`.

### `packages/ai-parrot/tests/outputs/a2ui/graph/test_mermaid_c4.py` (CREATE)
```python
"""FEAT-754 M2 — Mermaid C4 codec (emission half; TASK-4786 appends parser/round-trip tests)."""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from parrot.outputs.a2ui.graph.mermaid import to_mermaid
from parrot.outputs.a2ui.graph.mermaid_c4 import to_mermaid_c4
from parrot.outputs.a2ui.graph.models import GraphSpec

FIXTURE = Path(__file__).resolve().parent.parent / "fixtures" / "c4_container_diagram.json"


def _spec() -> GraphSpec:
    return GraphSpec.model_validate(json.loads(FIXTURE.read_text()))


def test_c4_fixture_emits_container_header() -> None:
    assert to_mermaid(_spec()).startswith("C4Container\n")


def test_c4_emission_exact_text() -> None: ...           # FILL IN: assert full expected text for the fixture
def test_c4_each_level_header_emits() -> None: ...       # FILL IN
def test_c4_all_twenty_element_macros_emit() -> None: ...  # FILL IN
def test_c4_nested_boundaries_indent() -> None: ...      # FILL IN: enterprise ⊃ system ⊃ container, 4-space indents
def test_c4_rel_macros_emit() -> None: ...               # FILL IN: every valid (bidirectional, hint) pair
def test_c4_dynamic_emits_relindex() -> None: ...        # FILL IN
def test_c4_update_layout_config_only_when_both_set() -> None: ...  # FILL IN
def test_c4_quotes_escape() -> None: ...                 # FILL IN: '"' → #quot;
def test_to_mermaid_c4_rejects_non_c4() -> None:
    with pytest.raises(ValueError):
        to_mermaid_c4(GraphSpec(nodes=[], edges=[]))
```

### FILL IN checklist
- [ ] `_ELEMENT_MACRO` 20 entries
- [ ] `_quote`, `_emit_element`, `_emit_rel` bodies
- [ ] traversal + relationships + `UpdateLayoutConfig` in `to_mermaid_c4`
- [ ] test bodies

---

## Acceptance Criteria

- [ ] `to_mermaid(fixture)` emits `C4Container` source using only the spec §3 M2 macros.
- [ ] Existing `graph/test_mermaid.py` passes unchanged.
- [ ] `ruff check` / `black --check` clean.

## Validation Commands
- `pytest packages/ai-parrot/tests/outputs/a2ui/graph/test_mermaid_c4.py -q`
- `pytest packages/ai-parrot/tests/outputs/a2ui/graph/test_mermaid.py -q`

---

## Test Specification
See blueprint; spec §4 rows tagged M2 (emission side).

---

## Agent Instructions

Same procedure as every FEAT-754 task: feature worktree, verify contract, mark in-progress, implement,
`PYTHONPATH=packages/ai-parrot/src` validation, commit listed files only,
`scripts/sdd/close_task.sh TASK-4785 a2ui-c4-diagrams verified`, Completion Note.

---

## Completion Note

*(Agent fills this in when done)*

**Completed by**: gpt-5.6-terra (codex), attempt 1
**Date**: 2026-10-27
**Notes**: wave-2 merge tier pytest: 136 passed (engine run); vitest A2UIGraph+ECharts 21/21 on the merged feature branch (sdd-worker run). The engine gate's vitest runner stayed red (`pnpm exec vitest`: "Command vitest not found" in the validation sandbox, exit 254) while the same command passes from a normal shell; closed with close_task.sh because finalize_task needs a green engine validation ref (user authorized merging UI tasks on sdd-worker-run test evidence).

**Deviations from spec**: none
