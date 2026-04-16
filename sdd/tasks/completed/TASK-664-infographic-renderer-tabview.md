# TASK-664: Renderer — TabViewBlock

**Feature**: Multi-Tab Infographic Template + New Component Blocks
**Spec**: `sdd/specs/multi-tab-infographic.spec.md`
**Status**: done
**Priority**: high
**Estimated effort**: L (4-8h)
**Depends-on**: TASK-659, TASK-663
**Assigned-to**: unassigned

---

## Context

This is the most complex renderer task. It implements the `_render_tab_view()` method, which generates tab navigation HTML, tab pane containers, and recursively renders each pane's blocks. It requires inline vanilla JS for tab switching, unique instance IDs for multiple TabViewBlocks, and print CSS that shows all panes. Depends on TASK-663 because it reuses the `_render_single_block()` helper with depth tracking.

Implements part of Spec Section 3 (Module 4: Renderer).

---

## Scope

- Implement `_render_tab_view(self, block: TabViewBlock, depth: int = 0) -> str`:
  - Generate tab navigation bar with buttons (pill/underline/boxed styles)
  - Support tab icons (emoji in label)
  - Generate tab pane containers with unique IDs
  - Set active tab (from `active_tab` or default to first)
  - Recursively render each pane's blocks using `_render_single_block()` from TASK-663
  - Unique instance prefix per TabViewBlock (tv0, tv1, ...) for JS scoping
- Add `"tab_view": self._render_tab_view` to `_block_renderers` dict
- Add inline vanilla JS for tab switching (scoped by instance prefix)
- Update `_render_blocks()` to pass depth to tab_view and accordion renderers
- Update `_assemble_document()` or `render_to_html()` to inject tab/accordion JS only when those block types are present
- Add CSS for tab navigation and panes to BASE_CSS
- Add print CSS: tab nav hidden, all panes visible with page breaks
- Add responsive CSS: tab nav wraps on mobile
- Write comprehensive tests

**NOT in scope**: BulletList/Table updates (TASK-661), ChecklistBlock (TASK-662), template definition (TASK-660).

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot/src/parrot/outputs/formats/infographic_html.py` | MODIFY | Add `_render_tab_view()`, tab JS, CSS, update `_render_blocks()`, update `render_to_html()` for JS injection |
| `tests/test_infographic_html.py` | MODIFY | Add tab view rendering tests |

---

## Codebase Contract (Anti-Hallucination)

### Verified Imports
```python
from parrot.models.infographic import (
    TabViewBlock, TabPane,          # created by TASK-659
    InfographicBlock,               # verified: infographic.py:392
    InfographicResponse,            # verified: infographic.py:412
)
from parrot.outputs.formats.infographic_html import InfographicHTMLRenderer  # verified: infographic_html.py:412
```

### Existing Signatures to Use
```python
# packages/ai-parrot/src/parrot/outputs/formats/infographic_html.py:424-439
class InfographicHTMLRenderer(BaseRenderer):
    def __init__(self) -> None:
        self._block_renderers: Dict[str, Any] = { ... }  # 12+ entries after TASK-662/663

# packages/ai-parrot/src/parrot/outputs/formats/infographic_html.py:564-600
def _render_blocks(self, data: InfographicResponse) -> str:
    """Render all blocks, grouping consecutive hero_cards."""
    # This method needs to be updated to use _render_single_block for depth tracking

# packages/ai-parrot/src/parrot/outputs/formats/infographic_html.py:473-531
def render_to_html(self, data, theme=None) -> str:
    """Convert InfographicResponse to a complete HTML document."""
    # Line 520-524: checks for charts to inject ECharts JS
    # Similar pattern needed for tab/accordion JS injection

# packages/ai-parrot/src/parrot/outputs/formats/infographic_html.py:535-560
def _assemble_document(self, page_title, theme_css, blocks_html, echarts_script="") -> str:
    """Assemble full HTML5 document. echarts_script goes in <head>."""

