# TASK-663: Renderer — AccordionBlock

**Feature**: Multi-Tab Infographic Template + New Component Blocks
**Spec**: `sdd/specs/multi-tab-infographic.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: M (2-4h)
**Depends-on**: TASK-659
**Assigned-to**: unassigned

---

## Context

This task implements the `_render_accordion()` method in `InfographicHTMLRenderer`. The accordion block is moderately complex because it supports recursive block rendering (`content_blocks`) and HTML sanitization (`html_content` via `nh3`). It also requires inline vanilla JS for expand/collapse behavior. Implements part of Spec Section 3 (Module 4: Renderer).

This task also introduces the `nh3` dependency and the depth-tracked `_render_block()` helper that will be reused by TASK-664 (TabViewBlock).

---

## Scope

- Add `nh3` to `pyproject.toml` dependencies
- Implement `_render_accordion(self, block: AccordionBlock, depth: int = 0) -> str`:
  - Render each AccordionItem as a collapsible section
  - If `content_blocks` is non-empty, render each block recursively using a new `_render_single_block(block, depth)` helper
  - If `content_blocks` is empty and `html_content` is provided, sanitize via `nh3` and render
  - Support AccordionItem fields: id (auto-generate if None), title, subtitle, badge, badge_color, number, number_color, expanded
  - Enforce `max_depth=3`: if depth > max_depth, emit HTML comment instead of rendering
- Add `"accordion": self._render_accordion` to `_block_renderers` dict
- Implement depth-tracked `_render_single_block(self, block, depth: int = 0) -> str` helper:
  - Dispatches to the correct render method based on block type
  - Passes `depth` to accordion and tab_view renderers
  - Returns HTML comment when depth > max_depth
- Add inline vanilla JS for accordion toggle (from curated collection pattern)
- Add CSS for accordion to BASE_CSS
- Add print CSS: `.accordion__body { display: block !important; }` in `@media print`
- Write unit tests

**NOT in scope**: TabViewBlock rendering (TASK-664), template changes.

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot/pyproject.toml` | MODIFY | Add `nh3>=0.2.14` dependency |
| `packages/ai-parrot/src/parrot/outputs/formats/infographic_html.py` | MODIFY | Add `_render_accordion()`, `_render_single_block()`, accordion JS, CSS, register in dispatch |
| `tests/test_infographic_html.py` | MODIFY | Add accordion rendering tests |

---

## Codebase Contract (Anti-Hallucination)

### Verified Imports
```python
from parrot.models.infographic import (
    AccordionBlock, AccordionItem,  # created by TASK-659
    InfographicBlock,               # verified: infographic.py:392
    BulletListBlock,                # verified: infographic.py:218
)
from parrot.outputs.formats.infographic_html import InfographicHTMLRenderer  # verified: infographic_html.py:412
import nh3  # to be added to pyproject.toml in this task
```

### Existing Signatures to Use
```python
# packages/ai-parrot/src/parrot/outputs/formats/infographic_html.py:424-439
class InfographicHTMLRenderer(BaseRenderer):
    def __init__(self) -> None:
        self._md = markdown_it.MarkdownIt()
        self._block_renderers: Dict[str, Any] = { ... }  # 12 entries

# packages/ai-parrot/src/parrot/outputs/formats/infographic_html.py:564-600
def _render_blocks(self, data: InfographicResponse) -> str:
    """Render all blocks, grouping consecutive hero_cards."""
    # Uses self._block_renderers.get(block_type) for dispatch

# packages/ai-parrot/src/parrot/outputs/formats/infographic_html.py:535-560
def _assemble_document(self, page_title, theme_css, blocks_html, echarts_script="") -> str:
    """Assemble the full HTML5 document."""
    # Inline JS can be injected via echarts_script parameter or by extending the template
```

### Does NOT Exist
- ~~`InfographicHTMLRenderer._render_accordion`~~ — to be created in this task
- ~~`InfographicHTMLRenderer._render_single_block`~~ — to be created in this task
- ~~`nh3`~~ — NOT yet in pyproject.toml (to be added in this task)
- ~~`bleach`~~ — NOT to be used (deprecated)

