# TASK-4777: ssr-html (+pdf) Mermaid code-block degradation (M5)

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

- Add a `role == "mermaid-source"` branch to `ssr_html.py` (see blueprint) with the fixed degradation message.
- Add tests to `test_ssr_html.py`.
- Add `test_pdf_inherits_mermaid_degradation` to `test_pdf.py` (module already `importorskip`s weasyprint) asserting the same single degraded record; pdf.py itself is not modified.

**NOT in scope**: adding `MermaidDiagram` to `supported_components` / `_INTERCEPTED`; any `<script src=…>`; other renderers.

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot-visualizations/src/parrot/outputs/a2ui_renderers/ssr_html.py` | MODIFY | mermaid-source role branch + degradation record |
| `packages/ai-parrot-visualizations/tests/outputs/a2ui_renderers/test_ssr_html.py` | MODIFY | mermaid degradation tests |
| `packages/ai-parrot-visualizations/tests/outputs/a2ui_renderers/test_pdf.py` | MODIFY | pdf inherits the ssr-html degradation |

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
# packages/ai-parrot-visualizations/src/parrot/outputs/a2ui_renderers/ssr_html.py
        if role == "html_document":  # line 532
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
      "path": "packages/ai-parrot-visualizations/src/parrot/outputs/a2ui_renderers/ssr_html.py",
      "action": "MODIFY"
    },
    {
      "path": "packages/ai-parrot-visualizations/tests/outputs/a2ui_renderers/test_ssr_html.py",
      "action": "MODIFY"
    },
    {
      "path": "packages/ai-parrot-visualizations/tests/outputs/a2ui_renderers/test_pdf.py",
      "action": "MODIFY"
    }
  ],
  "contract_symbols": []
}
```

---

## Implementation Notes

- Degradation message is a FIXED string (spec §7), asserted by tests: `"ssr-html has no Mermaid engine; source shown as a code block"`.
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
2. Add tests after `class TestHtmlDocumentDegradesToLink:` class — *why*: AC-7.
3. Run Validation Commands.

### `packages/ai-parrot-visualizations/src/parrot/outputs/a2ui_renderers/ssr_html.py` (MODIFY)
```python
# occurrences: 1 (verified: grep -c '        if role == "html_document":' ssr_html.py) — line 532
# BEFORE `        if role == "html_document":` (inside SSRHTMLRenderer._render_Text, verified: ssr_html.py:516) add:
        if role == "mermaid-source":
            # FEAT-753: no Mermaid engine server-side — show the source as a copyable code block.
            degradations.append(degradation_record(node, "ssr-html has no Mermaid engine; source shown as a code block"))
            source = str(props.get("text") or "")
            diagram_type = str(extensions.get("parrot_diagram_type") or "unknown")
            return (
                '<pre class="a2ui-mermaid-source"><code class="language-mermaid" '
                f'data-diagram-type="{html.escape(diagram_type, quote=True)}">{html.escape(source)}</code></pre>'
            )
```
**Why**: spec §3 M5 skeleton; mirrors the `html_document` role branch (degrade visibly, record once).

### `packages/ai-parrot-visualizations/tests/outputs/a2ui_renderers/test_ssr_html.py` (MODIFY)
```python
# occurrences: 1 (verified: grep -c 'class TestHtmlDocumentDegradesToLink:' test_ssr_html.py) — line 270
# BEFORE that class, add:
SRC = 'flowchart TD\n    a["a < b & c"] --> b\n'


class TestMermaidDiagramDegradesToCodeBlock:
    """FEAT-753: ssr-html shows MermaidDiagram source as a code block, one degraded record."""

    async def test_ssr_html_mermaid_source_code_block_and_degraded(self):
        env = CreateSurface(
        surfaceId="s",
        catalogId="c",
        components=[Component(id="root", component="MermaidDiagram", source=SRC, diagramType="flowchart")],
        dataModel={},
    )
        art = await SSRHTMLRenderer().render(env)
        doc = art.content.decode()
        assert '<pre class="a2ui-mermaid-source"><code class="language-mermaid"' in doc
        # FILL IN: escaped "&lt; b &amp; c" present, raw "a < b" absent; exactly one degraded record whose reason contains "Mermaid"
```

### FILL IN checklist
- [ ] branch body per blueprint
- [ ] test assertions (AC-7: block present, escaped, ONE degraded record naming Mermaid)

---

## Acceptance Criteria

- [ ] AC-7 for this renderer: renders without raising, monospace block, escaped, exactly ONE degraded entry, no `<script src`.
- [ ] Existing tests of this renderer unchanged and green.

## Validation Commands

- `PYTHONPATH=packages/ai-parrot/src:packages/ai-parrot-tools/src:packages/ai-parrot-visualizations/src pytest packages/ai-parrot-visualizations/tests/outputs/a2ui_renderers/test_ssr_html.py -q`
- `PYTHONPATH=packages/ai-parrot/src:packages/ai-parrot-tools/src:packages/ai-parrot-visualizations/src pytest packages/ai-parrot-visualizations/tests/outputs/a2ui_renderers/test_pdf.py -q`

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
**Notes**: Added the `mermaid-source` role branch to ssr_html.py (escaped `<pre><code class=language-mermaid>`, one degraded record with the fixed message) plus tests in test_ssr_html.py and test_pdf.py (pdf.py unchanged). 148 passed across the four renderer test files. Black was NOT applied to these renderer files (it reflows unrelated code); only the inserted hunks were kept.

**Deviations from spec**: none
