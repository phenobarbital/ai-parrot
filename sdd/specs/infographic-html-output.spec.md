# Feature Specification: Infographic HTML Output via Content Negotiation

**Feature ID**: FEAT-094
**Date**: 2026-04-10
**Author**: Jesus Lara
**Status**: draft
**Target version**: 1.x

---

## 1. Motivation & Business Requirements

### Problem Statement

The `get_infographic()` method (added in branch `claude/structured-infographic-output-1jZ2v`)
returns structured JSON (`InfographicResponse`) via `OutputMode.INFOGRAPHIC`. This is a
**breaking change** for the frontend (`BlockCanvas` in navigator-frontend-next), which
currently expects a fully rendered HTML document with inline CSS and interactive charts.

The backend must support both output formats via HTTP content negotiation (`Accept` header),
defaulting to HTML for backward compatibility.

### Goals
- Serve self-contained HTML infographics (inline CSS + inline ECharts JS) when
  `Accept: text/html` or no Accept header is provided (backward compatible default).
- Serve structured JSON (`InfographicResponse`) when `Accept: application/json`.
- Implement a reusable `InfographicHTMLRenderer` that converts any `InfographicResponse`
  to a complete HTML document, suitable for future PDF/email/embed export.
- Support theme customization (built-in: `light`, `dark`, `corporate`) with user-registrable
  custom themes.
- Render all 12 block types as HTML, including interactive ECharts for `ChartBlock`.

### Non-Goals (explicitly out of scope)
- PDF export (future feature, but renderer must be reusable for it).
- Static SVG chart rendering (defer to a later `chart_mode` parameter).
- Adaptive Cards or other non-HTML output formats.
- Modifying the `InfographicResponse` model or block types.
- Frontend changes to `BlockCanvas` (that is a separate navigator-frontend-next task).

---

## 2. Architectural Design

### Overview

A new `InfographicHTMLRenderer` class renders `InfographicResponse` blocks into a
self-contained HTML5 document. Content negotiation happens at two levels:

1. **`get_infographic()` method**: accepts an `accept` parameter (or reads from
   `RequestContext`) to decide which renderer to invoke.
2. **HTTP handler**: inspects the `Accept` header and passes the format preference
   downstream.

The renderer is a standalone utility: given an `InfographicResponse` dict, it returns
an HTML string. It does not depend on the HTTP layer.

### Component Diagram
```
Client (Accept header)
    |
    v
Handler (_get_output_format)
    |
    v
get_infographic() ──→ self.ask() ──→ AIMessage (structured_output=InfographicResponse)
    |
    ├── Accept: application/json ──→ InfographicRenderer (existing, returns JSON)
    |
    └── Accept: text/html (default) ──→ InfographicHTMLRenderer (NEW)
                                            |
                                            ├── ThemeRegistry ──→ CSS variables
                                            ├── BlockRenderers ──→ HTML fragments
                                            └── EChartsMapper ──→ <script> tags
```

### Integration Points

| Existing Component | Integration Type | Notes |
|---|---|---|
| `InfographicRenderer` | preserved | Continues to serve JSON; HTML renderer is a sibling |
| `BaseRenderer` | extends | `InfographicHTMLRenderer` inherits from `BaseRenderer` |
| `InfographicResponse` model | depends on | Consumed as input; not modified |
| `BlockType`, `ChartType` enums | depends on | Used for dispatch in block rendering |
| `get_infographic()` | modifies | Add `accept` parameter for content negotiation |
| `_get_output_format()` handler | uses | Existing Accept header parsing; no changes needed |
| `register_renderer` / `get_renderer` | uses | Register the new HTML renderer |
| `infographic_registry` | extends | Add theme registration alongside template registration |

### Data Models

```python
# New: Theme configuration (lives in parrot/models/infographic.py)
class ThemeConfig(BaseModel):
    """CSS variable configuration for infographic HTML themes."""
    name: str
    primary: str = "#6366f1"
    primary_dark: str = "#4f46e5"
    primary_light: str = "#818cf8"
    accent_green: str = "#10b981"
    accent_amber: str = "#f59e0b"
    accent_red: str = "#ef4444"
    neutral_bg: str = "#f8fafc"
    neutral_border: str = "#e2e8f0"
    neutral_muted: str = "#64748b"
    neutral_text: str = "#0f172a"
    body_bg: str = "#f1f5f9"
    font_family: str = (
        '-apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, '
        'Helvetica, Arial, sans-serif'
    )
```

