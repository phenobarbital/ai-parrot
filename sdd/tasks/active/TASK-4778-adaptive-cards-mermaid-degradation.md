# TASK-4778: adaptive_cards Mermaid monospace TextBlock degradation (M5)

**Feature**: FEAT-753 — A2UI MermaidDiagram (opaque Mermaid-source component in the Parrot catalog)
**Spec**: `sdd/specs/a2ui-mermaid-diagram.spec.md`
**Status**: pending
**Priority**: medium
**Estimated effort**: S (< 2h)
**Depends-on**: TASK-4773
**Assigned-to**: unassigned

---

## Context

Spec §3 Module 5 / G3, AC-7. The lowered `MermaidDiagram` source Text
(`parrot_role: "mermaid-source"`) must render as a monospace, copyable block with exactly ONE recorded
`degraded` entry per diagram. Capabilities are NOT changed — `MermaidDiagram` always lowers on this renderer.

---

## Scope

- Add a `role == "mermaid-source"` branch to `adaptive_cards.py` (see blueprint) with the fixed degradation message.
- Add tests to `test_adaptive_cards.py`.

**NOT in scope**: adding `MermaidDiagram` to `supported_components` / `_INTERCEPTED`; any `<script src=…>`; other renderers.

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot-visualizations/src/parrot/outputs/a2ui_renderers/adaptive_cards.py` | MODIFY | mermaid-source role branch + degradation record |
| `packages/ai-parrot-visualizations/tests/outputs/a2ui_renderers/test_adaptive_cards.py` | MODIFY | mermaid degradation tests |

---

## Codebase Contract (Anti-Hallucination)

> **CRITICAL**: verified against `65144d730` (2026-10-27). Use these exact imports, names and
> signatures. If you need something not listed here, VERIFY it exists first with `grep` or `read`.

### Verified Imports
```python
from parrot.outputs.a2ui.renderers.degrade import degradation_record  # verified: renderers/degrade.py:46 (already imported by the renderer)
from parrot.outputs.a2ui.models import Component, CreateSurface  # verified: models.py:400, :446
```

### Existing Signatures to Use
```python
# packages/ai-parrot-visualizations/src/parrot/outputs/a2ui_renderers/adaptive_cards.py
        if role == "html_document":  # line 466
# degradation_record(node: BasicNode, reason: str) -> dict[str, Any]  # renderers/degrade.py:46
# TextBlock is imported in adaptive_cards.py (line 88); model: parrot/outputs/cards/elements.py:14
class TextBlock(ACElement): text: str; wrap: bool = True; font_type: Literal["Default", "Monospace"] | None = None  # serialized as "fontType" (cards/renderer.py:93)
# NOTE: the spec writes `fontType="Monospace"` — the Python field is `font_type`.
```

### Does NOT Exist
- ~~`MermaidDiagram` in any renderer's `supported_components`~~ / ~~`_INTERCEPTED`~~ / ~~`_render_mermaiddiagram()`~~ — deliberately not added (D5).
- ~~a Mermaid engine / mermaid.js on server lanes~~ — never.

---

## Complexity Contract

```json
{
  "schema_version": 1,
  "targets": [
    {
      "path": "packages/ai-parrot-visualizations/src/parrot/outputs/a2ui_renderers/adaptive_cards.py",
      "action": "MODIFY"
    },
    {
      "path": "packages/ai-parrot-visualizations/tests/outputs/a2ui_renderers/test_adaptive_cards.py",
      "action": "MODIFY"
    }
  ],
  "contract_symbols": []
}
```

---

## Implementation Notes

- Degradation message is a FIXED string (spec §7), asserted by tests: `"adaptive_cards has no Mermaid engine; source shown as monospace text"`.
- HTML-escape the source (`html.escape`) where the output is HTML: a `<script` sample must never appear unescaped.
- The source text comes from the lowered node's `text` prop (`node.model_extra["text"]`); the diagram type from
  `metadata.extensions["parrot_diagram_type"]`.
- Note: an envelope containing `<script` is rejected by `validate_envelope` — build the escaping test with a
  source that is valid but contains `<` / `&` (e.g. `A["a < b & c"]`), or render the lowered node directly.

---

## Implementation Blueprint

> **Executor-ready starting point.** Write each block to its declared path nearly verbatim, then
> complete every `# FILL IN:` marker. Never change a signature, class name or file path fixed here.

### Steps (in order)
1. Add the branch at the anchor — *why*: G3 readable fallback.
2. Add tests after `class TestHtmlDocumentDegradesToTextBlockAndOpenUrl:` class — *why*: AC-7.
3. Run Validation Commands.

### `packages/ai-parrot-visualizations/src/parrot/outputs/a2ui_renderers/adaptive_cards.py` (MODIFY)
```python
# occurrences: 1 (verified: grep -c '        if role == "html_document":' adaptive_cards.py) — line 466
# BEFORE `        if role == "html_document":` (inside AdaptiveCardsRenderer._render_Text) add:
        if role == "mermaid-source":
            # FEAT-753: Adaptive Cards cannot run mermaid.js — monospace source, recorded once.
            state.degradations.append(
                degradation_record(node, "adaptive_cards has no Mermaid engine; source shown as monospace text")
            )
            return TextBlock(text=str(props.get("text") or ""), font_type="Monospace", wrap=True)
```
**Why**: spec §3 M5 skeleton; mirrors the `html_document` role branch (degrade visibly, record once).

### `packages/ai-parrot-visualizations/tests/outputs/a2ui_renderers/test_adaptive_cards.py` (MODIFY)
```python
# occurrences: 1 (verified: grep -c 'class TestHtmlDocumentDegradesToTextBlockAndOpenUrl:' test_adaptive_cards.py) — line 261
# BEFORE that class, add:
SRC = 'flowchart TD\n    a["a < b & c"] --> b\n'


class TestMermaidDiagramMonospaceTextBlock:
    """FEAT-753: adaptive_cards renders MermaidDiagram source as a Monospace TextBlock, one degraded record."""

    async def test_adaptive_cards_mermaid_monospace_textblock(self):
        env = CreateSurface(
        surfaceId="s",
        catalogId="c",
        components=[Component(id="root", component="MermaidDiagram", source=SRC, diagramType="flowchart")],
        dataModel={},
    )
        # FILL IN: render with AdaptiveCardsRenderer the way the neighbouring HtmlDocument test does; find the
        #   TextBlock whose text == the source; assert fontType == "Monospace" in the JSON output (font_type on the
        #   model), wrap is True, exactly one degraded record whose reason contains "Mermaid"
```

### FILL IN checklist
- [ ] branch body per blueprint
- [ ] test assertions (AC-7: block present, escaped, ONE degraded record naming Mermaid)

---

## Acceptance Criteria

- [ ] AC-7 for this renderer: renders without raising, monospace block, escaped, exactly ONE degraded entry, no `<script src`.
- [ ] Existing tests of this renderer unchanged and green.

## Validation Commands

- `PYTHONPATH=packages/ai-parrot/src:packages/ai-parrot-tools/src:packages/ai-parrot-visualizations/src pytest packages/ai-parrot-visualizations/tests/outputs/a2ui_renderers/test_adaptive_cards.py -q`

---

## Test Specification

See the test block above.

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

*(Agent fills this in when done)*

**Completed by**: [agent name]
**Date**: YYYY-MM-DD
**Notes**: What was implemented, any deviations from scope, issues encountered.

**Deviations from spec**: none | describe if any
