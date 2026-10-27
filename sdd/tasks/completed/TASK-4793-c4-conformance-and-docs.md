# TASK-4793: C4 re-exports, conformance sweep and documentation

**Feature**: FEAT-754 — C4 architecture diagrams as a `Graph` kind
**Spec**: `sdd/specs/a2ui-c4-diagrams.spec.md`
**Status**: pending
**Priority**: medium
**Estimated effort**: M (2-4h)
**Depends-on**: TASK-4786, TASK-4787, TASK-4788, TASK-4789, TASK-4792
**Assigned-to**: unassigned

---

## Context

Spec §3 Module 7 (plus the `graph/__init__.py` re-export lines of M2/M3, moved here so the codec and
layout tasks do not serialize on that file). Proves a C4 envelope is conformant, round-trips and
renders/degrades on every registered satellite renderer without touching
`packages/ai-parrot-visualizations/`, and documents the kind.

---

## Scope

- `graph/__init__.py`: re-export `from_mermaid_c4`, `to_mermaid_c4`, `C4_LOSSY_FIELDS`, `compute_c4_positions`; mention both modules in the package docstring.
- `test_all_emitters.py`: `_c4_envelope()` + `class TestC4GraphConformance` (3 tests) after `TestCatalogDefinitionIncludesGraph`.
- `docs/outputs/a2ui-v1.md`: section `### C4 architecture diagrams — kind="c4" (FEAT-754)` immediately BEFORE `### Renderer matrix`
  (vocabulary, boundaries-as-groups, V1–V7 table, lowering roles, Mermaid subset + lossy list, layout rules, renderer notes incl. explicit loss of nested satellite frames).
- `docs/frontend/agentdashboard-a2ui-reference.md` §5.4: C4 rows in the `Graph` prop table + one paragraph on the bundled renderer's C4 behaviour.

**NOT in scope**: any edit under `packages/ai-parrot-visualizations/`.

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot/src/parrot/outputs/a2ui/graph/__init__.py` | MODIFY | C4 codec/layout re-exports |
| `packages/ai-parrot/tests/outputs/a2ui/conformance/test_all_emitters.py` | MODIFY | `TestC4GraphConformance` |
| `docs/outputs/a2ui-v1.md` | MODIFY | C4 section |
| `docs/frontend/agentdashboard-a2ui-reference.md` | MODIFY | C4 prop rows + renderer paragraph |

---

## Codebase Contract (Anti-Hallucination)

### Verified Imports
```python
from parrot.outputs.a2ui.builders import build_c4_diagram  # created by TASK-4789
from parrot.outputs.a2ui.graph import GraphSpec, from_mermaid, to_mermaid  # verified: graph/__init__.py:12-28
from parrot.outputs.a2ui.graph.mermaid_c4 import C4_LOSSY_FIELDS, from_mermaid_c4, to_mermaid_c4  # TASK-4785/4786
from parrot.outputs.a2ui.graph.layout_c4 import compute_c4_positions  # TASK-4787
```

### Existing Signatures to Use
```python
# packages/ai-parrot/src/parrot/outputs/a2ui/graph/__init__.py (verified at 65144d730)
from .layout import MAX_STATIC_NODES, GraphTooLargeError, LayoutResult, compute_positions   # 11
from .mermaid import MermaidCodecError, from_mermaid, to_mermaid                           # 12
__all__ = [ ... ]                                                                          # 30-52

# packages/ai-parrot/tests/outputs/a2ui/conformance/test_all_emitters.py (verified at 65144d730)
# _assert_conformant helper; fixture load pattern json.loads(Path(...).read_text()) at :472
# class TestFlowToGraphToMermaidRoundtrip  :466
# class TestGraphRendersOnEveryRegisteredRenderer  :501-553 (renderer loop + degradation assertions to mirror)
class TestCatalogDefinitionIncludesGraph:                                                   # 555