---

## Implementation Notes

### Pattern to Follow
```python
# New depth-tracked single block renderer
def _render_single_block(self, block, depth: int = 0, max_depth: int = 3) -> str:
    """Render a single block with depth tracking for nested structures."""
    block_type = getattr(block, "type", None)
    if depth > max_depth:
        return f"        <!-- max nesting depth ({max_depth}) exceeded for {block_type} -->"
    renderer = self._block_renderers.get(block_type)
    if renderer is None:
        return ""
    # For accordion and tab_view, pass depth
    if block_type in ("accordion", "tab_view"):
        return renderer(block, depth=depth)
    return renderer(block)
```

### Accordion JS (inline vanilla)
```javascript
function toggleAccordion(el) {
    var item = el.closest('.accordion__item');
    var parent = item.closest('.accordion');
    var allowMultiple = parent.dataset.allowMultiple === 'true';
    if (!allowMultiple) {
        parent.querySelectorAll('.accordion__item.open').forEach(function(i) {
            if (i !== item) i.classList.remove('open');
        });
    }
    item.classList.toggle('open');
}
```

### Key Constraints
- `nh3.clean()` with restricted tags: `p, br, strong, em, ul, ol, li, a, span, div, h3, h4, code, pre, table, tr, td, th, thead, tbody`
- `content_blocks` takes priority over `html_content` — if `content_blocks` is non-empty, ignore `html_content`
- Auto-generate AccordionItem.id using slugified title or a counter if id is None
- JS must be self-contained — no external dependencies
- The `_render_single_block` helper will also be used by TASK-664 for TabViewBlock

### CSS to Add
```css
.accordion { display: flex; flex-direction: column; gap: 8px; margin-bottom: 1rem; }
.accordion__title { font-size: 14px; font-weight: 600; margin-bottom: 8px; color: var(--neutral-text); }
.accordion__item { border: 0.5px solid var(--neutral-border); border-radius: 12px; overflow: hidden; }
.accordion__header { display: flex; align-items: center; gap: 12px; padding: 12px 16px; cursor: pointer;
    background: transparent; border: none; width: 100%; text-align: left; }
.accordion__header:hover { background: var(--neutral-bg); }
.accordion__arrow { transition: transform 0.2s; font-size: 10px; color: var(--neutral-muted); }
.accordion__item.open .accordion__arrow { transform: rotate(90deg); }
.accordion__number { width: 28px; height: 28px; border-radius: 50%; display: flex; align-items: center;
    justify-content: center; font-size: 12px; font-weight: 600; color: #fff; flex-shrink: 0; }
.accordion__item-title { font-size: 13px; font-weight: 500; color: var(--neutral-text); }
.accordion__subtitle { font-size: 11px; color: var(--neutral-muted); }
.accordion__badge { font-size: 10px; padding: 2px 8px; border-radius: 10px; font-weight: 500; }
.accordion__body { display: none; padding: 16px; border-top: 0.5px solid var(--neutral-border); }
.accordion__item.open .accordion__body { display: block; }

@media print {
    .accordion__body { display: block !important; }
    .accordion__arrow { display: none; }
}
```

---

## Acceptance Criteria

- [ ] `nh3` added to pyproject.toml dependencies
- [ ] `_render_accordion()` renders collapsible sections with correct HTML structure
- [ ] AccordionItem with `content_blocks` recursively renders inner blocks
- [ ] AccordionItem with `html_content` (no content_blocks) sanitizes via `nh3` and renders
- [ ] `content_blocks` takes priority over `html_content`
- [ ] AccordionItem.id auto-generated when None
- [ ] AccordionItem fields rendered: title, subtitle, badge (with color), number (with color), expanded
- [ ] `expanded=True` items have `open` class by default
- [ ] Depth limit enforced: blocks beyond max_depth=3 produce HTML comment
- [ ] `allow_multiple` data attribute set on accordion container
- [ ] Inline vanilla JS toggles accordion items
- [ ] Print CSS expands all accordion bodies
- [ ] `"accordion"` entry added to `_block_renderers` dict
- [ ] XSS test: malicious html_content is sanitized
- [ ] All tests pass: `pytest tests/test_infographic_html.py -v`

