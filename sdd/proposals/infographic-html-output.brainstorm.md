# Brainstorm: Infographic HTML Output via Content Negotiation

**Date**: 2026-04-10
**Author**: Jesus Lara
**Status**: exploration
**Recommended Option**: Option A

---

## Problem Statement

The recently merged `get_infographic()` method (branch `claude/structured-infographic-output-1jZ2v`)
returns structured JSON (`InfographicResponse`) instead of the HTML infographics that the
frontend (`BlockCanvas` in navigator-frontend-next) currently expects. This is a **breaking change**
for existing consumers that rely on receiving a fully rendered HTML document.

We need:
1. **Content negotiation** via `Accept` header so the same endpoint serves both formats.
2. A **backend HTML renderer** that converts `InfographicResponse` JSON blocks into a
   self-contained HTML document (CSS inline, ECharts JS inline for interactive charts).
3. **Backward compatibility**: when no `Accept` header is specified (or `text/html`), the
   response must be HTML (matching the current frontend behavior).

**Who is affected**: All frontend consumers of the infographic endpoint, specifically
`BlockCanvas` in navigator-frontend-next.

## Constraints & Requirements

- HTML output must be a **complete, self-contained document** (inline CSS + inline JS).
- Default output (no Accept header) must be **HTML** for backward compatibility.
- Charts must use **ECharts** by default (interactive), with option for static SVG via parameter.
- The renderer must handle **all 12 block types**: title, hero_card, summary, chart,
  bullet_list, table, image, quote, callout, divider, timeline, progress.
- Visual fidelity must match the existing HTML infographics (see `docs/infographic-1775694709159.html`).
- Renderer must be a **reusable utility** (future: PDF export, Adaptive Cards, webApps).
- Infographics are not large; rendering entirely in memory is acceptable.
- Async-first: no blocking I/O.

---

## Options Explored

### Option A: Block-Based HTML Renderer in outputs/formats

Extend the existing `InfographicRenderer` to support content negotiation. Add a new
`InfographicHTMLRenderer` class (or extend the current one) in `parrot/outputs/formats/`
that maps each `BlockType` to an HTML rendering function. The renderer produces a complete
HTML document with inline CSS (design tokens from the existing infographic HTML) and
inline ECharts JS for chart blocks.

Content negotiation happens at the `get_infographic()` / handler level: check the `Accept`
header, and route to JSON rendering or HTML rendering accordingly.

The renderer is a standalone utility class (`InfographicHTMLRenderer`) that takes an
`InfographicResponse` (or its dict equivalent) and returns a complete HTML string. This
makes it reusable for PDF export (via headless browser/weasyprint) or other formats later.

Each block type gets its own render method (`_render_title`, `_render_hero_card`,
`_render_chart`, etc.) following the visitor pattern. Themes are implemented as CSS
variable sets (matching the existing `:root` CSS custom properties pattern from the
example HTML).

ECharts integration: for `ChartBlock`, generate a `<div>` with a unique ID and an inline
`<script>` that initializes an ECharts instance with the chart data from the block's
`series`, `labels`, `chart_type` fields. Map `ChartType` enum values to ECharts option
configurations.

**Pros:**
- Follows existing renderer architecture (`BaseRenderer`, `@register_renderer`)
- Each block type is independently testable
- Theme system via CSS variables is clean and extensible
- ECharts inline means zero external dependencies for the HTML consumer
- Reusable: same class can be called from PDF export, email, etc.
- Content negotiation uses the existing `_get_output_format()` handler infrastructure

**Cons:**
- Significant implementation effort: 12 block types + ECharts mappings + theme system
- CSS must be carefully crafted to match existing visual style
- ECharts CDN or bundled JS adds to document size (~800KB minified)

**Effort:** Medium-High