No new block models are needed — the existing 12 block types in `parrot/models/infographic.py`
are consumed as-is.

### New Public Interfaces

```python
# parrot/outputs/formats/infographic_html.py
class InfographicHTMLRenderer(BaseRenderer):
    """Renders InfographicResponse as self-contained HTML with inline CSS and ECharts."""

    async def render(
        self,
        response: Any,
        environment: str = 'default',
        **kwargs,
    ) -> Tuple[str, Optional[Any]]:
        """Render infographic as complete HTML document."""
        ...

    def render_to_html(
        self,
        data: Union[InfographicResponse, dict],
        theme: Optional[str] = None,
    ) -> str:
        """Standalone method: convert InfographicResponse to HTML string.

        Reusable outside the renderer pipeline (e.g., for PDF export, email).
        """
        ...

# parrot/models/infographic.py (addition)
class ThemeRegistry:
    """Registry for infographic HTML themes."""

    def register(self, theme: ThemeConfig) -> None: ...
    def get(self, name: str) -> ThemeConfig: ...
    def list_themes(self) -> List[str]: ...

# Module-level singleton
theme_registry = ThemeRegistry()
```

---

## 3. Module Breakdown

### Module 1: Theme System
- **Path**: `parrot/models/infographic.py` (extend existing file)
- **Responsibility**: `ThemeConfig` model and `ThemeRegistry` with built-in themes
  (`light`, `dark`, `corporate`). Generates CSS `:root` variable blocks.
- **Depends on**: Nothing new (extends existing file)

### Module 2: HTML Block Renderers
- **Path**: `parrot/outputs/formats/infographic_html.py`
- **Responsibility**: `InfographicHTMLRenderer` class with per-block-type render methods
  (`_render_title`, `_render_hero_card`, `_render_summary`, `_render_chart`,
  `_render_bullet_list`, `_render_table`, `_render_image`, `_render_quote`,
  `_render_callout`, `_render_divider`, `_render_timeline`, `_render_progress`).
  Assembles full HTML5 document with inline CSS + ECharts JS.
- **Depends on**: Module 1 (ThemeConfig, ThemeRegistry), `InfographicResponse`,
  `BlockType`, `ChartType`, `markupsafe`, `markdown-it-py`, `BaseRenderer`

### Module 3: ECharts Mapping
- **Path**: `parrot/outputs/formats/infographic_html.py` (same file, internal methods)
- **Responsibility**: Map `ChartBlock` data (chart_type, labels, series) to ECharts
  option JSON. Generate `<div>` + `<script>` that initializes ECharts instances.
  Include inline minified ECharts JS in the document `<head>`.
- **Depends on**: `ChartType`, `ChartBlock`, `ChartDataSeries` models

### Module 4: Content Negotiation Wiring
- **Path**: `parrot/bots/abstract.py` (modify `get_infographic`),
  `parrot/outputs/formats/__init__.py` (register new renderer)
- **Responsibility**: Add `accept` parameter to `get_infographic()`. When `text/html`
  (or default), render via `InfographicHTMLRenderer`. When `application/json`, use
  existing `InfographicRenderer`. Register new renderer in lazy-load map.
- **Depends on**: Module 2, existing `InfographicRenderer`, `_get_output_format`

### Module 5: Tests
- **Path**: `tests/test_infographic_html.py`
- **Responsibility**: Unit tests for each block renderer, theme system, ECharts mapping,
  content negotiation, and full round-trip rendering.
- **Depends on**: Modules 1-4

---

## 4. Test Specification

### Unit Tests

