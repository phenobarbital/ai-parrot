# TASK-2709: Shared document shell + composer wiring in both A2UI HTML renderers

**Feature**: FEAT-493 — Backend HTML Design System
**Spec**: `sdd/specs/html-renderer-design-system.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: M (2-4h)
**Depends-on**: TASK-2707
**Assigned-to**: unassigned

---

## Context

Spec §3 Module 3 (first half). Both A2UI HTML renderers build their document
inline and carry their own hardcoded `_STYLE` constant. Neither emits
`<meta viewport>`; `interactive-html` drops top-level blocks straight into
`<body>` with `margin:1rem` and no wrapper. This task replaces both
stylesheets with the composer and extracts one shared shell.

This is the task that makes the design system visible. It deliberately does
NOT yet honour `parrot_variant`/`parrot_role` (TASK-2710) — keeping those
separate means this change is verifiable on its own: same markup, real CSS.

---

## Scope

- Create `a2ui_renderers/_shell.py` with
  `document_shell(*, title, style, body, theme, layout, scripts=()) -> str`,
  emitting `<!DOCTYPE html>`, `<meta charset>`, **`<meta name="viewport"`**,
  `<title>`, `<style>`, and
  `<body><div class="ds-page" data-layout="…" data-theme="…">…</div>` with
  the scripts after the wrapper.
- `InteractiveHTMLRenderer.render()` (`interactive_html.py:298`,
  document built at `:333-343`) uses it, passing the embedded
  `report-data` JSON, the Chart.js bundle and `_BEHAVIOR_JS` as `scripts`.
- `SSRHTMLRenderer.render()` (`ssr_html.py:128`, `<style>` at `:173`) uses
  it with no scripts.
- Delete both `_STYLE` constants (`interactive_html.py:108-138`,
  `ssr_html.py:61-79`) in favour of `DesignSystem.stylesheet(...)`.
- Both renderers accept `theme` and `layout` constructor kwargs, defaulting
  to `("light", "analytics")`. `AbstractA2UIRenderer` declares no
  `__init__`, so adding one is additive — but `RecipeRunner` currently calls
  `renderer_cls()` with no arguments (`runner.py:635`), so **both kwargs
  must have defaults** or every existing caller breaks.
- Preserve every `a2ui-*` class exactly as emitted today.

**NOT in scope**: variant/role class mapping and `DesignSystem.resolve()`
(TASK-2710); the rich table (TASK-2711); `PDFRenderer`'s print layout
(TASK-2713); the runner change (TASK-2714).

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `.../a2ui_renderers/_shell.py` | CREATE | `document_shell()` |
| `.../a2ui_renderers/interactive_html.py` | MODIFY | Drop `_STYLE`; use shell + composer; `__init__` kwargs |
| `.../a2ui_renderers/ssr_html.py` | MODIFY | Same, scriptless |
| `packages/ai-parrot-visualizations/tests/outputs/a2ui_renderers/test_document_shell.py` | CREATE | Shell + class-preservation tests |

---

## Codebase Contract (Anti-Hallucination)

### Verified Imports

```python
from parrot.outputs.a2ui.artifacts import RenderedArtifact
from parrot.outputs.a2ui.models import CreateSurface
from parrot.outputs.a2ui.renderers import AbstractA2UIRenderer, RendererCapabilities, register_a2ui_renderer
# verified: packages/ai-parrot/src/parrot/outputs/a2ui/renderers/__init__.py:51, 78, 108
from parrot.outputs.formats.assets.design_system import DesignSystem   # TASK-2707
```

### Existing Signatures to Use

```python
# packages/ai-parrot/src/parrot/outputs/a2ui/renderers/__init__.py
class AbstractA2UIRenderer(ABC):                   # line 78
    capabilities: RendererCapabilities             # line 86
    @abstractmethod
    async def render(self, envelope: CreateSurface, *, bake: bool = True) -> "Any | str": ...  # line 89
    # NOTE: the ABC declares NO __init__ — adding one in a subclass is additive