# Created by TASK-663:
# def _render_single_block(self, block, depth: int = 0, max_depth: int = 3) -> str:
```

### Does NOT Exist
- ~~`InfographicHTMLRenderer._render_tab_view`~~ — to be created in this task
- ~~`InfographicHTMLRenderer._tab_view_counter`~~ — instance counter to be added

---

## Implementation Notes

### Tab Switching JS (inline vanilla, scoped by instance)
```javascript
function showTab(prefix, id, btn) {
    var container = btn.closest('.tab-view');
    container.querySelectorAll('.tab-view__pane').forEach(function(p) { p.classList.remove('active'); });
    container.querySelectorAll('.tab-view__btn').forEach(function(b) { b.classList.remove('active'); });
    document.getElementById(prefix + '-' + id).classList.add('active');
    btn.classList.add('active');
}
```

### Key Constraints
- Each TabViewBlock instance gets a unique prefix: `tv0`, `tv1`, etc. Use an instance counter on the renderer (reset per `render_to_html()` call).
- Tab pane IDs: `{prefix}-{tab.id}` (e.g., `tv0-overview`, `tv0-phases`)
- The `_render_blocks()` method should be updated to use `_render_single_block()` for all blocks, maintaining the hero_card grouping logic.
- Tab JS and accordion JS should only be injected if the respective block types appear in the response. Detect by scanning `data.blocks` recursively.
- CSS must use only ThemeConfig CSS variables.

### CSS to Add
```css
.tab-view { margin-bottom: 1.5rem; }
.tab-view__nav { display: flex; gap: 6px; flex-wrap: wrap; padding-bottom: 1.25rem;
    border-bottom: 0.5px solid var(--neutral-border); margin-bottom: 1.25rem; }
.tab-view__btn { padding: 6px 14px; border-radius: 20px; border: 0.5px solid var(--neutral-border);
    background: transparent; color: var(--neutral-muted); font-size: 13px; cursor: pointer;
    transition: all 0.2s; }
.tab-view__btn:hover { background: var(--neutral-bg); color: var(--neutral-text); }
.tab-view__btn.active { background: var(--neutral-bg); border-color: var(--primary);
    color: var(--neutral-text); font-weight: 500; }
.tab-view__nav--underline { border-bottom: 2px solid var(--neutral-border); gap: 0; }
.tab-view__nav--underline .tab-view__btn { border: none; border-radius: 0; border-bottom: 2px solid transparent;
    margin-bottom: -2px; }
.tab-view__nav--underline .tab-view__btn.active { border-bottom-color: var(--primary); background: transparent; }
.tab-view__nav--boxed .tab-view__btn { border-radius: 8px; }
.tab-view__pane { display: none; }
.tab-view__pane.active { display: block; }

@media print {
    .tab-view__nav { display: none; }
    .tab-view__pane { display: block !important; page-break-before: always; }
}
@media (max-width: 600px) {
    .tab-view__nav { gap: 4px; }
    .tab-view__btn { font-size: 11px; padding: 4px 10px; }
}
```

### JS Injection Pattern
```python
# In render_to_html(), after rendering blocks:
has_tabs = any(getattr(b, "type", None) == "tab_view" for b in data.blocks)
has_accordion = any(getattr(b, "type", None) == "accordion" for b in data.blocks)
# Also check inside TabPane.blocks for nested accordions
interaction_js = ""
if has_tabs:
    interaction_js += TAB_JS
if has_accordion:
    interaction_js += ACCORDION_JS
# Inject alongside echarts_script
```

---

## Acceptance Criteria

- [ ] `_render_tab_view()` generates correct tab navigation HTML
- [ ] Tab nav buttons styled per `style` field (pills, underline, boxed)
- [ ] Active tab set correctly (from `active_tab` or first by default)
- [ ] Tab pane IDs are unique per TabViewBlock instance (prefix scoping)
- [ ] Each pane's blocks are recursively rendered via `_render_single_block()`
- [ ] Depth tracking works: TabView at depth 0 renders accordion content at depth 1
- [ ] Multiple TabViewBlocks in one infographic don't conflict (unique prefixes)
- [ ] Inline vanilla JS switches tabs correctly
- [ ] Tab/accordion JS only injected when block types are present
- [ ] Print CSS hides tab nav and shows all panes
- [ ] Responsive CSS wraps tab nav on mobile
- [ ] `"tab_view"` entry added to `_block_renderers` dict
- [ ] `_render_blocks()` updated to use depth tracking
- [ ] All tests pass: `pytest tests/test_infographic_html.py -v`

---

## Test Specification

```python
import pytest
from parrot.models.infographic import (
    TabViewBlock, TabPane, SummaryBlock, AccordionBlock, AccordionItem,
    ChecklistBlock, ChecklistItem, TitleBlock, InfographicResponse,
    BulletListBlock,
)
from parrot.outputs.formats.infographic_html import InfographicHTMLRenderer


@pytest.fixture
def renderer():
    return InfographicHTMLRenderer()