| Test | Module | Description |
|---|---|---|
| `test_theme_config_defaults` | 1 | ThemeConfig produces correct CSS variables with defaults |
| `test_theme_registry_builtin` | 1 | Built-in themes (light, dark, corporate) are registered |
| `test_theme_registry_custom` | 1 | Custom theme registration and retrieval works |
| `test_theme_registry_unknown` | 1 | KeyError raised for unknown theme name |
| `test_render_title_block` | 2 | TitleBlock renders hero header with title, subtitle |
| `test_render_hero_card_block` | 2 | HeroCardBlock renders KPI card with value, label, trend |
| `test_render_summary_block` | 2 | SummaryBlock renders markdown content as HTML |
| `test_render_chart_block_bar` | 2 | ChartBlock(BAR) generates ECharts div + script |
| `test_render_chart_block_pie` | 2 | ChartBlock(PIE) generates correct ECharts pie config |
| `test_render_chart_block_line` | 2 | ChartBlock(LINE) generates correct ECharts line config |
| `test_render_bullet_list_block` | 2 | BulletListBlock renders ul/ol with items |
| `test_render_table_block` | 2 | TableBlock renders HTML table with headers and rows |
| `test_render_image_block` | 2 | ImageBlock renders img tag with alt and caption |
| `test_render_quote_block` | 2 | QuoteBlock renders blockquote with attribution |
| `test_render_callout_block` | 2 | CalloutBlock renders alert box with correct level styling |
| `test_render_divider_block` | 2 | DividerBlock renders hr with correct style |
| `test_render_timeline_block` | 2 | TimelineBlock renders chronological event list |
| `test_render_progress_block` | 2 | ProgressBlock renders progress bars with percentages |
| `test_render_unknown_block_type` | 2 | Unknown block type is skipped with warning |
| `test_render_empty_blocks` | 2 | Empty blocks list renders minimal page with message |
| `test_echarts_bar_mapping` | 3 | ChartType.BAR maps to correct ECharts option |
| `test_echarts_series_colors` | 3 | Series colors propagated to ECharts config |
| `test_echarts_inline_js` | 3 | HTML document includes inline ECharts JS |
| `test_full_document_structure` | 2 | Full render produces valid HTML5 with doctype, head, body |
| `test_css_variables_in_document` | 2 | Rendered HTML contains correct CSS custom properties |
| `test_xss_prevention` | 2 | HTML-escaped user content (no script injection) |
| `test_markdown_rendering` | 2 | Markdown in SummaryBlock converted to safe HTML |
| `test_content_negotiation_html` | 4 | Accept: text/html returns HTML document |
| `test_content_negotiation_json` | 4 | Accept: application/json returns JSON |
| `test_content_negotiation_default` | 4 | No Accept header returns HTML (backward compat) |
| `test_render_to_html_standalone` | 2 | render_to_html() works outside renderer pipeline |

### Integration Tests

| Test | Description |
|---|---|
| `test_get_infographic_html_roundtrip` | Full pipeline: get_infographic → LLM → HTML output |
| `test_reference_html_visual_match` | Rendered HTML structure matches reference doc patterns |

### Test Data / Fixtures

```python
@pytest.fixture
def sample_infographic_response():
    """Complete InfographicResponse with all 12 block types."""
    return InfographicResponse(
        template="basic",
        theme="light",
        blocks=[
            TitleBlock(type="title", title="Test Report", subtitle="Q4 2025"),
            HeroCardBlock(type="hero_card", label="Revenue", value="$1.2M",
                         trend=TrendDirection.UP, trend_value="+15%"),
            SummaryBlock(type="summary", content="**Key findings** from the analysis."),
            ChartBlock(type="chart", chart_type=ChartType.BAR, title="Sales",
                      labels=["Q1", "Q2", "Q3", "Q4"],
                      series=[ChartDataSeries(name="2025", values=[100, 200, 150, 300])]),
            BulletListBlock(type="bullet_list", title="Recommendations",
                           items=["Item 1", "Item 2"]),
            TableBlock(type="table", columns=["Name", "Value"],
                      rows=[["A", "100"], ["B", "200"]]),
            CalloutBlock(type="callout", level=CalloutLevel.INFO,
                        title="Note", content="Important info"),
            DividerBlock(type="divider", style="solid"),
        ],
    )

@pytest.fixture
def sample_theme():
    return ThemeConfig(name="test", primary="#ff0000", primary_dark="#cc0000")
```