---

## Test Specification

```python
import pytest
from parrot.models.infographic import (
    AccordionBlock, AccordionItem, BulletListBlock, SummaryBlock,
)
from parrot.outputs.formats.infographic_html import InfographicHTMLRenderer


@pytest.fixture
def renderer():
    return InfographicHTMLRenderer()


class TestAccordionRendering:
    def test_basic_accordion(self, renderer):
        block = AccordionBlock(items=[
            AccordionItem(title="Section 1"),
            AccordionItem(title="Section 2"),
        ])
        html = renderer._render_accordion(block)
        assert "Section 1" in html
        assert "Section 2" in html
        assert "accordion__item" in html

    def test_with_content_blocks(self, renderer):
        block = AccordionBlock(items=[
            AccordionItem(
                title="Phase 1",
                content_blocks=[BulletListBlock(items=["A", "B"])],
            ),
        ])
        html = renderer._render_accordion(block)
        assert "<li>" in html  # bullet list rendered inside

    def test_with_html_content(self, renderer):
        block = AccordionBlock(items=[
            AccordionItem(title="X", html_content="<p>Hello <strong>world</strong></p>"),
        ])
        html = renderer._render_accordion(block)
        assert "<p>Hello" in html
        assert "<strong>" in html

    def test_html_content_xss_sanitized(self, renderer):
        block = AccordionBlock(items=[
            AccordionItem(title="X", html_content="<script>alert(1)</script><p>Safe</p>"),
        ])
        html = renderer._render_accordion(block)
        assert "<script>" not in html
        assert "<p>Safe</p>" in html

    def test_content_blocks_priority(self, renderer):
        block = AccordionBlock(items=[
            AccordionItem(
                title="X",
                content_blocks=[SummaryBlock(content="From blocks")],
                html_content="<p>From HTML</p>",
            ),
        ])
        html = renderer._render_accordion(block)
        assert "From blocks" in html
        assert "From HTML" not in html

    def test_expanded_item(self, renderer):
        block = AccordionBlock(items=[
            AccordionItem(title="X", expanded=True),
        ])
        html = renderer._render_accordion(block)
        assert "open" in html

    def test_depth_limit(self, renderer):
        block = AccordionBlock(items=[
            AccordionItem(title="X", content_blocks=[
                AccordionBlock(items=[AccordionItem(title="Nested")])
            ]),
        ])
        # depth=0 → accordion body renders at depth=1 → nested accordion at depth=2
        html = renderer._render_accordion(block, depth=2)
        # The nested accordion should render since depth=2 < max_depth=3
        # but if we test with depth=3, it should be skipped
        html_deep = renderer._render_accordion(block, depth=3)
        assert "max nesting depth" in html_deep

    def test_number_and_badge(self, renderer):
        block = AccordionBlock(items=[
            AccordionItem(title="Phase 1", number=1, number_color="#534AB7",
                         badge="Weeks 1-2", badge_color="#e8e4f8"),
        ])
        html = renderer._render_accordion(block)
        assert "#534AB7" in html
        assert "Weeks 1-2" in html
```

---

## Agent Instructions

When you pick up this task:

1. **Read the spec** at `sdd/specs/multi-tab-infographic.spec.md`
2. **Check dependencies** — verify TASK-659 is completed
3. **Verify** AccordionBlock and AccordionItem exist in infographic.py
4. **Add `nh3`** to pyproject.toml and run `source .venv/bin/activate && uv pip install nh3`
5. **Implement**, **test**, **move to completed**, **update index**

---

## Completion Note

*(Agent fills this in when done)*

**Completed by**: <session or agent ID>
**Date**: YYYY-MM-DD
**Notes**: What was implemented, any deviations from scope, issues encountered.

**Deviations from spec**: none | describe if any