class TestTabViewRendering:
    def test_basic_tabs(self, renderer):
        block = TabViewBlock(tabs=[
            TabPane(id="a", label="Tab A", blocks=[SummaryBlock(content="Content A")]),
            TabPane(id="b", label="Tab B", blocks=[SummaryBlock(content="Content B")]),
        ])
        html = renderer._render_tab_view(block)
        assert "Tab A" in html
        assert "Tab B" in html
        assert "tab-view__pane" in html
        assert 'class="tab-view__pane active"' in html  # first pane active

    def test_active_tab(self, renderer):
        block = TabViewBlock(
            tabs=[
                TabPane(id="a", label="A", blocks=[]),
                TabPane(id="b", label="B", blocks=[]),
            ],
            active_tab="b",
        )
        html = renderer._render_tab_view(block)
        # Tab B should be active
        assert 'id="tv0-b"' in html

    def test_pills_style(self, renderer):
        block = TabViewBlock(tabs=[
            TabPane(id="a", label="A", blocks=[]),
            TabPane(id="b", label="B", blocks=[]),
        ], style="pills")
        html = renderer._render_tab_view(block)
        assert "tab-view__nav--pills" in html or "tab-view__nav" in html

    def test_underline_style(self, renderer):
        block = TabViewBlock(tabs=[
            TabPane(id="a", label="A", blocks=[]),
            TabPane(id="b", label="B", blocks=[]),
        ], style="underline")
        html = renderer._render_tab_view(block)
        assert "underline" in html

    def test_nested_blocks_rendered(self, renderer):
        block = TabViewBlock(tabs=[
            TabPane(id="a", label="A", blocks=[
                BulletListBlock(items=["Item 1", "Item 2"]),
                ChecklistBlock(items=[ChecklistItem(text="Check")]),
            ]),
            TabPane(id="b", label="B", blocks=[]),
        ])
        html = renderer._render_tab_view(block)
        assert "Item 1" in html
        assert "Check" in html

    def test_multiple_tab_views_unique_ids(self, renderer):
        block1 = TabViewBlock(tabs=[
            TabPane(id="a", label="A", blocks=[]),
            TabPane(id="b", label="B", blocks=[]),
        ])
        block2 = TabViewBlock(tabs=[
            TabPane(id="a", label="A", blocks=[]),
            TabPane(id="b", label="B", blocks=[]),
        ])
        html1 = renderer._render_tab_view(block1)
        html2 = renderer._render_tab_view(block2)
        # Should have different prefixes
        assert "tv0-" in html1
        assert "tv1-" in html2

    def test_tab_icon_emoji(self, renderer):
        block = TabViewBlock(tabs=[
            TabPane(id="a", label="Overview", icon="📊", blocks=[]),
            TabPane(id="b", label="Details", blocks=[]),
        ])
        html = renderer._render_tab_view(block)
        assert "📊" in html


class TestFullMultiTabInfographic:
    def test_render_to_html(self, renderer):
        response = InfographicResponse(
            template="multi_tab",
            theme="light",
            blocks=[
                TitleBlock(title="Test Report"),
                TabViewBlock(tabs=[
                    TabPane(id="overview", label="Overview", blocks=[
                        SummaryBlock(content="Summary text"),
                    ]),
                    TabPane(id="details", label="Details", blocks=[
                        AccordionBlock(items=[
                            AccordionItem(title="Phase 1", content_blocks=[
                                BulletListBlock(items=["A", "B"]),
                            ]),
                        ]),
                    ]),
                ]),
            ],
        )
        html = renderer.render_to_html(response, theme="light")
        assert "<!DOCTYPE html>" in html
        assert "Test Report" in html
        assert "showTab" in html  # JS injected
        assert "toggleAccordion" in html  # accordion JS injected
        assert "Summary text" in html

    def test_js_not_injected_without_tabs(self, renderer):
        response = InfographicResponse(
            template="basic",
            blocks=[TitleBlock(title="Simple"), SummaryBlock(content="Text")],
        )
        html = renderer.render_to_html(response, theme="light")
        assert "showTab" not in html
```

---

## Agent Instructions

When you pick up this task:

1. **Read the spec** at `sdd/specs/multi-tab-infographic.spec.md`
2. **Check dependencies** — verify TASK-659 and TASK-663 are completed
3. **Verify** TabViewBlock, TabPane exist; `_render_single_block()` exists (from TASK-663)
4. **Read** `_render_blocks()` and `render_to_html()` before modifying
5. **Implement**, **test**, **move to completed**, **update index**

---

## Completion Note

*(Agent fills this in when done)*

**Completed by**: <session or agent ID>
**Date**: YYYY-MM-DD
**Notes**: What was implemented, any deviations from scope, issues encountered.

**Deviations from spec**: none | describe if any
