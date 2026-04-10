# TASK-645: HTML Block Renderers

**Feature**: infographic-html-output
**Spec**: `sdd/specs/infographic-html-output.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: L (4-8h)
**Depends-on**: TASK-644
**Assigned-to**: unassigned

---

## Context

> Implements Module 2 from the spec. This is the core task: create
> `InfographicHTMLRenderer` that converts `InfographicResponse` blocks
> into a complete, self-contained HTML5 document with inline CSS.
> Chart blocks are handled as placeholders here; full ECharts integration
> is in TASK-646.

---

## Scope

- Create `parrot/outputs/formats/infographic_html.py` with class
  `InfographicHTMLRenderer(BaseRenderer)`.
- Implement `async render()` method (BaseRenderer interface).
- Implement `render_to_html(data, theme=None)` standalone method that accepts
  either an `InfographicResponse` model or a raw dict (model_validate if dict).
- Implement per-block-type render methods for all 12 block types:
  - `_render_title(block)` — hero header with gradient background, h1 + subtitle
  - `_render_hero_card(block)` — KPI card with value, label, trend arrow, color
  - `_render_summary(block)` — markdown-rendered rich text paragraph
  - `_render_chart(block)` — placeholder `<div>` for chart (TASK-646 adds ECharts)
  - `_render_bullet_list(block)` — `<ul>` or `<ol>` with items
  - `_render_table(block)` — HTML `<table>` with thead/tbody
  - `_render_image(block)` — `<img>` with alt text and optional caption
  - `_render_quote(block)` — `<blockquote>` with attribution
  - `_render_callout(block)` — alert box styled by level (info/success/warning/error/tip)
  - `_render_divider(block)` — `<hr>` with style (solid/dashed/dotted/gradient)
  - `_render_timeline(block)` — chronological event list with date markers
  - `_render_progress(block)` — progress bars with percentages and labels
- Implement block dispatch: dict mapping `BlockType` → render method.
- Unknown block types: skip with `logging.warning()`.
- Empty blocks list: render minimal page with "No data available" message.
- Use `markupsafe.escape()` for ALL user text fields (XSS prevention).
- Use `markdown_it.MarkdownIt()` with default config (`html=False`) for SummaryBlock.
- Assemble full HTML5 document: `<!DOCTYPE html>`, `<head>` with inline CSS
  (from ThemeConfig.to_css_variables() + base CSS), `<body>` with rendered blocks.
- Base CSS: extract from `docs/infographic-1775694709159.html` — classes for
  `.container`, `.hero`, `.kpi-grid`, `.kpi-card`, `.section-title`, `.chart-container`,
  `.insight-box`, `.insight-list`, table styles, responsive breakpoints, print styles.
- Extract `_extract_infographic_data()` logic by importing from existing
  `InfographicRenderer` or duplicating the method.

**NOT in scope**:
- ECharts JS integration (TASK-646 — chart blocks render as placeholder divs here)
- Content negotiation wiring (TASK-647)
- Theme creation (TASK-644, already done)

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot/src/parrot/outputs/formats/infographic_html.py` | CREATE | Main HTML renderer |
| `packages/ai-parrot/src/parrot/outputs/formats/__init__.py` | MODIFY | Add lazy-load entry for infographic_html |

---

## Codebase Contract (Anti-Hallucination)

### Verified Imports
```python
# Base class
from parrot.outputs.formats.base import BaseRenderer  # verified: base.py:54

# Renderer registration
from parrot.outputs.formats import register_renderer  # verified: __init__.py:17

# Models
from parrot.models.infographic import (
    InfographicResponse,  # verified: infographic.py:311
    InfographicBlock,     # verified: infographic.py:291 (Union type)
    BlockType,            # verified: infographic.py:38
    ChartType,            # verified: infographic.py:54
    TitleBlock,           # verified: infographic.py:90
    HeroCardBlock,        # verified: infographic.py:100
    SummaryBlock,         # verified: infographic.py:124
    ChartBlock,           # verified: infographic.py:148
    BulletListBlock,      # verified: infographic.py:168
    TableBlock,           # verified: infographic.py:183
    ImageBlock,           # verified: infographic.py:202
    QuoteBlock,           # verified: infographic.py:212
    CalloutBlock,         # verified: infographic.py:220
    DividerBlock,         # verified: infographic.py:231
    TimelineBlock,        # verified: infographic.py:249
    ProgressBlock,        # verified: infographic.py:277
    TrendDirection,       # verified: infographic.py:70
    CalloutLevel,         # verified: infographic.py:77
)

# Theme (created by TASK-644)
from parrot.models.infographic import ThemeConfig, theme_registry

# Output mode
from parrot.models.outputs import OutputMode  # verified: outputs.py:39

# Existing renderer (for _extract_infographic_data reuse)
from parrot.outputs.formats.infographic import InfographicRenderer  # verified: infographic.py:45

# External libraries
from markupsafe import escape  # verified: installed (dependency of Jinja2)
import markdown_it  # verified: markdown-it-py 4.0.0 installed
```

