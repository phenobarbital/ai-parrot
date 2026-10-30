# TASK-4782: Conformance suite: MermaidDiagram builders, round-trip, renderers (M7)

**Feature**: FEAT-753 — A2UI MermaidDiagram (opaque Mermaid-source component in the Parrot catalog)
**Spec**: `sdd/specs/a2ui-mermaid-diagram.spec.md`
**Status**: pending
**Priority**: medium
**Estimated effort**: M (2-4h)
**Depends-on**: TASK-4774, TASK-4777, TASK-4778, TASK-4779
**Assigned-to**: unassigned

---

## Context

Spec §4 Integration Tests / AC-4, AC-5, AC-7. Cross-cutting acceptance tests in the existing two-layer
conformance file (catalog allowlist + lowered Basic wire schema via `_assert_conformant`).

---

## Scope

- Add to `conformance/test_all_emitters.py`: `TestBuildersConformance.test_build_mermaid_diagram` (TOOL and LLM),
  `TestGraphToMermaidDiagramRoundtrip`, `TestCatalogDefinitionIncludesMermaidDiagram`,
  `TestMermaidDiagramFallbackRenderers` (ssr_html, pdf, adaptive_cards, interactive-html — existing skip rules),
  `TestMermaidDiagramFocalRendererCompatibility` (echarts, folium_map keep their existing errors).

**NOT in scope**: changing any existing test in the file (AC-11); production code.

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot/tests/outputs/a2ui/conformance/test_all_emitters.py` | MODIFY | five new test groups |

---

## Codebase Contract (Anti-Hallucination)

> **CRITICAL**: verified against `65144d730` (2026-10-27). Use these exact imports, names and
> signatures. If you need something not listed here, VERIFY it exists first with `grep` or `read`.

### Verified Imports
```python
from parrot.outputs.a2ui.builders import build_mermaid_diagram  # created by TASK-4774
from parrot.outputs.a2ui.graph import graph_spec_from_mermaid_source, to_mermaid, detect_diagram_type  # TASK-4772 + graph/mermaid.py:206
from parrot.outputs.a2ui.catalog import ProducerOrigin  # verified: catalog/__init__.py __all__
from parrot.outputs.a2ui.catalog.export import export_catalog_definition  # verified: catalog/export.py:215
```

### Existing Signatures to Use
```python
# conformance/test_all_emitters.py
def _assert_conformant(envelope: CreateSurface, *, origin: ProducerOrigin = ProducerOrigin.TOOL) -> None  # line 116
class TestBuildersConformance:  # line 136 — def test_build_graph(self) at line 171 (pattern)
class TestRendererConformance:  # line 381 — renderer parametrization + optional-dependency skip rules to reuse
class TestFlowToGraphToMermaidRoundtrip:  # line 466 — flow fixture (:466-500) for the round-trip
class TestGraphRendersOnEveryRegisteredRenderer:  # line 501 — how echarts / folium_map errors are asserted
class TestCatalogDefinitionIncludesGraph:  # line 555 — insert new classes BEFORE it (anchor, occurrences 1)
# graph/test_mermaid.py:23-29 — helper semantics for comparing specs modulo accessible_description/size
```

### Does NOT Exist
- ~~`from_mermaid` returning `kind="dag"`~~ — a `dag` spec exports as `flowchart`; compare accordingly.
- ~~new renderer code~~ — echarts/folium_map are NOT changed (AC-7).

---

## Complexity Contract

```json
{
  "schema_version": 1,
  "targets": [
    {
      "path": "packages/ai-parrot/tests/outputs/a2ui/conformance/test_all_emitters.py",
      "action": "MODIFY"
    }
  ],
  "contract_symbols": []
}
```

---

## Implementation Notes

- Read `TestRendererConformance` and `TestGraphRendersOnEveryRegisteredRenderer` first and reuse their renderer lookup and
  importorskip rules verbatim.
- Round-trip: for each GraphSpec fixture (flow fixture + one flowchart/state/sequence sample), `build_mermaid_diagram(
  source=to_mermaid(spec))` validates, `diagramType ∈ {flowchart, state, sequence}`, and `graph_spec_from_mermaid_source`
  equals the spec modulo `accessible_description`/`size` (and `kind="dag"` → `"flowchart"`).

---

## Implementation Blueprint

> **Executor-ready starting point.** Write each block to its declared path nearly verbatim, then
> complete every `# FILL IN:` marker. Never change a signature, class name or file path fixed here.

