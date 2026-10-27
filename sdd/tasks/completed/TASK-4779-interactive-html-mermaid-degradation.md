# TASK-4779: interactive-html Mermaid code-block degradation (M5)

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

- Add a `role == "mermaid-source"` branch to `interactive_html.py` (see blueprint) with the fixed degradation message.
- Add tests to `test_interactive_html.py`.

**NOT in scope**: adding `MermaidDiagram` to `supported_components` / `_INTERCEPTED`; any `<script src=…>`; other renderers.

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot-visualizations/src/parrot/outputs/a2ui_renderers/interactive_html.py` | MODIFY | mermaid-source role branch + degradation record |
| `packages/ai-parrot-visualizations/tests/outputs/a2ui_renderers/test_interactive_html.py` | MODIFY | mermaid degradation tests |

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
# packages/ai-parrot-visualizations/src/parrot/outputs/a2ui_renderers/interactive_html.py
    def _render_prim_Text(self, node: BasicNode, degradations: list[dict[str, Any]]) -> str:  # line 1117
# degradation_record(node: BasicNode, reason: str) -> dict[str, Any]  # renderers/degrade.py:46
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
      "path": "packages/ai-parrot-visualizations/src/parrot/outputs/a2ui_renderers/interactive_html.py",
      "action": "MODIFY"
    },
    {
      "path": "packages/ai-parrot-visualizations/tests/outputs/a2ui_renderers/test_interactive_html.py",
      "action": "MODIFY"
    }
  ],
  "contract_symbols": []
}
```

---

## Implementation Notes

- Degradation message is a FIXED string (spec §7), asserted by tests: `"interactive-html does not bundle mermaid.js (self-contained invariant); source shown as a code block"`.
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
2. Add tests after `class TestHtmlDocumentSandboxedIframe:` class — *why*: AC-7.
3. Run Validation Commands.

### `packages/ai-parrot-visualizations/src/parrot/outputs/a2ui_renderers/interactive_html.py` (MODIFY)
```python
# occurrences: 1 (verified: grep -c 'cls = f"a2ui-text a2ui-{_esc(role)}" if role else "a2ui-text"' interactive_html.py) — line 1117
# Inside _render_prim_Text (verified: interactive_html.py:1117), BEFORE the line
#   `        cls = f"a2ui-text a2ui-{_esc(role)}" if role else "a2ui-text"`   (occurrences: 1; ~line 1129)
# i.e. right after `role` is read from the extensions, add:
        if role == "mermaid-source":
            # FEAT-753 D5: no mermaid.js in the self-contained artifact — code block, recorded once.
            degradations.append(
                degradation_record(
                    node,
                    "interactive-html does not bundle mermaid.js (self-contained invariant); source shown as a code block",
                )
            )
            return (
                '<pre class="a2ui-mermaid-source"><code class="language-mermaid">'
                f"{html.escape(str(props.get('text') or ''))}</code></pre>"
            )
# DO NOT touch `_INTERCEPTED` (line 136), `supported_components` (lines 866-902) or `_render_top`.
```
**Why**: spec §3 M5 skeleton; mirrors the `html_document` role branch (degrade visibly, record once).

### `packages/ai-parrot-visualizations/tests/outputs/a2ui_renderers/test_interactive_html.py` (MODIFY)
```python
# occurrences: 1 (verified: grep -c 'class TestHtmlDocumentSandboxedIframe:' test_interactive_html.py) — line 478
# BEFORE that class, add:
SRC = 'flowchart TD\n    a["a < b & c"] --> b\n'


class TestMermaidDiagramNotIntercepted:
    """FEAT-753 D5: interactive-html lowers MermaidDiagram to a code block (no mermaid.js)."""

    async def test_interactive_html_mermaid_not_intercepted_code_block(self):
        from parrot.outputs.a2ui_renderers.interactive_html import _INTERCEPTED

        assert "MermaidDiagram" not in _INTERCEPTED
        env = CreateSurface(
        surfaceId="s",
        catalogId="c",
        components=[Component(id="root", component="MermaidDiagram", source=SRC, diagramType="flowchart")],
        dataModel={},
    )
        # FILL IN: render with InteractiveHTMLRenderer like the neighbouring tests; assert the code block, escaped
        #   source, no new "<script src" compared with a baseline render, exactly one degraded record naming mermaid
```

### FILL IN checklist
- [ ] branch body per blueprint
- [ ] test assertions (AC-7: block present, escaped, ONE degraded record naming Mermaid)

---

## Acceptance Criteria

- [ ] AC-7 for this renderer: renders without raising, monospace block, escaped, exactly ONE degraded entry, no `<script src`.
- [ ] Existing tests of this renderer unchanged and green.

## Validation Commands

- `PYTHONPATH=packages/ai-parrot/src:packages/ai-parrot-tools/src:packages/ai-parrot-visualizations/src pytest packages/ai-parrot-visualizations/tests/outputs/a2ui_renderers/test_interactive_html.py -q`

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

**Completed by**: sdd-worker (sequential fallback)
**Date**: 2026-10-27
**Notes**: Added the `mermaid-source` role branch to interactive_html.py `_render_prim_Text` (code block, one degraded record); `_INTERCEPTED`/`supported_components` untouched; test also checks no extra `<script src=`. Tests green. Black was NOT applied to these renderer files (it reflows unrelated code); only the inserted hunks were kept.

**Deviations from spec**: none