---

## 5. Acceptance Criteria

- [x] All unit tests pass (`pytest tests/test_infographic_html.py -v`)
- [ ] HTML output is a valid, self-contained HTML5 document (inline CSS, inline ECharts JS)
- [ ] All 12 block types render correctly to HTML
- [ ] `Accept: text/html` returns HTML; `Accept: application/json` returns JSON
- [ ] No Accept header defaults to HTML (backward compatible)
- [ ] ECharts JS is bundled inline (not CDN) for offline/embed use
- [ ] Themes (light, dark, corporate) produce correct CSS custom properties
- [ ] Custom theme registration works via `ThemeRegistry`
- [ ] User-provided text content is HTML-escaped (XSS prevention)
- [ ] Markdown in SummaryBlock rendered via `markdown-it-py` (safe mode)
- [ ] `render_to_html()` is callable as a standalone utility (no HTTP context needed)
- [ ] No breaking changes to existing `InfographicRenderer` JSON output
- [ ] HTML visual structure matches reference `docs/infographic-1775694709159.html` patterns

---

## 6. Codebase Contract

### Verified Imports
```python
# These imports have been confirmed to work:
from parrot.models.infographic import (
    InfographicResponse, InfographicBlock, BlockType, ChartType,
    TitleBlock, HeroCardBlock, SummaryBlock, ChartBlock, ChartDataSeries,
    BulletListBlock, TableBlock, ImageBlock, QuoteBlock, CalloutBlock,
    DividerBlock, TimelineBlock, TimelineEvent, ProgressBlock, ProgressItem,
    TrendDirection, CalloutLevel,
)  # verified: parrot/models/__init__.py exports all

from parrot.models.infographic_templates import (
    InfographicTemplate, InfographicTemplateRegistry, infographic_registry,
    BlockSpec,
)  # verified: parrot/models/__init__.py

from parrot.models.outputs import OutputMode  # verified: parrot/models/outputs.py:39
from parrot.outputs.formats import register_renderer, get_renderer  # verified: parrot/outputs/formats/__init__.py:17,33
from parrot.outputs.formats.base import BaseRenderer  # verified: parrot/outputs/formats/base.py:54

# Markdown library (already installed):
import markdown_it  # verified: markdown-it-py 4.0.0 installed in venv
from markupsafe import escape  # verified: markupsafe is a dependency (via Jinja2)
```

### Existing Class Signatures