### Steps (in order)
1. Add the `test_build_mermaid_diagram` method inside `TestBuildersConformance` after `test_build_graph`.
2. Insert the four new classes before `class TestCatalogDefinitionIncludesGraph:`.
3. Run the file.

### `packages/ai-parrot/tests/outputs/a2ui/conformance/test_all_emitters.py` (MODIFY)
```python
# (a) inside TestBuildersConformance, after `def test_build_graph(self):` (line 171) method:
    @pytest.mark.parametrize("origin", [ProducerOrigin.TOOL, ProducerOrigin.LLM])
    def test_build_mermaid_diagram(self, origin):
        env = build_mermaid_diagram(source="sequenceDiagram\n    A->>B: hi\n", origin=origin)
        _assert_conformant(env, origin=origin)

# (b) occurrences: 1 (verified: grep -c 'class TestCatalogDefinitionIncludesGraph:') — line 555; BEFORE it add:
class TestGraphToMermaidDiagramRoundtrip:
    # FILL IN: spec §4 row — AC-5
    ...


class TestCatalogDefinitionIncludesMermaidDiagram:
    def test_catalog_definition_includes_mermaid_diagram(self):
        # FILL IN: Parrot export lists MermaidDiagram; viz-core export does not (mirror TestCatalogDefinitionIncludesGraph)
        ...


class TestMermaidDiagramFallbackRenderers:
    # FILL IN: parametrize ssr_html, pdf, adaptive_cards, interactive-html; readable source + exactly ONE degraded record
    ...


class TestMermaidDiagramFocalRendererCompatibility:
    # FILL IN: echarts / folium_map keep their existing missing-focal errors on a Mermaid-only envelope (AC-7)
    ...
```
**Why**: the `...` stubs are placeholders for the executor — replace every one with a real body (no `...` may remain).

### FILL IN checklist
- [ ] four new test classes per spec §4 Integration Tests
- [ ] reuse existing renderer skip rules

---

## Acceptance Criteria

- [ ] AC-4, AC-5, AC-7 conformance rows pass; all pre-existing tests in the file unchanged and green.

## Validation Commands

- `PYTHONPATH=packages/ai-parrot/src:packages/ai-parrot-tools/src:packages/ai-parrot-visualizations/src pytest packages/ai-parrot/tests/outputs/a2ui/conformance/test_all_emitters.py -q`

---

## Test Specification

See the MODIFY block.

---

## Agent Instructions

When you pick up this task:

1. **Work in the feature worktree** — never on `dev`
   (`python -m scripts.sdd.ensure_worktree --slug a2ui-mermaid-diagram --feature-id FEAT-753`).
2. **Read the spec** `sdd/specs/a2ui-mermaid-diagram.spec.md` (§2 decisions D1–D7, §6 contract, §7 constraints).
3. **Check dependencies** — every `Depends-on` task must be `done` in `sdd/tasks/index/a2ui-mermaid-diagram.json`.
4. **Verify the Codebase Contract** — re-run the `grep -c` of every MODIFY anchor before editing; a count of 0 is drift: stop and report.
5. **Update status** in the per-spec index → `"in-progress"`.
6. **Implement** the blueprint, then complete every `FILL IN` — touch only the files listed above.
7. **Validate**: `ruff check --fix <files>`, `black -l 120 <files>`, then the Validation Commands with
   `PYTHONPATH=packages/ai-parrot/src:packages/ai-parrot-tools/src:packages/ai-parrot-visualizations/src`.
8. **Close** with `scripts/sdd/close_task.sh <TASK-ID> a2ui-mermaid-diagram verified` and fill the Completion Note.

---

## Completion Note

**Completed by**: sdd-worker (sequential fallback)
**Date**: 2026-10-27
**Notes**: Added `test_build_mermaid_diagram` (TOOL + LLM) and four new groups to conformance/test_all_emitters.py (35 passed in the file). The only removed line is the extended `build_linked_surface`/`graph` import tuple. Adaptive-card text is compared via a recursive `_card_texts` helper because `json.dumps` escapes the source's newlines/quotes. Round-trip fixtures use declared nodes/participants (codec requirement); `dag` normalized to `flowchart`.

**Deviations from spec**: none
