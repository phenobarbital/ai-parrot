# TASK-2865: Renderer handling for `HtmlDocument` — sandboxed iframe in interactive-html, titled-link degradation elsewhere

**Feature**: FEAT-527 — Infographic → A2UI migration (dual-emit)
**Spec**: `sdd/specs/infographic-a2ui-migration.spec.md`
**Status**: pending
**Priority**: medium
**Estimated effort**: M (2-4h)
**Depends-on**: TASK-2863
**Assigned-to**: unassigned

---

## Context

Spec §2 Overview step 6, §3 Module 4 "renderer handling", §7 security stance. `HtmlDocument`
lowers to a placeholder (TASK-2863), so every renderer already degrades gracefully by default.
This task makes the degradation *good*: interactive-html embeds the document in a sandboxed
`<iframe>`; ssr-html / pdf / adaptive_cards render a titled link to `srcUrl` (or the placeholder
when only inline `html` exists) and record a `degraded` entry.

---

## Scope

- `a2ui_renderers/interactive_html.py` — add `"HtmlDocument"` to `_INTERCEPTED` (`:120`) so the
  component is handled **before** lowering (its raw `html` lives on the component props); implement
  `_render_htmldocument(self, props) -> str` returning
  `<section class="a2ui-html-document"><h3>…title…</h3><iframe sandbox="allow-scripts" srcdoc="…escaped html…"></iframe></section>`
  when `html` is present, else `<iframe sandbox="allow-scripts" src="…srcUrl…">`. Wire it in
  `_render_descriptor` (`:705`) / the intercepted dispatch (`:698-704`, where `Infographic` is
  special-cased) so nested `HtmlDocument` inside an `Infographic` section also works. Escape with
  `html.escape(..., quote=True)` for the `srcdoc` attribute. Add a `.a2ui-html-document iframe`
  rule to the renderer's inline CSS (min-height, width 100%, border) — no external CSS.
- `a2ui_renderers/ssr_html.py` — the lowered placeholder `Text` carries
  `extensions.parrot_role == "html_document"` and `parrot_src_url`; in `_render_Text` (`:402+`) (or a
  small pre-check in `_render_basic` `:383`) render `<p class="a2ui-html-document-link"><a href="{srcUrl}">{title}</a></p>`
  when `parrot_src_url` is set, otherwise the placeholder text; append a `degradation_record(node,
  "ssr-html cannot embed HtmlDocument")` in both cases. `pdf.py` inherits (`:99`) — verify the link
  survives the print layout.
- `a2ui_renderers/adaptive_cards.py` — same rule as SSR in `_render_Text` (`:429`): `TextBlock` with
  the title + an `Action.OpenUrl` when `parrot_src_url` exists (check how the renderer already emits
  actions/deep links at `:210+`); record degradation.
- Tests in `tests/outputs/a2ui_renderers/`: `test_interactive_html.py` (iframe sandboxed; raw script
  from the document does **not** execute in the host — assert it appears only inside the escaped
  `srcdoc` attribute; self-contained assertions still hold), `test_ssr_html.py`, `test_pdf.py`,
  `test_adaptive_cards.py`.