```python
# parrot/outputs/formats/base.py:54
class BaseRenderer(ABC):
    @classmethod
    def get_expected_content_type(cls) -> Type:  # line 57
        ...
    @abstractmethod
    async def render(self, response: Any, environment: str = 'default', **kwargs) -> Tuple[str, Optional[Any]]:
        ...

# parrot/outputs/formats/infographic.py:44-73
@register_renderer(OutputMode.INFOGRAPHIC, system_prompt=INFOGRAPHIC_SYSTEM_PROMPT)
class InfographicRenderer(BaseRenderer):
    async def render(self, response: Any, environment: str = 'default', **kwargs) -> Tuple[str, Optional[Any]]:  # line 52
    def _extract_infographic_data(self, response: Any) -> dict:  # line 75
    def _wrap_output(self, json_string: str, data: dict, environment: str) -> Any:  # line 136
    def _wrap_html(self, json_string: str) -> str:  # line 165

# parrot/models/infographic.py:311-332
class InfographicResponse(BaseModel):
    template: Optional[str]            # line 313
    theme: Optional[str]               # line 318
    blocks: List[InfographicBlock]     # line 319 — Union of 12 block types
    metadata: Optional[Dict[str, Any]] # line 325

# parrot/models/infographic.py:38-51
class BlockType(str, Enum):
    TITLE = "title"           # line 39
    HERO_CARD = "hero_card"   # line 40
    SUMMARY = "summary"       # line 41
    CHART = "chart"           # line 42
    BULLET_LIST = "bullet_list"  # line 43
    TABLE = "table"           # line 44
    IMAGE = "image"           # line 45
    QUOTE = "quote"           # line 46
    CALLOUT = "callout"       # line 47
    DIVIDER = "divider"       # line 48
    TIMELINE = "timeline"     # line 49
    PROGRESS = "progress"     # line 50

# parrot/models/infographic.py:54-67
class ChartType(str, Enum):
    BAR = "bar"       LINE = "line"     PIE = "pie"
    DONUT = "donut"   AREA = "area"     SCATTER = "scatter"
    RADAR = "radar"   HEATMAP = "heatmap"  TREEMAP = "treemap"
    FUNNEL = "funnel" GAUGE = "gauge"   WATERFALL = "waterfall"

# parrot/models/infographic.py — Block models (key fields only):
# TitleBlock(90): title, subtitle, author, date, logo_url
# HeroCardBlock(100): label, value, icon, trend, trend_value, comparison_period, color
# SummaryBlock(124): title, content (markdown), highlight
# ChartBlock(148): chart_type, title, description, labels, series, x_axis_label, y_axis_label, stacked, show_legend
# ChartDataSeries(138): name, values, color
# BulletListBlock(168): title, items, ordered, icon
# TableBlock(183): title, columns, rows, highlight_first_column, sortable
# ImageBlock(202): url, base64, alt, caption, width
# QuoteBlock(212): text, author, source
# CalloutBlock(220): level, title, content
# DividerBlock(231): style (solid/dashed/dotted/gradient)
# TimelineEvent(240): date, title, description, icon, color
# TimelineBlock(249): title, events
# ProgressItem(259): label, value (0-100), color, target
# ProgressBlock(277): title, items

# parrot/bots/abstract.py:2574-2653
async def get_infographic(
    self,
    question: str,
    template: Optional[str] = "basic",
    session_id: Optional[str] = None,
    user_id: Optional[str] = None,
    use_vector_context: bool = True,
    use_conversation_history: bool = False,
    theme: Optional[str] = None,
    ctx: Optional[RequestContext] = None,
    **kwargs,
) -> AIMessage:  # calls self.ask() with structured_output=InfographicResponse

# parrot/handlers/agent.py:399-426
def _get_output_format(self, data, qs) -> str:
    # Returns 'json', 'html', 'markdown', or 'text'
    # Priority: output_format param → Accept header → 'json'

# parrot/outputs/formats/__init__.py:17-31
def register_renderer(mode: OutputMode, system_prompt: Optional[str] = None):
    # Decorator to register a renderer class

# parrot/outputs/formats/__init__.py:33-89
def get_renderer(mode: OutputMode) -> Type[Renderer]:
    # Lazy-loads and returns renderer class. Line 82-83 handles INFOGRAPHIC.
```

### Integration Points

| New Component | Connects To | Via | Verified At |
|---|---|---|---|
| `InfographicHTMLRenderer` | `BaseRenderer` | inheritance | `parrot/outputs/formats/base.py:54` |
| `InfographicHTMLRenderer` | `InfographicRenderer._extract_infographic_data` | reuse (import or inherit) | `parrot/outputs/formats/infographic.py:75` |
| `ThemeConfig` / `ThemeRegistry` | `infographic.py` models | same file extension | `parrot/models/infographic.py` |
| Content negotiation | `get_infographic()` | new `accept` parameter | `parrot/bots/abstract.py:2574` |
| Lazy loader | `get_renderer()` | new elif branch | `parrot/outputs/formats/__init__.py:82` |

### Does NOT Exist (Anti-Hallucination)
- ~~`parrot.outputs.formats.infographic_html`~~ — does not exist yet (Module 2 creates it)
- ~~`InfographicRenderer.render_html()`~~ — no HTML rendering method exists on the JSON renderer
- ~~`parrot.themes`~~ — no theme module; themes will live in `parrot/models/infographic.py`
- ~~`InfographicResponse.to_html()`~~ — no such method on the model
- ~~`OutputMode.INFOGRAPHIC_HTML`~~ — does not exist; we reuse INFOGRAPHIC with content negotiation
- ~~`InfographicRenderer._render_block()`~~ — no per-block rendering in current renderer
- ~~`parrot.outputs.formats.echarts.EChartsRenderer._build_option()`~~ — the ECharts renderer
  exists but has no method by this name that we can reuse for option building

