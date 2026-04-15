# TASK-661: Renderer — BulletList & Table Style Updates

**Feature**: Multi-Tab Infographic Template + New Component Blocks
**Spec**: `sdd/specs/multi-tab-infographic.spec.md`
**Status**: pending
**Priority**: medium
**Estimated effort**: M (2-4h)
**Depends-on**: TASK-659
**Assigned-to**: unassigned

---

## Context

This task updates the existing `_render_bullet_list()` and `_render_table()` methods in `InfographicHTMLRenderer` to support the new styling fields added to `BulletListBlock` and `TableBlock` in TASK-659. It implements part of Spec Section 3 (Module 4: Renderer).

---

## Scope

- Update `_render_bullet_list()` to handle:
  - `color`: render colored dot indicators before each item
  - `columns`: CSS grid layout with N columns (1-4)
  - `style`: BulletListStyle.TITLED renders a styled header with border-bottom
- Update `_render_table()` to handle:
  - `columns` as `List[ColumnDef]`: use width/align/color from each ColumnDef for th elements
  - `style` (TableStyle): apply CSS classes for striped, bordered, compact, comparison variants
  - `responsive`: wrap table in responsive container when True
  - `caption`: render `<caption>` element
- Add CSS for new bullet list and table styles to BASE_CSS
- Ensure backward compatibility: when new fields are None/default, rendering is identical to current output
- Write unit tests for each new rendering variant

**NOT in scope**: AccordionBlock, ChecklistBlock, or TabViewBlock rendering.

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot/src/parrot/outputs/formats/infographic_html.py` | MODIFY | Update `_render_bullet_list()`, `_render_table()`, add CSS |
| `tests/test_infographic_html.py` | MODIFY | Add tests for new bullet list and table rendering |

---

## Codebase Contract (Anti-Hallucination)

### Verified Imports
```python
from parrot.models.infographic import (
    BulletListBlock,    # verified: infographic.py:218
    TableBlock,         # verified: infographic.py:233
    ColumnDef,          # created by TASK-659
    TableStyle,         # created by TASK-659
    BulletListStyle,    # created by TASK-659
)
from parrot.outputs.formats.infographic_html import InfographicHTMLRenderer  # verified: infographic_html.py:412
```

### Existing Signatures to Use
```python
# packages/ai-parrot/src/parrot/outputs/formats/infographic_html.py:865-879
def _render_bullet_list(self, block: BulletListBlock) -> str:
    """Render BulletListBlock as ul/ol with escaped items."""
    ...

# packages/ai-parrot/src/parrot/outputs/formats/infographic_html.py:881-905
def _render_table(self, block: TableBlock) -> str:
    """Render TableBlock as HTML table with thead/tbody, escaped cells."""
    ...

# packages/ai-parrot/src/parrot/outputs/formats/infographic_html.py:71-409
# BASE_CSS — comprehensive stylesheet (CSS string constant at module level)
```

### Does NOT Exist
- ~~`InfographicHTMLRenderer._render_styled_table`~~ — will NOT be created (updating `_render_table` instead)
- ~~`InfographicHTMLRenderer._render_titled_bullet_list`~~ — will NOT be created (updating `_render_bullet_list` instead)

---

## Implementation Notes

### Pattern to Follow
```python
# Existing _render_bullet_list (infographic_html.py:865-879)
# Extend with conditional styling based on new fields:
def _render_bullet_list(self, block: BulletListBlock) -> str:
    # ... existing logic ...
    # If block.color: add dot indicator spans
    # If block.columns: add CSS grid wrapper
    # If block.style == "titled": render header with styled class
```

### Key Constraints
- When `color`, `columns`, `style` are all `None`, output must be IDENTICAL to current renderer.
- Use `html.escape()` for all user-provided text (existing pattern).
- CSS must use only ThemeConfig CSS variables (e.g., `var(--neutral-border)`, `var(--primary)`).
- `ColumnDef.color` should only apply to the `<th>` header, not data cells.
- `TableStyle.COMPARISON` should highlight the first column as labels.

### CSS to Add (approximate)
```css
/* Bullet list columns */
.bullet-list--grid { display: grid; gap: 8px; }
.bullet-list--grid-2 { grid-template-columns: repeat(2, 1fr); }
.bullet-list--grid-3 { grid-template-columns: repeat(3, 1fr); }
.bullet-list--grid-4 { grid-template-columns: repeat(4, 1fr); }
.bullet-list__dot { width: 5px; height: 5px; border-radius: 50%; flex-shrink: 0; margin-top: 5px; }
.bullet-list--titled .bullet-list__header { font-size: 13px; font-weight: 500; padding-bottom: 8px;
    border-bottom: 0.5px solid var(--neutral-border); margin-bottom: 10px; }

