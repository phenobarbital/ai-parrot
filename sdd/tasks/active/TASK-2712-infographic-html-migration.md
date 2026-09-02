# TASK-2712: Migrate the infographic HTML lane onto the composer

**Feature**: FEAT-493 — Backend HTML Design System
**Spec**: `sdd/specs/html-renderer-design-system.spec.md`
**Status**: pending
**Priority**: medium
**Estimated effort**: M (2-4h)
**Depends-on**: TASK-2708
**Assigned-to**: unassigned

---

## Context

Spec §3 Module 5. `InfographicHTMLRenderer` is the lane that already had a
design system — a ~180-line `BASE_CSS` plus `ThemeConfig` theming — and it is
the reason the other lanes look poor by comparison. This task makes it a
*consumer* of the shared composer instead of the owner of a private
stylesheet, and switches its default to `analytics`.

Unlike the A2UI renderers, this one is NOT missing a shell: it already emits
`<meta viewport>` and a `.container` wrapper (`:1013-1037`), and its theme
resolution already warns and falls back to `light` (`:966-971`).

**This task changes what existing consumers see.** That is the explicit,
user-approved decision recorded in spec §7 and §8: `analytics` becomes the
default everywhere, and `report` reproduces the previous appearance.

---

## Scope

- Replace the `theme_css` + `BASE_CSS` interpolation in
  `_assemble_document` (`:1028-1031`) with a single
  `DesignSystem.stylesheet(theme_name, layout)` call.
- Add a `layout` parameter to the render path, defaulting to `"analytics"`,
  and keep `report` selectable by callers.
- **Reconcile the wrapper class.** The document wraps content in
  `<div class="container">` (`:1035`), and `.container` is defined by
  `layout-report.css` (migrated from `BASE_CSS`). Emit
  `<div class="ds-page container" data-layout="…" data-theme="…">` so the
  report layout keeps its exact hook while `analytics` styles via `.ds-page`.
  Do not silently drop `.container` — TASK-2708's parity test depends on it.
- Delete `BASE_CSS` from this module once the composed sheet is in place.
- Verify every block renderer in this module still finds its selectors:
  callouts, timeline, progress, dividers, quote, image, bullet list, summary,
  KPI, chart container, table container, `.empty-message`,
  `footer.infographic-footer`.

**NOT in scope**: authoring the CSS (TASK-2707/2708); the A2UI renderers;
`ThemeConfig` changes (TASK-2706).

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `.../formats/infographic_html.py` | MODIFY | Composer call; `layout` param; wrapper reconcile; delete `BASE_CSS` |
| `packages/ai-parrot-visualizations/tests/outputs/test_infographic_html_layouts.py` | CREATE | Default-layout and selector-coverage tests |

---

## Codebase Contract (Anti-Hallucination)

### Verified Imports

```python
from parrot.models.infographic import ThemeConfig, theme_registry   # already imported at line 54
from parrot.outputs.formats.assets.design_system import DesignSystem  # TASK-2707
```

### Existing Signatures to Use

```python
# packages/ai-parrot-visualizations/src/parrot/outputs/formats/infographic_html.py
BASE_CSS = """\...                                 # line 176 — ~180 lines, DELETE at the end of this task
class InfographicHTMLRenderer(BaseRenderer):       # line 854
    self._theme_cfg: Optional[ThemeConfig] = None  # line 877
    async def render(self, ...)                    # line 902
    def render_to_html(self, ...)                  # line 931
        # theme resolution, lines 966-971:
        #   try:    theme_cfg = theme_registry.get(theme_name)
        #   except: theme_cfg = theme_registry.get("light")     # already warn-and-fallback
        #   self._theme_cfg = theme_cfg                          # line 971
        # assembly call, line 1003: theme_css=theme_cfg.to_css_variables()
    def _assemble_document(self, page_title, theme_css, blocks_html,
                           echarts_script="", chrome_html="",
                           footer_html="") -> str: ...          # line 1013
        # emits, lines 1023-1037:
        #   <meta charset="UTF-8">
        #   <meta name="viewport" content="width=device-width, initial-scale=1.0">
        #   <style>{theme_css}\n{BASE_CSS}</style>               # lines 1028-1031
        #   <body><div class="container">{chrome_html}{blocks_html}{footer_html}</div></body>
    def _render_document_chrome(self, meta: DocumentMeta) -> str: ...   # line 1041
    def _render_document_footer(self, meta: DocumentMeta) -> str: ...   # line 1094
```