---

## 7. Implementation Notes & Constraints

### Patterns to Follow
- Inherit from `BaseRenderer` (parrot/outputs/formats/base.py:54)
- Use `@register_renderer` decorator for renderer registration
- Use `markupsafe.escape()` for all user text → HTML conversion
- Use `markdown_it.MarkdownIt()` for markdown → HTML (SummaryBlock.content)
- Pydantic `BaseModel` for `ThemeConfig`
- Block rendering via dispatch dict: `{BlockType.TITLE: self._render_title, ...}`

### CSS Architecture
Extract CSS from the reference HTML (`docs/infographic-1775694709159.html`):
- CSS custom properties on `:root` for theme values
- `.container`, `.hero`, `.kpi-grid`, `.kpi-card`, `.chart-container`, `.section-title`,
  `.insight-box`, `.insight-list` class styles
- Responsive breakpoints: `@media (max-width: 600px)`
- Print styles: `@media print`
- The CSS is a constant string template with `{variables}` for theme tokens

### ECharts Integration
- Include ECharts JS inline in `<head>` (minified, ~800KB) — NOT via CDN
- Each `ChartBlock` gets a unique `<div id="chart-{uuid}">` container
- A `<script>` tag after the div initializes: `echarts.init(dom).setOption({...})`
- Map `ChartType` enum to ECharts `type` values:
  - BAR → `{type: 'bar'}`, LINE → `{type: 'line'}`, PIE → `{type: 'pie'}`
  - DONUT → pie with inner radius, AREA → line with `areaStyle`
  - SCATTER → `{type: 'scatter'}`, RADAR → radar chart config
  - GAUGE → gauge, FUNNEL → funnel, TREEMAP → treemap
  - HEATMAP → heatmap, WATERFALL → custom bar implementation
- `ChartDataSeries` → ECharts `series[]` items with `data` and `name`
- `ChartBlock.labels` → ECharts `xAxis.data` (for cartesian charts) or `legend.data` (pie)

### Known Risks / Gotchas
- **ECharts bundle size**: ~800KB inline per document. Acceptable since infographics
  are infrequent, high-value outputs (not high-frequency API calls).
- **ECharts version pinning**: Must ship a specific version. Pin in the renderer and
  document which version is bundled.
- **Markdown XSS**: `markdown-it-py` must be configured with `html=False` (default)
  to prevent raw HTML injection in SummaryBlock content.
- **Block type evolution**: If new block types are added to `BlockType` enum, the
  HTML renderer must be updated. The unknown-block fallback (skip + warn) prevents
  crashes but produces incomplete output.

### External Dependencies

| Package | Version | Reason |
|---|---|---|
| `markdown-it-py` | `>=3.0` | Markdown → HTML for SummaryBlock content (already installed: 4.0.0) |
| `markupsafe` | `>=2.0` | HTML escaping for XSS prevention (already installed) |
| `orjson` | `>=3.0` | JSON serialization for ECharts options (already installed) |

No new dependencies required.

---

## Worktree Strategy

- **Default isolation**: `per-spec` — all tasks run sequentially in one worktree.
- **Rationale**: Modules have linear dependencies (themes → block renderers → ECharts →
  content negotiation → tests). Parallel execution would require frequent merging.
- **Cross-feature dependencies**: None. The `InfographicResponse` model and existing
  `InfographicRenderer` are stable and not modified by other in-flight specs.

---

## 8. Open Questions

- [x] Which ECharts version to bundle inline? Need to pick a specific minified build.
  Suggestion: `echarts@5.5.x` (latest stable). — *Owner: Jesus Lara*: yes, latest stable.
- [x] Should `render_to_html()` accept a raw dict (loose) or require a validated
  `InfographicResponse` model? Suggestion: accept both (try model_validate on dict).
  — *Owner: Jesus Lara*: accept both.

---

## Revision History

| Version | Date | Author | Change |
|---|---|---|---|
| 0.1 | 2026-04-10 | Jesus Lara | Initial draft from brainstorm |
