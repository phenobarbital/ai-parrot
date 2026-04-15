# TASK-662: Renderer — ChecklistBlock

**Feature**: Multi-Tab Infographic Template + New Component Blocks
**Spec**: `sdd/specs/multi-tab-infographic.spec.md`
**Status**: pending
**Priority**: medium
**Estimated effort**: S (< 2h)
**Depends-on**: TASK-659
**Assigned-to**: unassigned

---

## Context

This task implements the `_render_checklist()` method in `InfographicHTMLRenderer` and its CSS. It is a relatively simple block with no recursion or JS requirements. Implements part of Spec Section 3 (Module 4: Renderer).

---

## Scope

- Implement `_render_checklist(self, block: ChecklistBlock) -> str` in `InfographicHTMLRenderer`
- Add `"checklist": self._render_checklist` to `_block_renderers` dict in `__init__`
- Render HTML structure:
  - Optional title header
  - List of items with visual checkbox indicators
  - Checked items get `--checked` modifier class with checkmark
  - Optional description text below each item
  - Style variants: default, acceptance, todo, compact
- Add CSS for checklist to BASE_CSS
- Write unit tests

**NOT in scope**: AccordionBlock, TabViewBlock, BulletList/Table updates.

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot/src/parrot/outputs/formats/infographic_html.py` | MODIFY | Add `_render_checklist()`, CSS, register in dispatch dict |
| `tests/test_infographic_html.py` | MODIFY | Add checklist rendering tests |

---

## Codebase Contract (Anti-Hallucination)

### Verified Imports
```python
from parrot.models.infographic import ChecklistBlock, ChecklistItem  # created by TASK-659
from parrot.outputs.formats.infographic_html import InfographicHTMLRenderer  # verified: infographic_html.py:412
```

### Existing Signatures to Use
```python
# packages/ai-parrot/src/parrot/outputs/formats/infographic_html.py:424-439
def __init__(self) -> None:
    self._md = markdown_it.MarkdownIt()
    self._block_renderers: Dict[str, Any] = {
        "title": self._render_title,
        # ... 12 entries
    }

# Pattern: every render method returns str, takes a single block argument
# e.g. infographic_html.py:947-959
def _render_callout(self, block: CalloutBlock) -> str:
    """Render CalloutBlock as alert box styled by level."""
    ...
```

### Does NOT Exist
- ~~`InfographicHTMLRenderer._render_checklist`~~ — to be created in this task

---

## Implementation Notes

### Pattern to Follow
```python
# Follow _render_callout pattern (infographic_html.py:947-959)
def _render_checklist(self, block: ChecklistBlock) -> str:
    style_cls = f"checklist--{block.style}" if block.style else ""
    parts = [f'        <div class="checklist {style_cls}">']
    if block.title:
        parts.append(f'          <div class="checklist__title">{escape(block.title)}</div>')
    parts.append('          <div class="checklist__items">')
    for item in block.items:
        checked_cls = " checklist__item--checked" if item.checked else ""
        check_mark = "&#10003;" if item.checked else ""
        parts.append(f'            <div class="checklist__item{checked_cls}">')
        parts.append(f'              <div class="checklist__checkbox">{check_mark}</div>')
        parts.append(f'              <span>{escape(item.text)}</span>')
        if item.description:
            parts.append(f'              <div class="checklist__desc">{escape(item.description)}</div>')
        parts.append('            </div>')
    parts.append('          </div>')
    parts.append('        </div>')
    return "\n".join(parts)
```

### CSS to Add
```css
.checklist { margin-bottom: 1rem; }
.checklist__title { font-size: 13px; font-weight: 600; margin-bottom: 8px; color: var(--neutral-text); }
.checklist__items { display: flex; flex-direction: column; gap: 6px; }
.checklist__item { display: flex; gap: 8px; align-items: flex-start; font-size: 12px; color: var(--neutral-text); }
.checklist__checkbox { width: 16px; height: 16px; border-radius: 3px; border: 1px solid var(--neutral-border);
    flex-shrink: 0; display: flex; align-items: center; justify-content: center; font-size: 10px; }
.checklist__item--checked .checklist__checkbox { background: var(--accent-green); border-color: var(--accent-green); color: #fff; }
.checklist__desc { font-size: 11px; color: var(--neutral-muted); margin-left: 24px; }
.checklist--acceptance .checklist__title { color: var(--primary); }
.checklist--compact .checklist__item { gap: 4px; font-size: 11px; }
.checklist--compact .checklist__checkbox { width: 12px; height: 12px; font-size: 8px; }
```

---

## Acceptance Criteria

- [ ] `_render_checklist()` renders correct HTML with checkbox visuals
- [ ] Checked items display checkmark and green background
- [ ] Unchecked items display empty checkbox
- [ ] Optional title renders when present
- [ ] Optional description renders below item text
- [ ] Style variants (acceptance, todo, compact) apply correct CSS classes
- [ ] `"checklist"` entry added to `_block_renderers` dict
- [ ] CSS uses only ThemeConfig CSS variables
- [ ] All tests pass: `pytest tests/test_infographic_html.py -v`

---

## Test Specification

```python
import pytest
from parrot.models.infographic import ChecklistBlock, ChecklistItem
from parrot.outputs.formats.infographic_html import InfographicHTMLRenderer


@pytest.fixture
def renderer():
    return InfographicHTMLRenderer()


class TestChecklistRendering:
    def test_basic(self, renderer):
        block = ChecklistBlock(items=[
            ChecklistItem(text="Item 1", checked=True),
            ChecklistItem(text="Item 2"),
        ])
        html = renderer._render_checklist(block)
        assert "checklist__item--checked" in html
        assert "Item 1" in html
        assert "Item 2" in html

    def test_with_title(self, renderer):
        block = ChecklistBlock(title="Criteria", items=[ChecklistItem(text="A")])
        html = renderer._render_checklist(block)
        assert "Criteria" in html
        assert "checklist__title" in html

    def test_with_description(self, renderer):
        block = ChecklistBlock(items=[
            ChecklistItem(text="X", description="Details here"),
        ])
        html = renderer._render_checklist(block)
        assert "Details here" in html

    def test_acceptance_style(self, renderer):
        block = ChecklistBlock(items=[ChecklistItem(text="A")], style="acceptance")
        html = renderer._render_checklist(block)
        assert "checklist--acceptance" in html

    def test_xss_prevention(self, renderer):
        block = ChecklistBlock(items=[ChecklistItem(text="<script>alert(1)</script>")])
        html = renderer._render_checklist(block)
        assert "<script>" not in html
```

---

## Agent Instructions

When you pick up this task:

1. **Read the spec** at `sdd/specs/multi-tab-infographic.spec.md`
2. **Check dependencies** — verify TASK-659 is completed
3. **Verify** ChecklistBlock and ChecklistItem exist in infographic.py (from TASK-659)
4. **Read** the current `_render_callout()` method as a pattern reference
5. **Implement**, **test**, **move to completed**, **update index**

---

## Completion Note

*(Agent fills this in when done)*

**Completed by**: <session or agent ID>
**Date**: YYYY-MM-DD
**Notes**: What was implemented, any deviations from scope, issues encountered.

**Deviations from spec**: none | describe if any