**Libraries / Tools:**
| Package | Purpose | Notes |
|---|---|---|
| `echarts` (JS) | Interactive charts in HTML output | CDN link or inline minified; already used in frontend |
| `markupsafe` | Safe HTML string escaping | Already a dependency (via Jinja2) |
| `orjson` | JSON serialization for ECharts options | Already used in InfographicRenderer |

**Existing Code to Reuse:**
- `parrot/outputs/formats/infographic.py` — `InfographicRenderer._extract_infographic_data()` for data extraction
- `parrot/outputs/formats/base.py` — `BaseRenderer` base class
- `parrot/models/infographic.py` — All block models, `InfographicResponse`, `BlockType`, `ChartType`
- `parrot/models/infographic_templates.py` — Template definitions and theme hints
- `parrot/handlers/agent.py:399-461` — Existing content negotiation (`_get_output_format`, `_get_output_mode`)
- `docs/infographic-1775694709159.html` — Reference CSS and layout structure

---

### Option B: Jinja2 Template-Based Renderer

Use Jinja2 templates to render the HTML. Create a set of Jinja2 templates (one per block
type or a single template with macros) in a `templates/infographic/` directory. The renderer
loads the template, passes the `InfographicResponse` data, and Jinja2 produces the HTML.

Themes are Jinja2 context variables. ECharts config is generated via a Jinja2 macro that
emits `<script>` tags.

**Pros:**
- Jinja2 is battle-tested for HTML generation
- Templates are easier for designers to modify (HTML, not Python)
- Clear separation of presentation (templates) from logic (renderer)
- Jinja2 autoescaping prevents XSS

**Cons:**
- Adds a template directory and template management complexity
- Jinja2 templates for complex ECharts configs become unwieldy (mixing JS in Jinja2)
- Harder to unit test individual block rendering
- Template loading requires filesystem access or package resource management
- Jinja2's async support is limited and may need workarounds

**Effort:** Medium

**Libraries / Tools:**
| Package | Purpose | Notes |
|---|---|---|
| `jinja2` | HTML template rendering | Already a dependency |
| `echarts` (JS) | Interactive charts | CDN link in templates |
| `markupsafe` | HTML escaping | Already a dependency |

**Existing Code to Reuse:**
- `parrot/outputs/formats/infographic.py` — Data extraction logic
- `parrot/outputs/formats/base.py` — BaseRenderer
- `parrot/models/infographic.py` — Block models

---

### Option C: Hybrid Approach — Python Renderer with ECharts as Separate Module

Split the rendering into two concerns:
1. **Static HTML renderer** (Python string builder) handles all non-chart blocks.
2. **Chart renderer module** that can produce either ECharts JS (interactive) or
   matplotlib/SVG (static) based on a parameter.

The chart renderer is a pluggable component: `ChartAdapter` base class with
`EChartsAdapter` and `SVGAdapter` implementations. The HTML renderer calls the
appropriate adapter based on configuration.

This adds a layer of abstraction but cleanly separates chart rendering (which has
its own complexity) from document structure rendering.

**Pros:**
- Clean separation of concerns (layout vs. charts)
- Chart adapters can be independently tested and extended
- SVG adapter enables server-side chart rendering without JS
- Future-proof for adding new chart backends

**Cons:**
- Over-engineered for current requirements (only ECharts needed now)
- More classes, more abstraction, more indirection
- SVG adapter requires additional dependencies (matplotlib or similar)
- Increases implementation scope significantly

**Effort:** High

**Libraries / Tools:**
| Package | Purpose | Notes |
|---|---|---|
| `echarts` (JS) | Interactive charts | CDN in HTML |
| `matplotlib` | Static SVG charts | Only if SVG adapter built |
| `cairosvg` | SVG rendering | Optional, for PDF path |

**Existing Code to Reuse:**
- Same as Option A, plus:
- `parrot/outputs/formats/echarts.py` — `EChartsRenderer` patterns for chart config generation

---

## Recommendation

**Option A** is recommended because:

- It follows the existing renderer pattern (`BaseRenderer` + `@register_renderer`) without
  introducing new template systems or abstraction layers.
- All 12 block types can be rendered as self-contained Python methods, each independently
  testable and easy to iterate on.
- The CSS variable / theme system directly mirrors the existing HTML infographic style
  (see `docs/infographic-1775694709159.html`).
- ECharts inline JS is straightforward: map `ChartType` to ECharts option objects and emit
  a `<script>` tag. No need for a separate chart adapter abstraction.
- Content negotiation plugs into the existing `_get_output_format()` infrastructure.
- The renderer class is reusable as-is for future PDF/email/Adaptive Cards outputs.

The tradeoff vs. Option B (Jinja2) is maintainability of HTML-in-Python, but since the
HTML structure is deterministic and block-based (not free-form pages), string building
is cleaner than managing template files. The tradeoff vs. Option C is simplicity over
extensibility — we only need ECharts now, and YAGNI applies.

---

## Feature Description

### User-Facing Behavior

When a client calls `get_infographic()` (or the corresponding HTTP endpoint):

- **`Accept: text/html`** (or no Accept header) → Returns a complete, self-contained HTML
  document with inline CSS and inline ECharts JS. The HTML is ready to render in a browser
  or embed in an iframe. This is the **default** for backward compatibility.

- **`Accept: application/json`** → Returns the structured `InfographicResponse` JSON with
  typed blocks. This is the new structured format for frontend clients that want to render
  blocks themselves.

The HTML output visually matches the existing infographic style: gradient hero header,
KPI cards in a grid, bar/line/pie charts via ECharts, styled tables, callout boxes,
timeline components, and responsive layout with print media query support.

### Internal Behavior

1. **`get_infographic()`** calls `self.ask()` which returns an `AIMessage` with
   `structured_output=InfographicResponse` (JSON blocks from the LLM).

2. The **handler** inspects the `Accept` header via `_get_output_format()`:
   - If `text/html` or default → pass to `InfographicHTMLRenderer.render(response)`
   - If `application/json` → pass to existing `InfographicRenderer.render(response)`

3. **`InfographicHTMLRenderer`**:
   - Extracts `InfographicResponse` from the AIMessage (reuses `_extract_infographic_data`)
   - Resolves theme (from response metadata or template default)
   - Generates CSS `:root` variables for the theme
   - Iterates over `blocks` list, calling `_render_<block_type>()` for each
   - For `ChartBlock`: generates ECharts `<div>` + `<script>` with mapped options
   - Wraps everything in a complete HTML5 document (`<!DOCTYPE html>...<body>...</body></html>`)
   - Returns the HTML string

4. **Theme resolution**: A `ThemeConfig` dataclass holds CSS variable values (primary color,
   accent colors, background, text color, font family). Built-in themes: `light`, `dark`,
   `corporate`. Custom themes can be registered.

### Edge Cases & Error Handling

- **Missing blocks**: If `InfographicResponse.blocks` is empty, render a minimal HTML page
  with a "No data available" message.
- **Unknown block type**: Skip with a logged warning (do not crash the whole render).
- **Chart with no data**: Render an empty chart container with a "No data" placeholder.
- **ECharts CDN unreachable**: Since ECharts JS is included via CDN `<script src>`, if the
  CDN is down the charts won't render. Mitigation: offer a config option to inline a
  bundled ECharts minified JS instead.
- **XSS prevention**: All user-provided text content must be HTML-escaped before insertion.
  Use `markupsafe.escape()` for all text fields. Markdown fields are rendered to HTML via
  a safe markdown parser (no raw HTML passthrough).
- **Accept header ambiguity**: If Accept contains both `text/html` and `application/json`,
  prefer HTML (backward compatibility). If Accept is `*/*`, return HTML.

---

## Capabilities

### New Capabilities
- `infographic-html-renderer`: Backend HTML renderer that converts InfographicResponse JSON
  blocks into self-contained HTML documents with inline CSS and ECharts.