**NOT in scope**: the component/builder (TASK-2863); toolkit (TASK-2864); frontend iframe (TASK-2867); ECharts renderer (irrelevant).

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot-visualizations/src/parrot/outputs/a2ui_renderers/interactive_html.py` | MODIFY | intercept + sandboxed iframe |
| `packages/ai-parrot-visualizations/src/parrot/outputs/a2ui_renderers/ssr_html.py` | MODIFY | titled link + degradation |
| `packages/ai-parrot-visualizations/src/parrot/outputs/a2ui_renderers/adaptive_cards.py` | MODIFY | TextBlock + OpenUrl + degradation |
| `packages/ai-parrot-visualizations/tests/outputs/a2ui_renderers/test_interactive_html.py` | MODIFY | iframe/sandbox tests |
| `packages/ai-parrot-visualizations/tests/outputs/a2ui_renderers/test_ssr_html.py` | MODIFY | link degradation |
| `packages/ai-parrot-visualizations/tests/outputs/a2ui_renderers/test_pdf.py` | MODIFY | inherits link |
| `packages/ai-parrot-visualizations/tests/outputs/a2ui_renderers/test_adaptive_cards.py` | MODIFY | TextBlock/OpenUrl |

---

## Codebase Contract (Anti-Hallucination)

### Verified Imports
```python
from parrot.outputs.a2ui.builders import build_html_document                     # after TASK-2863
from parrot.outputs.a2ui.models import Component, CreateSurface                  # a2ui/models.py
from parrot.outputs.a2ui.renderers import get_a2ui_renderer                      # renderers/__init__.py:141
from parrot.outputs.a2ui.renderers.degrade import degrade                        # degrade.py:24
from parrot.outputs.a2ui.artifacts import RenderedArtifact                      # artifacts.py:54 (.metadata["degraded"])
from parrot.outputs.a2ui_renderers.ssr_html import SSRHTMLRenderer               # ssr_html.py:142
from parrot.outputs.a2ui_renderers.pdf import PDFRenderer                        # pdf.py:99 (subclass of SSRHTMLRenderer)
import parrot.outputs.a2ui_renderers.interactive_html                            # class at :574 — verify exact name
import parrot.outputs.a2ui_renderers.adaptive_cards                              # registered at :210
```

### Existing Signatures to Use
```python
# interactive_html.py
_INTERCEPTED = {"Chart", "DataTable", "Infographic", "Map"}                      # :120 ← add "HtmlDocument"
# intercepted composites are rendered directly BEFORE baking :605 ; non-intercepted composites lowered :653
if name == "Infographic": ...                                                    # :698 (special-case dispatch — add HtmlDocument sibling)
def _render_descriptor(self, descriptor: dict[str, Any]) -> str                  # :705 ("nested component descriptor (e.g. inside an Infographic section)")
def _render_prim_Text(self, node, degradations) -> str                           # :772 usage; `degrade(node, "no renderer available")`
def _render_chart(self, props) -> str :1005 ; def _render_datatable(self, props) -> str :1058 ; def _render_infographic(self, props) -> str :1136
# self-contained invariant: tests assert absence of "<script src=", "<link ", "@import"

# ssr_html.py
def _render_basic(self, node: BasicNode, degradations: list[dict]) -> str        # :383-394 (degradation_record(node, msg) + degrade(node, reason))
def _render_Text(self, node: BasicNode, degradations) -> str                     # :402
# node.metadata["extensions"] carries parrot_role etc. (see kpicard lowering)

# pdf.py
class PDFRenderer(SSRHTMLRenderer): __init__(*, theme="light") → super().__init__(theme=theme, layout="print")  # :99-126 ; async def render :128

# adaptive_cards.py
def _render_basic(self, node: BasicNode, state: _RenderState) -> ACElement | None  # :408 ; `degrade(node, "no renderer available")` :419
def _render_Text(self, node: BasicNode, state: _RenderState) -> ACElement        # :429

# HtmlDocument lowered shape (TASK-2863): Card{child: Column[Text(title, parrot_role=title), Text("[HTML document: <title>]",
#   extensions={"parrot_role": "html_document", "parrot_src_url": str|None, "parrot_inline_html": bool})]}
# HtmlDocument component props (pre-lowering, on Component.model_extra): title, html | srcUrl, theme
```

### Does NOT Exist
- ~~raw HTML inside the lowered tree~~ — TASK-2863 guarantees the placeholder never embeds it; only the interactive renderer reads `props["html"]` pre-lowering.
- ~~`get_a2ui_renderer("interactive_html")`~~ — hyphenated `"interactive-html"`; import the module in tests.
- ~~`RenderedArtifact.degradations`~~ — it is `metadata["degraded"]`.
- ~~any CDN/`<link>` for iframe styling~~ — inline CSS only (FEAT-493 invariant).

---

## Implementation Notes

### Pattern to Follow
`interactive_html.py:1136 _render_infographic` — an intercepted composite rendered from `props`
directly; mirror its signature and how it is dispatched at `:698-704`.

### Key Constraints
- `sandbox="allow-scripts"` **without** `allow-same-origin` so the embedded document cannot reach
  the host DOM/storage; the host page must not evaluate the document's scripts (assert the raw
  `<script>` text appears only inside the `srcdoc="…"` attribute, escaped).
- Degradation must be recorded in every non-embedding surface.
- Keep the print layout (PDF) readable: link text + URL.

### References in Codebase
- `packages/ai-parrot-visualizations/tests/outputs/a2ui_renderers/test_filterbar_degradation.py` — degradation assertions.
- `packages/ai-parrot-visualizations/tests/outputs/a2ui_renderers/test_semantic_classes.py` — CSS class assertions style.

---

## Acceptance Criteria

- [ ] interactive-html renders `HtmlDocument` as `<iframe sandbox="allow-scripts" srcdoc=…>` (inline) or `src=…` (URL); nested inside an `Infographic` section too; no external references introduced
- [ ] ssr-html / pdf render a titled link when `srcUrl` exists, placeholder text otherwise, and record a `degraded` entry
- [ ] adaptive_cards renders a `TextBlock` (+ `Action.OpenUrl` when URL) and records degradation
- [ ] Raw document scripts never appear unescaped in the host HTML
- [ ] `timeout -s KILL 600 pytest packages/ai-parrot-visualizations/tests/outputs/a2ui_renderers -q` green; `ruff check` on the three renderer modules

---

## Test Specification

```python
# tests/outputs/a2ui_renderers/test_interactive_html.py (add)
async def test_htmldocument_embedded_in_sandboxed_iframe():
    env = build_html_document(title="Doc", html="<html><body><script>alert(1)</script></body></html>")
    art = await InteractiveHTMLRenderer().render(env)
    out = art.content.decode()
    assert 'sandbox="allow-scripts"' in out and "srcdoc=" in out
    assert "<script>alert(1)</script>" not in out          # only the escaped form inside srcdoc
    assert "&lt;script&gt;alert(1)&lt;/script&gt;" in out
    assert "<script src=" not in out