### Existing Signatures to Use
```python
# parrot/outputs/formats/base.py:54
class BaseRenderer(ABC):
    @abstractmethod
    async def render(self, response: Any, environment: str = 'default', **kwargs) -> Tuple[str, Optional[Any]]:
        ...

# parrot/outputs/formats/infographic.py:75-134
class InfographicRenderer(BaseRenderer):
    def _extract_infographic_data(self, response: Any) -> dict:  # line 75
        """Extracts InfographicResponse dict from AIMessage. Handles:
        - response.structured_output (InfographicResponse)
        - response.output (dict or InfographicResponse)
        - response.data
        - string fallback (JSON parse)
        - last resort: wraps raw content as summary block
        Returns: dict with 'blocks' key."""

# parrot/outputs/formats/__init__.py:17-31
def register_renderer(mode: OutputMode, system_prompt: Optional[str] = None):
    """Decorator to register renderer."""

# parrot/outputs/formats/__init__.py:33-89
def get_renderer(mode: OutputMode) -> Type[Renderer]:
    """Lazy-loads and returns renderer. Line 82-83 handles INFOGRAPHIC."""

# Block model key fields (all verified in infographic.py):
# TitleBlock(90): title: str, subtitle: Optional[str], author: Optional[str], date: Optional[str]
# HeroCardBlock(100): label: str, value: str, icon: Optional[str], trend: Optional[TrendDirection],
#                      trend_value: Optional[str], comparison_period: Optional[str], color: Optional[str]
# SummaryBlock(124): title: Optional[str], content: str, highlight: Optional[bool]
# ChartBlock(148): chart_type: ChartType, title: Optional[str], labels: List[str],
#                  series: List[ChartDataSeries], x_axis_label, y_axis_label, stacked, show_legend
# BulletListBlock(168): title: Optional[str], items: List[str], ordered: Optional[bool], icon: Optional[str]
# TableBlock(183): title: Optional[str], columns: List[str], rows: List[List[str]],
#                  highlight_first_column: Optional[bool], sortable: Optional[bool]
# ImageBlock(202): url: Optional[str], base64: Optional[str], alt: Optional[str], caption: Optional[str]
# QuoteBlock(212): text: str, author: Optional[str], source: Optional[str]
# CalloutBlock(220): level: CalloutLevel, title: Optional[str], content: str
# DividerBlock(231): style: Optional[str]  # solid/dashed/dotted/gradient
# TimelineEvent(240): date: str, title: str, description: Optional[str], icon: Optional[str], color: Optional[str]
# TimelineBlock(249): title: Optional[str], events: List[TimelineEvent]
# ProgressItem(259): label: str, value: int (0-100), color: Optional[str], target: Optional[int]
# ProgressBlock(277): title: Optional[str], items: List[ProgressItem]
```

### Does NOT Exist
- ~~`parrot.outputs.formats.infographic_html`~~ — this task creates it
- ~~`InfographicRenderer.render_html()`~~ — no such method
- ~~`InfographicResponse.to_html()`~~ — no such method on the model
- ~~`BaseRenderer.render_to_html()`~~ — not part of the base class
- ~~`OutputMode.INFOGRAPHIC_HTML`~~ — does not exist; no new OutputMode needed

---

## Implementation Notes

### CSS Reference
Extract the full CSS from `docs/infographic-1775694709159.html` as a constant string.
Use CSS custom properties (`var(--primary)`, etc.) so themes work by just changing `:root`.
Include responsive breakpoints (`@media (max-width: 600px)`) and print styles.

### Document Structure
```html
<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>{title}</title>
    <style>
        {theme_css_variables}
        {base_css}
    </style>
    <!-- ECharts script will be injected here by TASK-646 -->
</head>
<body>
    <div class="container">
        {rendered_blocks}
    </div>
</body>
</html>
```

### Block Dispatch Pattern
```python
self._block_renderers = {
    "title": self._render_title,
    "hero_card": self._render_hero_card,
    "summary": self._render_summary,
    "chart": self._render_chart,
    "bullet_list": self._render_bullet_list,
    "table": self._render_table,
    "image": self._render_image,
    "quote": self._render_quote,
    "callout": self._render_callout,
    "divider": self._render_divider,
    "timeline": self._render_timeline,
    "progress": self._render_progress,
}
```

### Hero Card Grouping
Multiple consecutive `hero_card` blocks should be wrapped in a single
`<div class="kpi-grid">` container (matching the reference HTML pattern).

### Markdown Rendering
```python
md = markdown_it.MarkdownIt()  # html=False by default (safe)
html_content = md.render(block.content)
```

### Key Constraints
- ALL user text must go through `markupsafe.escape()` BEFORE insertion
- Exception: markdown-rendered content (markdown_it already escapes HTML)
- `render_to_html()` must work standalone (no HTTP context, no AIMessage)
- Chart blocks: render a `<div class="chart-container" id="chart-{n}">` placeholder
  with a `data-chart-config` attribute containing the JSON config. TASK-646 will add
  the `<script>` tags to initialize ECharts.