- `infographic-content-negotiation`: Accept-header-based content negotiation in
  `get_infographic()` to serve HTML or JSON.
- `infographic-themes`: Theme system (CSS variables) for HTML infographic output with
  built-in themes (light, dark, corporate).

### Modified Capabilities
- `infographic-renderer` (existing): The current `InfographicRenderer` is preserved for
  JSON output; content negotiation routes to it when `Accept: application/json`.
- `get-infographic` (existing): Updated to support content negotiation via Accept header.

---

## Impact & Integration

| Affected Component | Impact Type | Notes |
|---|---|---|
| `parrot/outputs/formats/infographic.py` | extends | Add HTML rendering alongside existing JSON rendering |
| `parrot/bots/abstract.py:get_infographic()` | modifies | Pass Accept header / output format to renderer selection |
| `parrot/handlers/agent.py` | modifies | Route infographic responses based on Accept header |
| `parrot/models/infographic.py` | depends on | Uses all block models and InfographicResponse |
| `parrot/models/outputs.py` | depends on | Uses OutputMode.INFOGRAPHIC |
| `parrot/outputs/formats/__init__.py` | modifies | Register HTML renderer variant |

---

## Code Context

### Verified Codebase References

#### Classes & Signatures
```python
# From parrot/outputs/formats/infographic.py:44-73
@register_renderer(OutputMode.INFOGRAPHIC, system_prompt=INFOGRAPHIC_SYSTEM_PROMPT)
class InfographicRenderer(BaseRenderer):
    async def render(self, response: Any, environment: str = 'default', **kwargs) -> Tuple[str, Optional[Any]]:  # line 52
    def _extract_infographic_data(self, response: Any) -> dict:  # line 75
    def _wrap_output(self, json_string: str, data: dict, environment: str) -> Any:  # line 136
    def _wrap_html(self, json_string: str) -> str:  # line 165

# From parrot/outputs/formats/base.py:54
class BaseRenderer(ABC):
    @classmethod
    def get_expected_content_type(cls) -> Type:  # line 57
    @abstractmethod
    async def render(self, response: Any, environment: str = 'default', **kwargs) -> Tuple[str, Optional[Any]]: ...

# From parrot/models/infographic.py:311-332
class InfographicResponse(BaseModel):
    template: Optional[str]
    theme: Optional[str]
    blocks: List[InfographicBlock]
    metadata: Optional[Dict[str, Any]]

# From parrot/models/infographic.py:38-51
class BlockType(str, Enum):
    TITLE = "title"
    HERO_CARD = "hero_card"
    SUMMARY = "summary"
    CHART = "chart"
    BULLET_LIST = "bullet_list"
    TABLE = "table"
    IMAGE = "image"
    QUOTE = "quote"
    CALLOUT = "callout"
    DIVIDER = "divider"
    TIMELINE = "timeline"
    PROGRESS = "progress"

# From parrot/models/infographic.py:54-67
class ChartType(str, Enum):
    BAR = "bar"
    LINE = "line"
    PIE = "pie"
    DONUT = "donut"
    AREA = "area"
    SCATTER = "scatter"
    RADAR = "radar"
    HEATMAP = "heatmap"
    TREEMAP = "treemap"
    FUNNEL = "funnel"
    GAUGE = "gauge"
    WATERFALL = "waterfall"

# From parrot/bots/abstract.py:2574-2653
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
) -> AIMessage:

# From parrot/handlers/agent.py:399-426
def _get_output_format(self, data, qs) -> str:
    # Priority: output_format param → Accept header → 'json'

# From parrot/handlers/agent.py:428-461
def _get_output_mode(self, request: web.Request) -> OutputMode:
    # Priority: output_mode qs → Content-Type → Accept → DEFAULT

# From parrot/models/outputs.py:39-70
class OutputMode(str, Enum):
    INFOGRAPHIC = "infographic"  # line 70
    ECHARTS = "echarts"          # line 62
    HTML = "html"                # line 44
```