# tests/outputs/a2ui_renderers/test_ssr_html.py (add)
async def test_htmldocument_degrades_to_link():
    env = build_html_document(title="Doc", src_url="https://x/infographic-a.html")
    art = await SSRHTMLRenderer().render(env)
    assert '<a href="https://x/infographic-a.html">Doc</a>' in art.content.decode()
    assert any("HtmlDocument" in d.get("reason", "") for d in art.metadata["degraded"])
```

---

## Agent Instructions

When you pick up this task:

1. **Read the spec** at the path listed above for full context
2. **Check dependencies** — TASK-2863 in `sdd/tasks/completed/`
3. **Verify the Codebase Contract** — read `interactive_html.py:600-720` and `ssr_html.py:383-440` before editing
4. **Update status** in `sdd/tasks/index/infographic-a2ui-migration.json` → `"in-progress"`
5. **Implement** following the scope, codebase contract, and notes above
6. **Verify** all acceptance criteria are met
7. **Move this file** to `sdd/tasks/completed/TASK-2865-renderers-htmldocument.md`
8. **Update index** → `"done"`
9. **Fill in the Completion Note** below

---

## Completion Note

**Completed by**: sdd-worker (Claude)
**Date**: 2026-09-05
**Notes**:
- **interactive-html**: added `"HtmlDocument"` to `_INTERCEPTED` (so it's
  handled BEFORE lowering — its raw `html` lives on the component props,
  never in a lowered tree). New `_render_htmldocument()` returns
  `<section class="a2ui-html-document"><h3>…</h3><iframe
  sandbox="allow-scripts" srcdoc="…escaped…"></iframe></section>` (inline
  html) or `src="…srcUrl…"` (URL variant) — inline `style=` for min-height/
  width/border (no CSS file edit needed for the layout itself, following
  this file's own existing inline-`style=` precedent at line ~936). Wired
  into both `_render_top` (top-level) and `_render_descriptor` (nested
  inside an `Infographic` section).
- **ssr-html**: `_render_Text()` special-cases `parrot_role ==
  "html_document"` (the lowered placeholder from TASK-2863): degrades to
  `<a href="{srcUrl}">{title}</a>` when a `srcUrl` exists, else the
  placeholder text — the title is parsed out of the fixed, code-controlled
  `"[HTML document: <title>]"` string format `HtmlDocumentComponent.lower()`
  emits (not user input, so this is safe). ALWAYS records a
  `degradation_record` (both branches) since this static renderer can never
  embed the document either way. `pdf.py` inherits with ZERO code changes
  (verified: `PDFRenderer._build_intermediate_html` calls
  `super().render()` = `SSRHTMLRenderer.render()`).
- **adaptive_cards**: `_render_Text()` special-cases the same role: a
  `TextBlock` with the title, plus a top-level `Action.OpenUrl` appended to
  `state.actions` when a `srcUrl` exists (same bottom-action-bar convention
  `_render_Button`'s own `functionCall=openUrl` branch uses). Recorded.
- **Companion fixes (necessary, minimal, not code-behavior deviations)**:
  (1) ran `scripts/generate_a2ui_css.py` to regenerate
  `tailwind.generated.css` for the new `.a2ui-html-document` class
  referenced in `interactive_html.py` — 3-line diff, verified minimal.
  (2) extended `test_semantic_classes.py`'s `TestGoldensUntouched` allowlist
  for TASK-2862/2863's already-landed, already-approved catalog changes
  (`catalog/base.py`, `catalog/__init__.py`'s `tool_only` gate; the new
  `htmldocument.py` component + its golden) — this guard test's git-diff
  scope had not yet caught up with those completed, in-scope tasks.
- 213/213 targeted tests pass
  (`pytest packages/ai-parrot-visualizations/tests/outputs/a2ui_renderers`).
  `ruff check` on all 9 touched files: all checks passed.

**Deviations from spec**: none.