# packages/ai-parrot-visualizations/.../interactive_html.py
_SURFACE_NAME = "interactive-html"                 # line 82
_CHART_JS_SOURCE = _CHART_JS_PATH.read_text(...)   # line 97 — read once at import
_STYLE = (...)                                     # lines 108-138 — DELETE
_BEHAVIOR_JS = r"""..."""                          # line 142 — keep, pass as a script
class InteractiveHTMLRenderer(AbstractA2UIRenderer):   # line 295
    async def render(self, envelope, *, bake=True) -> RenderedArtifact: ...   # line 298
    # document assembled at lines 333-343:
    #   "<!DOCTYPE html>" '<html lang="en"><head><meta charset="utf-8">'
    #   f"<title>{html.escape(envelope.surface_id)}</title>"
    #   f"<style>{_STYLE}</style></head>"
    #   f'<body>{"".join(body_parts)}'
    #   f'<script type="application/json" id="report-data">{data_model_json}</script>'
    #   f"<script>{chart_js}</script>" f"<script>{_BEHAVIOR_JS}</script>"
    #   "</body></html>"

# packages/ai-parrot-visualizations/.../ssr_html.py
_STYLE = (...)                                     # lines 61-79 — DELETE
class SSRHTMLRenderer(AbstractA2UIRenderer):       # line 120
    async def render(self, ...)                    # line 128
    #   f"<style>{_STYLE}</style></head>"          # line 173

# packages/ai-parrot/src/parrot/tools/infographic_recipes/runner.py
    renderer = renderer_cls()                      # line 635 — NO arguments passed today
```

### Class-preservation constraints — these tests exist and must keep passing UNMODIFIED

```
packages/ai-parrot-visualizations/tests/outputs/a2ui_renderers/test_e2e_ssr_html.py:75
    assert doc.count('class="a2ui-text a2ui-cell"') == 6
packages/ai-parrot-visualizations/tests/outputs/a2ui_renderers/test_interactive_html.py:248
    assert '<hr class="a2ui-divider-h">' in doc
packages/ai-parrot-visualizations/tests/outputs/a2ui_renderers/test_interactive_html.py:64-67
    assert externals == [] ; "@import" not in doc ; "<script src=" not in doc ; "<link " not in doc
packages/ai-parrot/tests/integration/test_finance_reporter_narrative_e2e.py:231-288
    asserts a2ui-body / a2ui-summary / a2ui-value / a2ui-card presence and absence
```

### Does NOT Exist

- ~~`a2ui_renderers/_shell.py`~~ — created by this task
- ~~`AbstractA2UIRenderer.__init__`~~ — the ABC defines none; do not call `super().__init__(...)` expecting one
- ~~a `theme` or `layout` parameter on `render()`~~ — the ABC signature is `render(self, envelope, *, bake=True)` and this task does NOT change it; the pair arrives via the constructor
- ~~`CreateSurface.theme`~~ — no such field; the model is `extra="forbid"` (`a2ui/models.py:463`)
- ~~`ssr_html._render_prim_Card`~~ — wrong name: SSR dispatch omits the `_prim_` infix (`ssr_html.py:331`)
- ~~an existing shared base class between the two renderers~~ — they are siblings under the ABC; `PDFRenderer` is the only subclass relationship (`pdf.py:99`, subclasses SSR)

---

## Implementation Notes

### Key Constraints

- **Constructor kwargs MUST default.** `runner.py:635` calls
  `renderer_cls()` today; a required argument breaks every recipe run.
- **Additive classes only.** This task changes the document skeleton and the
  stylesheet, not a single component's class list. If a pre-existing test
  needs editing to pass, you have changed emitted markup — stop and
  reconsider.
- `PDFRenderer` subclasses `SSRHTMLRenderer` (`pdf.py:99`), so it inherits
  this change immediately and will render with `analytics` until TASK-2713
  forces `print`. That is expected and temporary; do not work around it here.
- Keep reading assets at import time only.

### References in Codebase

- `.../interactive_html.py:333-343` — the inline document build being replaced
- `.../ssr_html.py:165-180` — the SSR equivalent
- `.../interactive_html.py:89-97` — import-time asset read, the pattern to preserve

---

## Acceptance Criteria

- [ ] `document_shell()` output contains `<meta name="viewport"`, `<!DOCTYPE html>`, and `div class="ds-page"` with `data-layout` and `data-theme`
- [ ] Neither `interactive_html.py` nor `ssr_html.py` contains a `_STYLE` constant any more
- [ ] Both renderers construct with no arguments and with explicit `theme=`/`layout=`
- [ ] The rendered interactive document still contains the Chart.js bundle, the `report-data` JSON block and `_BEHAVIOR_JS`
- [ ] Every pre-existing test in `packages/ai-parrot-visualizations/tests/` and `packages/ai-parrot/tests/integration/test_finance_reporter_narrative_e2e.py` passes **without modification**
- [ ] The self-contained invariant holds: no `<script src=`, no `<link `, no `@import`
- [ ] Tests pass: `pytest packages/ai-parrot-visualizations/tests/outputs/a2ui_renderers/ -v`
- [ ] `ruff check` and `mypy` clean on all changed files

---

## Test Specification

```python
# packages/ai-parrot-visualizations/tests/outputs/a2ui_renderers/test_document_shell.py
import pytest
from parrot.outputs.a2ui.models import Component, CreateSurface
from parrot.outputs.a2ui_renderers.interactive_html import InteractiveHTMLRenderer
from parrot.outputs.a2ui_renderers.ssr_html import SSRHTMLRenderer