#### Verified Imports
```python
# These imports have been confirmed to work:
from parrot.models.infographic import (
    InfographicResponse, InfographicBlock, BlockType, ChartType,
    TitleBlock, HeroCardBlock, SummaryBlock, ChartBlock, ChartDataSeries,
    BulletListBlock, TableBlock, ImageBlock, QuoteBlock, CalloutBlock,
    DividerBlock, TimelineBlock, TimelineEvent, ProgressBlock, ProgressItem,
    TrendDirection, CalloutLevel,
)  # parrot/models/__init__.py
from parrot.models.infographic_templates import (
    InfographicTemplate, InfographicTemplateRegistry, infographic_registry,
    BlockSpec,
)  # parrot/models/__init__.py
from parrot.models.outputs import OutputMode  # parrot/models/outputs.py:39
from parrot.outputs.formats import register_renderer, get_renderer  # parrot/outputs/formats/__init__.py
from parrot.outputs.formats.base import BaseRenderer  # parrot/outputs/formats/base.py:54
```

#### Key Attributes & Constants
- `INFOGRAPHIC_SYSTEM_PROMPT` → `str` (parrot/outputs/formats/infographic.py:16-41)
- `infographic_registry` → `InfographicTemplateRegistry` singleton (parrot/models/infographic_templates.py:382)
- `InfographicResponse.blocks` → `List[InfographicBlock]` (parrot/models/infographic.py:319)
- `ChartBlock.series` → `List[ChartDataSeries]` (parrot/models/infographic.py:155)
- `ChartBlock.chart_type` → `ChartType` (parrot/models/infographic.py:150)

### Does NOT Exist (Anti-Hallucination)
- ~~`parrot.outputs.formats.infographic_html`~~ — does not exist yet (this is what we're building)
- ~~`InfographicRenderer.render_html()`~~ — no HTML rendering method exists; current `_wrap_html` only syntax-highlights JSON
- ~~`parrot.themes`~~ — no theme module exists
- ~~`InfographicResponse.to_html()`~~ — no such method on the model
- ~~`OutputMode.INFOGRAPHIC_HTML`~~ — no separate mode for HTML infographics exists

---

## Parallelism Assessment

- **Internal parallelism**: Yes — the HTML renderer (block renderers + CSS/theme) and the
  content negotiation (handler + get_infographic changes) are largely independent. The
  ECharts chart mapping is also a separate concern from the static block renderers.
- **Cross-feature independence**: No conflicts with in-flight specs. The infographic models
  are stable and only consumed (not modified) by this feature.
- **Recommended isolation**: `per-spec` — tasks are sequential (renderer depends on theme,
  content negotiation depends on renderer), but could be split into 2 parallel tracks:
  (1) HTML renderer + themes, (2) content negotiation wiring.
- **Rationale**: The renderer is the bulk of the work; content negotiation is a thin wiring
  layer. Sequential execution in one worktree keeps things simple.

---

## Open Questions

- [x] ECharts JS delivery: CDN link vs. inline bundled minified JS? CDN is simpler but requires
  internet. Inline adds ~800KB to every response. — *Owner: Jesus Lara*: inline is better to share as an embed document.
- [x] Should the HTML renderer support a `chart_mode` parameter (`interactive` vs `static_svg`)
  from day one, or defer SVG to a later feature? — *Owner: Jesus Lara*
- [x] Theme customization API: should users be able to register custom themes via
  `infographic_registry`, or is a separate theme registry needed? — *Owner: Jesus Lara*: users can register custom themes.
- [x] Markdown rendering in `SummaryBlock.content`: which markdown library? (`markdown`,
  `mistune`, `markdown-it-py`)? Need one that supports safe HTML output. — *Owner: Jesus Lara*: I'm open to suggestions.