---

## Acceptance Criteria

- [ ] `InfographicHTMLRenderer` inherits from `BaseRenderer`
- [ ] `render()` async method returns `Tuple[str, Optional[Any]]`
- [ ] `render_to_html()` accepts `InfographicResponse` or dict, returns HTML string
- [ ] All 12 block types render to correct HTML structure
- [ ] Hero cards are grouped in `<div class="kpi-grid">`
- [ ] HTML is a complete document (doctype, head, body, inline CSS)
- [ ] CSS uses `:root` variables matching theme system
- [ ] User text is HTML-escaped (no XSS)
- [ ] Markdown in SummaryBlock renders correctly
- [ ] Unknown block types produce a warning, not a crash
- [ ] Empty blocks produce a minimal page

---

## Test Specification

```python
import pytest
from parrot.outputs.formats.infographic_html import InfographicHTMLRenderer
from parrot.models.infographic import (
    InfographicResponse, TitleBlock, HeroCardBlock, SummaryBlock,
    ChartBlock, ChartType, ChartDataSeries, BulletListBlock,
    TableBlock, CalloutBlock, CalloutLevel, DividerBlock,
    TimelineBlock, TimelineEvent, ProgressBlock, ProgressItem,
    ImageBlock, QuoteBlock, TrendDirection,
)


@pytest.fixture
def renderer():
    return InfographicHTMLRenderer()


@pytest.fixture
def basic_response():
    return InfographicResponse(
        template="basic", theme="light",
        blocks=[
            TitleBlock(type="title", title="Test", subtitle="Sub"),
            HeroCardBlock(type="hero_card", label="KPI", value="100"),
            SummaryBlock(type="summary", content="**Bold** text"),
        ],
    )


class TestInfographicHTMLRenderer:
    def test_render_to_html_returns_string(self, renderer, basic_response):
        html = renderer.render_to_html(basic_response)
        assert isinstance(html, str)
        assert "<!DOCTYPE html>" in html

    def test_render_to_html_from_dict(self, renderer, basic_response):
        html = renderer.render_to_html(basic_response.model_dump())
        assert "<!DOCTYPE html>" in html

    def test_title_block(self, renderer):
        block = TitleBlock(type="title", title="Hello", subtitle="World")
        html = renderer._render_title(block)
        assert "Hello" in html
        assert "World" in html

    def test_hero_card_block(self, renderer):
        block = HeroCardBlock(type="hero_card", label="Rev", value="$1M",
                             trend=TrendDirection.UP, trend_value="+10%")
        html = renderer._render_hero_card(block)
        assert "$1M" in html
        assert "Rev" in html

    def test_summary_markdown(self, renderer):
        block = SummaryBlock(type="summary", content="**bold** and *italic*")
        html = renderer._render_summary(block)
        assert "<strong>bold</strong>" in html
        assert "<em>italic</em>" in html

    def test_xss_prevention(self, renderer):
        block = TitleBlock(type="title", title="<script>alert(1)</script>")
        html = renderer._render_title(block)
        assert "<script>" not in html
        assert "&lt;script&gt;" in html

    def test_empty_blocks(self, renderer):
        resp = InfographicResponse(blocks=[])
        html = renderer.render_to_html(resp)
        assert "No data" in html or "no data" in html.lower()

    def test_css_variables(self, renderer, basic_response):
        html = renderer.render_to_html(basic_response, theme="light")
        assert "--primary:" in html
        assert ":root" in html

    def test_table_block(self, renderer):
        block = TableBlock(type="table", columns=["A", "B"],
                          rows=[["1", "2"], ["3", "4"]])
        html = renderer._render_table(block)
        assert "<table" in html
        assert "<th" in html

    def test_bullet_list_ordered(self, renderer):
        block = BulletListBlock(type="bullet_list", items=["a", "b"], ordered=True)
        html = renderer._render_bullet_list(block)
        assert "<ol" in html

    def test_callout_block(self, renderer):
        block = CalloutBlock(type="callout", level=CalloutLevel.WARNING,
                            title="Warn", content="Be careful")
        html = renderer._render_callout(block)
        assert "Warn" in html
        assert "warning" in html.lower() or "Be careful" in html
```

---

## Agent Instructions

When you pick up this task:

1. **Read the spec** at `sdd/specs/infographic-html-output.spec.md` for full context
2. **Check dependencies** — verify TASK-644 is in `tasks/completed/`
3. **Verify the Codebase Contract** — confirm all imports still work
4. **Read the reference HTML** at `docs/infographic-1775694709159.html` to understand
   the visual structure and CSS patterns
5. **Update status** in `tasks/.index.json` → `"in-progress"`
6. **Implement** following the scope and notes above
7. **Verify** all acceptance criteria are met
8. **Move this file** to `tasks/completed/TASK-645-html-block-renderers.md`
9. **Update index** → `"done"`

---

## Completion Note

*(Agent fills this in when done)*