# docs anchors: docs/outputs/a2ui-v1.md:393 `### Renderer matrix`;
# docs/frontend/agentdashboard-a2ui-reference.md:626 `#### \`Graph\` (\`catalog/viz_core/graph.py\`) — required \`nodes\`, \`edges\`` (prop table 628-638)
```

### Does NOT Exist
- ~~a `Graph` entry in `catalog/viz_core/spec/catalog.json`~~ — nothing to update there.
- ~~nested boundary frames in satellite renderers~~ — do not assert them; docs state the loss.

---

## Complexity Contract

```json
{
  "schema_version": 1,
  "targets": [
    {"path": "packages/ai-parrot/src/parrot/outputs/a2ui/graph/__init__.py", "action": "MODIFY"},
    {"path": "packages/ai-parrot/tests/outputs/a2ui/conformance/test_all_emitters.py", "action": "MODIFY"},
    {"path": "docs/outputs/a2ui-v1.md", "action": "MODIFY"},
    {"path": "docs/frontend/agentdashboard-a2ui-reference.md", "action": "MODIFY"}
  ],
  "contract_symbols": [
    "sym:packages/ai-parrot/tests/outputs/a2ui/conformance/test_all_emitters.py#TestCatalogDefinitionIncludesGraph"
  ]
}
```

---

## Implementation Blueprint

### Steps (in order)
1. Add the re-exports — *why*: public API of the graph package.
2. Add the conformance class — *why*: integration gate of spec §4.
3. Write both docs sections from the merged code (not from the spec alone) — *why*: docs must match behaviour.

### `graph/__init__.py` (MODIFY)
```python
# occurrences: 1 (verified: grep -c 'from .mermaid import MermaidCodecError, from_mermaid, to_mermaid' graph/__init__.py → line 12) — AFTER it:
from .layout_c4 import compute_c4_positions
from .mermaid_c4 import C4_LOSSY_FIELDS, from_mermaid_c4, to_mermaid_c4
# and add "C4_LOSSY_FIELDS", "compute_c4_positions", "from_mermaid_c4", "to_mermaid_c4" to __all__
# FILL IN: check for an import cycle (layout_c4 → layout, mermaid_c4 → mermaid are fine; both after .layout/.mermaid)
```

### `test_all_emitters.py` (MODIFY)
```python
# occurrences: 1 (verified: grep -c 'class TestCatalogDefinitionIncludesGraph:' test_all_emitters.py → line 555)
# AFTER the end of that class:
def _c4_envelope() -> CreateSurface:
    """build_c4_diagram(...) over fixtures/c4_container_diagram.json."""
    # FILL IN: load fixture, map groups → boundaries, return build_c4_diagram(...)


class TestC4GraphConformance:
    def test_build_c4_diagram_conformant(self) -> None: ...  # FILL IN: _assert_conformant(_c4_envelope())

    def test_c4_mermaid_roundtrip_byte_stable(self) -> None: ...  # FILL IN: props → GraphSpec → to_mermaid → from_mermaid → to_mermaid

    @pytest.mark.asyncio
    async def test_c4_graph_renders_on_every_registered_renderer(self) -> None: ...
    # FILL IN: mirror :501-553 — SSR-HTML / interactive-HTML / ECharts render natively; adaptive-cards and folium
    #          record exactly one `degraded` entry
# FILL IN: confirm CreateSurface is already imported in this module; otherwise import from parrot.outputs.a2ui.models
```

### `docs/outputs/a2ui-v1.md` (MODIFY)
```markdown
<!-- occurrences: 1 (verified: grep -c '### Renderer matrix' docs/outputs/a2ui-v1.md → line 393) — BEFORE it: -->
### C4 architecture diagrams — kind="c4" (FEAT-754)
<!-- FILL IN: subsections per spec §3 M7 bullet 1 -->
```

### `docs/frontend/agentdashboard-a2ui-reference.md` (MODIFY)
```markdown
<!-- occurrences: 1 (verified: grep -c '#### `Graph` (`catalog/viz_core/graph.py`) — required `nodes`, `edges`' → line 626) -->
<!-- FILL IN: append C4 rows to the prop table (628-638) and one paragraph after the lowering note -->
```

### FILL IN checklist
- [ ] re-exports; `_c4_envelope`; 3 test bodies; both doc sections

---

## Acceptance Criteria

- [ ] `TestC4GraphConformance` passes with ZERO changes under `packages/ai-parrot-visualizations/`.
- [ ] Existing conformance tests and both regression satellite files pass.
- [ ] Docs document the C4 kind, including loss of nested satellite boundary frames.

## Validation Commands
- `pytest packages/ai-parrot/tests/outputs/a2ui/conformance/test_all_emitters.py -q`
- `pytest packages/ai-parrot-visualizations/tests/outputs/a2ui_renderers/test_echarts_graph.py -q`
- `pytest packages/ai-parrot-visualizations/tests/outputs/a2ui_renderers/test_graph_svg.py -q`

---

## Test Specification
Spec §4 Integration Tests.

---

## Agent Instructions

Standard FEAT-754 procedure (`PYTHONPATH=packages/ai-parrot/src:packages/ai-parrot-visualizations/src`);
close with `scripts/sdd/close_task.sh TASK-4793 a2ui-c4-diagrams verified`.

---

## Completion Note

*(Agent fills this in when done)*

**Completed by**: gpt-5.6-terra (codex), attempt 1
**Date**: 2026-10-27
**Notes**: Engine merge-tier validation green (10 passed, outcome=completed). Closed with close_task.sh (not finalize_task) because no formal review EvidenceRef was recorded for this delivery.

**Deviations from spec**: none