`self._theme_cfg` is read later by chart styling (`:1512`, `:1572`, `:1588`)
— keep populating it; only the CSS assembly changes.

### A byte-identity expectation to respect

`:995-997` comments that document chrome is *"only rendered when
document_meta is populated, so a response with no document_meta produces
byte-identical output."* That invariant is about chrome, not CSS — but do not
introduce chrome, wrappers, or whitespace that varies with unrelated inputs.

### Does NOT Exist

- ~~`InfographicHTMLRenderer.layout`~~ — no layout concept exists in this module today
- ~~a second stylesheet or `EXTRA_CSS` constant~~ — `BASE_CSS` is the only one
- ~~`.ds-page` in this module~~ — net-new from TASK-2707
- ~~an HTML snapshot baseline for this renderer~~ — none exists in-repo; any external screenshot WILL differ after this task, which is the accepted trade-off
- ~~`BaseRenderer.stylesheet()`~~ — the base class provides no CSS hook; verify before assuming any inherited helper

---

## Implementation Notes

### Key Constraints

- `analytics` is the new default; `report` must remain reachable through the
  same call path, not through a private flag.
- Keep `self._theme_cfg` assignment — three chart-styling call sites depend
  on it.
- The existing theme fallback at `:966-971` already does the right thing;
  don't duplicate it with a second try/except inside the composer call.
- Delete `BASE_CSS` only after TASK-2708's parity test is green; the two
  tasks are ordered for exactly this reason.

### References in Codebase

- `.../infographic_html.py:1013-1037` — the assembly being changed
- `.../formats/assets/design_system/layout-report.css` — where `BASE_CSS` now lives (TASK-2708)

---

## Acceptance Criteria

- [ ] `BASE_CSS` no longer exists in `infographic_html.py`
- [ ] The default rendered document composes with `layout="analytics"`
- [ ] `layout="report"` is reachable and produces a document containing `.container`-based legacy rules
- [ ] The wrapper carries `ds-page`, `container`, `data-layout` and `data-theme`
- [ ] Every block type this module renders (KPI, chart, table, summary, bullet list, image, quote, all five callouts, divider variants, timeline, progress, empty message, footer) finds its selectors in the composed sheet
- [ ] `self._theme_cfg` is still populated for the chart-styling call sites at `:1512`, `:1572`, `:1588`
- [ ] The self-contained rule holds: no `@import`, no external `<link>`
- [ ] Pre-existing infographic tests pass (`packages/ai-parrot/tests/outputs/formats/`), modified only where they asserted the old default appearance
- [ ] Tests pass: `pytest packages/ai-parrot-visualizations/tests/outputs/ packages/ai-parrot/tests/outputs/formats/ -v`

---

## Test Specification

```python
# packages/ai-parrot-visualizations/tests/outputs/test_infographic_html_layouts.py
import pytest


class TestInfographicLayouts:
    def test_default_layout_is_analytics(self): ...
    def test_report_layout_still_reachable(self): ...
    def test_wrapper_carries_both_classes(self):
        """ds-page for the new layouts, container for report parity."""
    def test_no_base_css_constant(self):
        import parrot.outputs.formats.infographic_html as m
        assert not hasattr(m, "BASE_CSS")
    def test_theme_cfg_still_populated(self): ...

    @pytest.mark.parametrize("block_selector", [
        ".kpi-grid", ".kpi-card", ".chart-container", ".table-container",
        ".summary-block", ".bullet-list-block", ".image-block",
        "blockquote.quote-block", ".callout-block.info", ".callout-block.success",
        ".callout-block.warning", ".callout-block.error", ".callout-block.tip",
        "hr.divider", ".timeline-block", ".progress-block",
        ".empty-message", "footer.infographic-footer",
    ])
    def test_every_block_selector_present(self, block_selector): ...
```

---

## Agent Instructions

1. **Read the spec** (§3 Module 5, §7 Known Risks — the default visual
   change is intentional and signed off).
2. **Check dependencies** — TASK-2708 must be completed AND its parity test
   green; deleting `BASE_CSS` before that loses the reference.
3. **Verify the Codebase Contract**, especially the `_assemble_document`
   signature and the three `self._theme_cfg` readers.
4. **Update status** in the per-spec index → `"in-progress"`.
5. **Implement** per scope.
6. **Verify** every acceptance criterion.
7. **Move this file** to `sdd/tasks/completed/`, update the index → `"done"`,
   fill in the Completion Note.

---

## Completion Note

*(Agent fills this in when done)*

**Completed by**:
**Date**:
**Notes**:

**Deviations from spec**: none | describe if any