/* Table styles */
.data-table--striped tbody tr:nth-child(even) { background: var(--neutral-bg); }
.data-table--bordered { border: 0.5px solid var(--neutral-border); }
.data-table--bordered td, .data-table--bordered th { border: 0.5px solid var(--neutral-border); }
.data-table--compact td, .data-table--compact th { padding: 4px 8px; font-size: 11px; }
.data-table--comparison td:first-child { font-weight: 500; }
.data-table--responsive { overflow-x: auto; }

@media (max-width: 600px) {
    .bullet-list--grid { grid-template-columns: 1fr !important; }
}
```

---

## Acceptance Criteria

- [ ] `_render_bullet_list()` renders colored dots when `color` is set
- [ ] `_render_bullet_list()` renders grid layout when `columns` is set
- [ ] `_render_bullet_list()` renders titled header when `style="titled"`
- [ ] `_render_bullet_list()` output unchanged when all new fields are None
- [ ] `_render_table()` handles `List[ColumnDef]` columns with width/align/color
- [ ] `_render_table()` applies correct CSS class for each `TableStyle` variant
- [ ] `_render_table()` renders `<caption>` when caption is set
- [ ] `_render_table()` wraps in responsive container when responsive=True
- [ ] `_render_table()` output unchanged when new fields are None and columns are `List[str]`
- [ ] All new CSS uses ThemeConfig CSS variables
- [ ] All tests pass: `pytest tests/test_infographic_html.py -v`

---

## Test Specification

```python
import pytest
from parrot.models.infographic import (
    BulletListBlock, BulletListStyle, TableBlock, TableStyle, ColumnDef,
)
from parrot.outputs.formats.infographic_html import InfographicHTMLRenderer


@pytest.fixture
def renderer():
    return InfographicHTMLRenderer()


class TestBulletListRendering:
    def test_backward_compat(self, renderer):
        block = BulletListBlock(items=["A", "B"])
        html = renderer._render_bullet_list(block)
        assert "<li>" in html
        assert "dot" not in html  # no dots without color

    def test_with_color_dots(self, renderer):
        block = BulletListBlock(items=["A"], color="#534AB7")
        html = renderer._render_bullet_list(block)
        assert "#534AB7" in html
        assert "dot" in html

    def test_with_columns(self, renderer):
        block = BulletListBlock(items=["A", "B", "C", "D"], columns=2)
        html = renderer._render_bullet_list(block)
        assert "grid" in html

    def test_titled_style(self, renderer):
        block = BulletListBlock(
            title="Section", items=["A"], style=BulletListStyle.TITLED
        )
        html = renderer._render_bullet_list(block)
        assert "titled" in html


class TestTableRendering:
    def test_backward_compat(self, renderer):
        block = TableBlock(columns=["A", "B"], rows=[["1", "2"]])
        html = renderer._render_table(block)
        assert "<th>" in html
        assert "<td>" in html

    def test_striped_style(self, renderer):
        block = TableBlock(
            columns=["A"], rows=[["1"]], style=TableStyle.STRIPED
        )
        html = renderer._render_table(block)
        assert "striped" in html

    def test_column_def(self, renderer):
        block = TableBlock(
            columns=[ColumnDef(header="Name", width="200px", align="center")],
            rows=[["Alice"]],
        )
        html = renderer._render_table(block)
        assert "200px" in html
        assert "center" in html

    def test_caption(self, renderer):
        block = TableBlock(
            columns=["A"], rows=[["1"]], caption="Table 1"
        )
        html = renderer._render_table(block)
        assert "<caption>" in html
```

---

## Agent Instructions

When you pick up this task:

1. **Read the spec** at `sdd/specs/multi-tab-infographic.spec.md` for full context
2. **Check dependencies** — verify TASK-659 is in `tasks/completed/`
3. **Verify the Codebase Contract** — confirm BulletListStyle, TableStyle, ColumnDef exist (from TASK-659)
4. **Read the current `_render_bullet_list()` and `_render_table()` methods** before modifying
5. **Update status** in `tasks/.index.json` → `"in-progress"`
6. **Implement** following the scope, codebase contract, and notes above
7. **Verify** all acceptance criteria are met
8. **Move this file** to `tasks/completed/TASK-661-infographic-renderer-bullet-table.md`
9. **Update index** → `"done"`

---

## Completion Note

*(Agent fills this in when done)*

**Completed by**: <session or agent ID>
**Date**: YYYY-MM-DD
**Notes**: What was implemented, any deviations from scope, issues encountered.

**Deviations from spec**: none | describe if any