@pytest.fixture
def simple_envelope() -> CreateSurface:
    return CreateSurface(
        surfaceId="shell-test",
        components=[Component(id="root", component="Text", text="hello")],
    )


class TestDocumentShell:
    async def test_shell_emits_viewport_and_wrapper(self, simple_envelope):
        doc = (await InteractiveHTMLRenderer().render(simple_envelope)).content.decode()
        assert '<meta name="viewport"' in doc
        assert 'class="ds-page"' in doc
        assert 'data-layout="analytics"' in doc
        assert 'data-theme="light"' in doc

    async def test_constructor_defaults_preserved(self, simple_envelope):
        """runner.py:635 calls renderer_cls() with no args — this must keep working."""
        assert await InteractiveHTMLRenderer().render(simple_envelope)
        assert await SSRHTMLRenderer().render(simple_envelope)

    async def test_explicit_pair_reaches_the_document(self, simple_envelope):
        doc = (await InteractiveHTMLRenderer(theme="midnight", layout="report")
               .render(simple_envelope)).content.decode()
        assert 'data-theme="midnight"' in doc
        assert 'data-layout="report"' in doc

    async def test_design_system_css_inlined(self, simple_envelope):
        doc = (await InteractiveHTMLRenderer().render(simple_envelope)).content.decode()
        assert ".kpi-card" in doc          # components.css reached the document
        assert "--content-width" in doc    # tokens reached the document

    async def test_self_contained_invariant(self, simple_envelope):
        doc = (await InteractiveHTMLRenderer().render(simple_envelope)).content.decode()
        assert "<script src=" not in doc
        assert "<link " not in doc
        assert "@import" not in doc

    async def test_interactive_keeps_its_scripts(self, simple_envelope):
        doc = (await InteractiveHTMLRenderer().render(simple_envelope)).content.decode()
        assert 'id="report-data"' in doc
        assert "Chart.js" in doc

---

## Agent Instructions

1. **Read the spec** at the path in the header for full context.
2. **Check dependencies** — every `Depends-on` task must be in `sdd/tasks/completed/`.
3. **Verify the Codebase Contract** before writing any code: confirm each
   listed import, signature and line number still holds. If the file has
   shifted, update this contract FIRST, then implement.
4. **Update status** in `sdd/tasks/index/html-renderer-design-system.json` → `"in-progress"`.
5. **Implement** per scope — nothing outside it.
6. **Verify** every acceptance criterion by running it, not by inspection.
7. **Move this file** to `sdd/tasks/completed/`.
8. **Update index** → `"done"`.
9. **Fill in the Completion Note.**

---

## Completion Note

*(Agent fills this in when done)*

**Completed by**:
**Date**:
**Notes**:

**Deviations from spec**: none | describe if any
