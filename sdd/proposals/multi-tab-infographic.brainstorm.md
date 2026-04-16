# Brainstorm: Multi-Tab Infographic Template + New Component Blocks

**Date**: 2026-04-15
**Author**: Jesus
**Status**: exploration
**Recommended Option**: Option A

---

## Problem Statement

The current infographic system (`InfographicResponse`) uses a flat list of `InfographicBlock` items, which works for single-view reports (executive, dashboard, comparison) but cannot represent multi-section, tabbed infographics. Complex reports — such as methodology documentation with 5+ logical sections — need navigable tabs, collapsible accordion sections, visual checklists, and richer table styling.

**Who is affected:**
- End users who receive AI-generated infographics for complex, multi-chapter content.
- Developers extending the infographic system with new templates.

**Why now:**
- Real-world usage demands richer layouts (e.g., "Metodología de implementación de agentes de IA" reference with 5 tabs, accordions, checklists).
- The existing 12 block types and flat structure cannot express these patterns.

## Constraints & Requirements

- Zero breaking changes to existing `InfographicResponse` — flat infographics must continue working unchanged.
- All new blocks must use CSS variables from `ThemeConfig` (no hardcoded colors).
- Inline vanilla JavaScript only — no external CDN dependencies. JS must come from a curated collection of inline scripts.
- HTML sanitization for `html_content` in AccordionBlock must use `nh3` (not deprecated `bleach`).
- Max nesting depth = 3 (TabView → Accordion → flat blocks). No TabView inside TabView, no Accordion inside Accordion.
- Print-friendly: tabs expand to show all panes, accordions expand all items.
- Responsive: tab nav wraps, tables scroll/stack, bullet columns collapse to single column on mobile.
- Auto-detection of multi-tab template when no template is explicitly specified (two-step LLM approach: first determine template, then generate).
- Extend existing `BulletListBlock` (add `color`, `columns`, `style`) rather than creating a new block type.
- Aggressively refactor `TableBlock` to incorporate styling options (ColumnDef, TableStyle) rather than creating a separate StyledTableBlock.

### Visual Reference

```
┌─────────────────────────────────────────────────┐
│  Título principal + subtítulo                   │
│  ┌──────┐ ┌──────┐ ┌──────┐ ┌──────┐ ┌──────┐  │
│  │ Tab1 │ │ Tab2 │ │ Tab3 │ │ Tab4 │ │ Tab5 │  │
│  └──────┘ └──────┘ └──────┘ └──────┘ └──────┘  │
│  ─────────────────────────────────────────────  │
│  ┌─────────────────────────────────────────┐    │
│  │  Vista activa (bloques del tab)         │    │
│  │  ┌─ accordion ──────────────────────┐   │    │
│  │  │ ▸ Sección colapsable             │   │    │
│  │  │   → contenido HTML interno       │   │    │
│  │  └──────────────────────────────────┘   │    │
│  │  ┌─ styled_table ──────────────────┐   │    │
│  │  │  Header │ Col A │ Col B │ Col C │   │    │
│  │  │  Row 1  │  ...  │  ...  │  ...  │   │    │
│  │  └──────────────────────────────────┘   │    │
│  │  ┌─ checklist ─────────────────────┐   │    │
│  │  │  ☐ Criterio de aceptación 1     │   │    │
│  │  │  ☐ Criterio de aceptación 2     │   │    │
│  │  └──────────────────────────────────┘   │    │
│  └─────────────────────────────────────────┘    │
└─────────────────────────────────────────────────┘
```


---

## Options Explored

### Option A: TabViewBlock as Union Member + Extend Existing Blocks

Add `TabViewBlock` as a new member of the `InfographicBlock` discriminated union. Add `AccordionBlock` and `ChecklistBlock` as new block types. Extend `BulletListBlock` and `TableBlock` in-place with new styling fields. Template auto-detection uses a two-step LLM call.

The `InfographicResponse` model stays unchanged — `blocks` remains a flat list, but can now contain a `TabViewBlock` that internally holds `TabPane` objects with their own nested block lists. This preserves composability (title block above tabs, callout below tabs).

For auto-detection: when `template=None`, a lightweight first LLM call determines the best template based on the question, then the full generation uses that template.

✅ **Pros:**
- Zero breaking changes to `InfographicResponse` — backward compatible.
- Composable: a single infographic can mix flat blocks and tabbed sections.
- Consistent philosophy: everything is a block, the renderer dispatches by type.
- `BulletListBlock` and `TableBlock` extensions are additive (optional fields default to `None`/existing values).
- Discriminated union pattern already proven with 12 block types.

❌ **Cons:**
- Recursive `InfographicBlock` references in `TabPane.blocks` and `AccordionItem.content_blocks` require `model_rebuild()`.
- Larger JSON payloads for multi-tab infographics (15-25 KB vs 2-4 KB).
- Two-step LLM call for auto-detection adds latency.

📊 **Effort:** High

📦 **Libraries / Tools:**
| Package | Purpose | Notes |
|---|---|---|
| `nh3` | HTML sanitization for AccordionItem.html_content | Rust-based, successor to bleach |
| `pydantic` v2 | `model_rebuild()` for forward references | Already in use |
| `markdown-it-py` | Markdown rendering in blocks | Already in use |

🔗 **Existing Code to Reuse:**
- `parrot/models/infographic.py` — BlockType enum, all existing block models, InfographicBlock union, InfographicResponse with `_normalise_payload()`
- `parrot/models/infographic_templates.py` — InfographicTemplate, BlockSpec, `to_prompt_instruction()`, InfographicTemplateRegistry
- `parrot/outputs/formats/infographic_html.py` — InfographicHTMLRenderer, `_block_renderers` dispatch dict, `_render_blocks()` hero-card grouping pattern, BASE_CSS, `_assemble_document()`
- `parrot/bots/abstract.py` — `get_infographic()` method (template resolution, ask() call, content negotiation)

---

### Option B: Tabs as Top-Level Field on InfographicResponse

Add an optional `tabs: List[TabPane]` field directly on `InfographicResponse`, alongside the existing `blocks`. A model validator ensures either `blocks` or `tabs` is populated. New block types (Accordion, Checklist) are added to the union as in Option A. BulletListBlock and TableBlock are extended in-place.

✅ **Pros:**
- Clearer separation: flat infographics use `blocks`, tabbed ones use `tabs`.
- Simpler LLM prompt: "populate the tabs array" is easier to describe than "put a TabViewBlock inside blocks".
- No recursive nesting concern at the Response level — tabs are one level deep.

❌ **Cons:**
- Breaking change to `InfographicResponse` schema (new required-or-alternative field).
- Not composable: can't have a title block above tabs and a callout below in the same blocks list.
- Tabs become a special case rather than following the "everything is a block" pattern.
- All consumers of `InfographicResponse` must handle the new `tabs` field.
- AccordionBlock still needs recursive `InfographicBlock` references regardless.

📊 **Effort:** High

📦 **Libraries / Tools:**
| Package | Purpose | Notes |
|---|---|---|
| `nh3` | HTML sanitization | Same as Option A |
| `pydantic` v2 | Model validation, forward refs | Already in use |

🔗 **Existing Code to Reuse:**
- Same as Option A, but `InfographicResponse` model needs structural changes.
- `infographic_html.py` renderer needs a new top-level branch for `tabs` mode.

---

### Option C: Micro-Frontend Component System

Instead of extending the Pydantic model, define blocks as a registry of renderable components. Each component is a self-contained unit (model + renderer + CSS + JS) registered at startup. TabView becomes a "layout component" that composes child components. This is a plugin-style architecture.

✅ **Pros:**
- Maximum extensibility: new block types can be added without touching the union or core models.
- Each component owns its own assets (CSS, JS), avoiding a monolithic stylesheet.
- Natural path toward user-defined custom blocks.

❌ **Cons:**
- Major architectural change — rewrites the entire block system.
- Pydantic discriminated union would be replaced with a generic `Dict[str, Any]` payload, losing type safety.
- Over-engineered for the immediate need (5 new block types).
- LLM structured output works best with typed models, not generic dicts.
- Testing and validation become significantly harder.

📊 **Effort:** Very High

📦 **Libraries / Tools:**
| Package | Purpose | Notes |
|---|---|---|
| `nh3` | HTML sanitization | Same as others |
| Custom registry | Component registration | Would need to be built |

🔗 **Existing Code to Reuse:**
- Limited reuse — this is a rewrite of the block and rendering system.

---

## Recommendation

**Option A** is recommended because:

1. **Zero breaking changes**: `InfographicResponse` keeps its existing shape. All current infographics, templates, and consumers continue working unchanged.
2. **Composability**: A multi-tab infographic naturally represents as `[TitleBlock, TabViewBlock]` — the title sits above the tabs, exactly like the visual reference. Option B forces an either/or between flat blocks and tabs.
3. **Consistent pattern**: The existing system processes blocks via a dispatch dict (`_block_renderers`). Adding new block types follows the same proven pattern. No special cases.
4. **Forward references are solved**: Pydantic v2's `model_rebuild()` handles the circular reference between `TabPane.blocks → InfographicBlock → TabViewBlock` cleanly.
5. **Auto-detection via two-step LLM**: The pre-pass is a lightweight call (just asking "which template?"), adds minimal latency, and gives the system intelligent template selection without hardcoded heuristics.

The tradeoff is complexity in the JSON schema (recursive types) and larger payloads, but both are well within LLM output limits and Pydantic's capabilities.

---

## Feature Description

### User-Facing Behavior

**Explicit template selection:**
A user calls `get_infographic(question, template="multi_tab")` and receives an HTML infographic with:
- A title/subtitle header at the top.
- A tab navigation bar with 3-7 pill-style buttons.
- Each tab pane contains its own set of content blocks (summaries, bullet lists, tables, accordions, checklists, charts, etc.).
- Clicking a tab shows that pane and hides others. Only one pane visible at a time.
- Accordions within tabs expand/collapse on click. Multiple can be open simultaneously.
- Checklists display visual checkbox indicators (checked/unchecked).
- Tables support styled variants: striped, bordered, compact, comparison.
- Bullet lists can display in multi-column grid layouts with colored dot indicators.

**Auto-detection (no template specified):**
When `template=None`, the system makes a lightweight LLM pre-pass to determine the best template. If the question implies multi-section content (methodology, multi-chapter report, process documentation), it selects `multi_tab`. Otherwise it falls back to existing templates.

**Print behavior:**
Tab navigation hides; all tab panes display sequentially with page breaks. Accordions expand.

### Internal Behavior

1. **Template resolution**: `get_infographic()` checks `template` param. If `None`, calls a pre-pass LLM prompt: "Given this question, which template is best?" with the list of available templates. Uses the returned template name.
2. **Prompt generation**: `TEMPLATE_MULTI_TAB.to_prompt_instruction()` generates extended instructions describing the tab_view block structure, allowed inner block types, and constraints (3-7 tabs, no nested TabView/Accordion).
3. **LLM generation**: `ask()` with `structured_output=InfographicResponse`. The LLM returns JSON with `blocks: [TitleBlock, TabViewBlock{tabs: [TabPane{blocks: [...]}, ...]}]`.
4. **Pydantic validation**: Discriminated union resolves each block by `type` field. `TabViewBlock` validates its `tabs` array. `TabPane.blocks` recursively validates inner blocks. `model_rebuild()` resolves forward references.
5. **Normalization**: `_normalise_payload()` handles LLM output quirks for new block types (e.g., tab_view with missing active_tab, accordion items with neither content_blocks nor html_content).
6. **Rendering**: `InfographicHTMLRenderer` dispatches to new render methods. `render_tab_view_block()` generates nav + panes, recursively calling `render_block()` for each pane's blocks. Tab/accordion JS is injected inline. CSS extends BASE_CSS with new block styles.
7. **Content negotiation**: `accept="text/html"` returns rendered HTML; `accept="application/json"` returns raw InfographicResponse JSON.

### Edge Cases & Error Handling

- **Empty tabs**: If a TabPane has no blocks, render an empty pane with a "No content" placeholder.
- **Single tab**: TabViewBlock requires min 2 tabs. Pydantic validation rejects 0 or 1 tab.
- **Deeply nested blocks**: Renderer enforces `max_depth=3`. Beyond that, renders a comment/warning instead of the block.
- **html_content XSS**: `AccordionItem.html_content` is sanitized through `nh3` with a restrictive tag allowlist before rendering.
- **Large JSON payloads**: Multi-tab infographics may need higher `max_tokens`. The template prompt can hint at expected size.
- **Auto-detection failure**: If the pre-pass LLM call fails or returns an unknown template, fall back to `"basic"`.
- **Multiple TabViewBlocks**: Each gets a unique instance ID prefix for JS scoping (tv0, tv1, etc.) to avoid DOM conflicts.
- **Missing active_tab**: Defaults to the first tab in the list.
- **AccordionItem with both content_blocks and html_content**: `content_blocks` takes priority; `html_content` is ignored if `content_blocks` is non-empty.

---

## Capabilities

### New Capabilities
- `infographic-tab-view`: TabViewBlock and TabPane models enabling tabbed navigation in infographics.
- `infographic-accordion`: AccordionBlock with collapsible sections containing nested content blocks or sanitized HTML.
- `infographic-checklist`: ChecklistBlock for visual checkbox-style lists.
- `infographic-multi-tab-template`: The `multi_tab` template definition and registration.
- `infographic-template-auto-detect`: Two-step LLM pre-pass for automatic template selection.
- `infographic-inline-js`: Curated collection of inline vanilla JS for tab switching, accordion toggling.

### Modified Capabilities
- `infographic-bullet-list`: Extend `BulletListBlock` with `color`, `columns`, and `style` fields.
- `infographic-table`: Refactor `TableBlock` to support `ColumnDef`, `TableStyle`, `highlight_first_column`, `responsive`, and `caption`.
- `infographic-html-renderer`: Extend `InfographicHTMLRenderer` with 4 new render methods and updated CSS/JS.

---

## Impact & Integration

| Affected Component | Impact Type | Notes |
|---|---|---|
| `parrot/models/infographic.py` | extends | +3 new block models (TabViewBlock, AccordionBlock, ChecklistBlock), extend BulletListBlock + TableBlock, expand BlockType enum, update InfographicBlock union, model_rebuild() |
| `parrot/models/infographic_templates.py` | extends | +TEMPLATE_MULTI_TAB, extend to_prompt_instruction() for tab_view blocks, register in _register_builtins() |
| `parrot/outputs/formats/infographic_html.py` | extends | +4 new render methods, +CSS for tabs/accordion/checklist, +inline JS collection, update _block_renderers dispatch |
| `parrot/bots/abstract.py` | modifies | Add template auto-detection pre-pass in get_infographic() when template=None |
| `pyproject.toml` | depends on | Add `nh3` dependency |
| `tests/test_infographic_html.py` | extends | +tests for all new blocks and rendering |
| Existing infographics | no change | Fully backward compatible |

---

## Code Context

### User-Provided Code

```python
# Source: sdd/proposals/multi-tab-infographic.md (proposal document)
# The proposal contains detailed model designs for all new blocks.
# Key decisions from interactive discovery:
# - Extend BulletListBlock in-place (add color, columns, style)
# - Aggressively refactor TableBlock (add ColumnDef, TableStyle)
# - AccordionBlock: Option C (content_blocks + html_content with nh3 sanitization)
# - TabViewBlock as union member (Option A from proposal §3.2)
# - max_depth = 3
# - Use nh3 for HTML sanitization (not bleach)
# - Auto-detect template via two-step LLM pre-pass
# - Inline vanilla JS from curated collection, no CDN
```

### Verified Codebase References

#### Classes & Signatures
```python
# From parrot/models/infographic.py:40-53
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

# From parrot/models/infographic.py:218-230
class BulletListBlock(BaseModel):
    type: Literal["bullet_list"] = "bullet_list"
    title: Optional[str] = Field(None, description="List heading")
    items: List[str] = Field(...)
    ordered: Optional[bool] = Field(False)
    icon: Optional[str] = Field(None)

# From parrot/models/infographic.py:233-284
class TableBlock(BaseModel):
    type: Literal["table"] = "table"
    title: Optional[str] = Field(None)
    columns: List[str] = Field(...)
    rows: List[List[Any]] = Field(...)
    highlight_first_column: Optional[bool] = Field(False)
    sortable: Optional[bool] = Field(False)
    # Has _normalize_table_data() model_validator

# From parrot/models/infographic.py:392-405
InfographicBlock = Union[
    TitleBlock, HeroCardBlock, SummaryBlock, ChartBlock,
    BulletListBlock, TableBlock, ImageBlock, QuoteBlock,
    CalloutBlock, DividerBlock, TimelineBlock, ProgressBlock,
]

# From parrot/models/infographic.py:412-479
class InfographicResponse(BaseModel):
    template: Optional[str] = Field(None)
    theme: Optional[str] = Field(None)
    blocks: List[Annotated[InfographicBlock, Discriminator("type")]] = Field(...)
    metadata: Optional[Dict[str, Any]] = Field(default_factory=dict)
    # Has _normalise_payload() model_validator

# From parrot/models/infographic.py:486-531
class ThemeConfig(BaseModel):
    name: str
    primary: str        # e.g. "#6366f1"
    primary_dark: str
    primary_light: str
    accent_green: str
    accent_amber: str
    accent_red: str
    neutral_bg: str
    neutral_border: str
    neutral_muted: str
    neutral_text: str
    body_bg: str
    font_family: str
    def to_css_variables(self) -> str: ...  # line 511

# From parrot/models/infographic_templates.py:21-44
class BlockSpec(BaseModel):
    block_type: BlockType
    required: bool = True
    description: Optional[str] = None
    min_items: Optional[int] = None
    max_items: Optional[int] = None
    constraints: Optional[Dict[str, str]] = {}

# From parrot/models/infographic_templates.py:47-93
class InfographicTemplate(BaseModel):
    name: str
    description: str
    block_specs: List[BlockSpec]
    default_theme: Optional[str] = None
    def to_prompt_instruction(self) -> str: ...  # line 60

# From parrot/outputs/formats/infographic_html.py:412-439
class InfographicHTMLRenderer:
    def __init__(self) -> None:
        self._md = markdown_it.MarkdownIt()
        self._block_renderers: Dict[str, Any] = {
            "title": self._render_title,
            "hero_card": self._render_hero_card,
            # ... 12 entries total
        }
    def render_to_html(self, data, theme=None) -> str: ...  # line 473

# From parrot/bots/abstract.py:2599-2611
async def get_infographic(
    self,
    question: str,
    template: Optional[str] = "basic",
    session_id: Optional[str] = None,
    user_id: Optional[str] = None,
    use_vector_context: bool = True,
    use_conversation_history: bool = False,
    theme: Optional[str] = None,
    accept: str = "text/html",
    ctx: Optional[RequestContext] = None,
    **kwargs,
) -> AIMessage: ...
```

#### Verified Imports
```python
# These imports have been confirmed to work:
from parrot.models.infographic import (  # parrot/models/infographic.py
    BlockType, InfographicBlock, InfographicResponse,
    ThemeConfig, ThemeRegistry,
    TitleBlock, HeroCardBlock, SummaryBlock, ChartBlock,
    BulletListBlock, TableBlock, ImageBlock, QuoteBlock,
    CalloutBlock, DividerBlock, TimelineBlock, ProgressBlock,
)
from parrot.models.infographic_templates import (  # parrot/models/infographic_templates.py
    BlockSpec, InfographicTemplate, InfographicTemplateRegistry,
    infographic_registry,
)
from parrot.outputs.formats.infographic_html import (  # parrot/outputs/formats/infographic_html.py
    InfographicHTMLRenderer,
)
```

#### Key Attributes & Constants
- `InfographicHTMLRenderer._block_renderers` → `Dict[str, Callable]` (infographic_html.py:425)
- `InfographicTemplateRegistry._templates` → internal dict of registered templates (infographic_templates.py:317)
- `ThemeRegistry._themes` → internal dict of registered themes (infographic.py:542)
- `infographic_registry` → module-level singleton `InfographicTemplateRegistry` (infographic_templates.py:382)
- CSS variables from ThemeConfig: `--primary`, `--primary-dark`, `--primary-light`, `--accent-green`, `--accent-amber`, `--accent-red`, `--neutral-bg`, `--neutral-border`, `--neutral-muted`, `--neutral-text`, `--body-bg`, `--font-family`

### Does NOT Exist (Anti-Hallucination)
- ~~`parrot.models.infographic.TabViewBlock`~~ — does not exist yet
- ~~`parrot.models.infographic.AccordionBlock`~~ — does not exist yet
- ~~`parrot.models.infographic.ChecklistBlock`~~ — does not exist yet
- ~~`parrot.models.infographic.StyledTableBlock`~~ — will NOT be created (refactoring TableBlock instead)
- ~~`parrot.models.infographic.TitledBulletListBlock`~~ — will NOT be created (extending BulletListBlock instead)
- ~~`bleach`~~ — not in dependencies, not to be used (deprecated). Use `nh3` instead.
- ~~`nh3`~~ — not yet in dependencies, needs to be added to pyproject.toml
- ~~`InfographicHTMLRenderer._render_tab_view`~~ — does not exist yet
- ~~`InfographicHTMLRenderer._render_accordion`~~ — does not exist yet
- ~~`InfographicHTMLRenderer._render_checklist`~~ — does not exist yet
- ~~`TEMPLATE_MULTI_TAB`~~ — does not exist yet in infographic_templates.py
- ~~`BulletListBlock.color`~~ — does not exist yet (to be added)
- ~~`BulletListBlock.columns`~~ — does not exist yet (to be added)
- ~~`BulletListBlock.style`~~ — does not exist yet (to be added)
- ~~`TableBlock.style`~~ — does not exist yet (to be added)
- ~~`TableBlock.column_defs`~~ — does not exist yet (to be added)
- ~~`ColumnDef`~~ — does not exist yet
- ~~`TableStyle`~~ — does not exist yet

---

## Parallelism Assessment

- **Internal parallelism**: Moderate. The models task (new block types + extensions) must be completed first as all other tasks depend on it. However, once models are done, the renderer tasks for each new block type (tab_view, accordion, checklist, bullet_list styling, table styling) can potentially run in parallel since each render method is independent. The template task and auto-detection task are also independent of renderer work.
- **Cross-feature independence**: No conflicts with in-flight features detected. The infographic system is self-contained within `parrot/models/infographic.py`, `parrot/models/infographic_templates.py`, and `parrot/outputs/formats/infographic_html.py`. The only shared file is `parrot/bots/abstract.py` (for auto-detection), which is a small change to `get_infographic()`.
- **Recommended isolation**: `per-spec` — All tasks should run sequentially in a single worktree. The model definitions must land first, and the renderer methods reference each other's CSS/JS. The interdependencies make parallel worktrees risky (merge conflicts in shared files like infographic.py and infographic_html.py).
- **Rationale**: Three core files are modified by nearly every task. Sequential execution in one worktree avoids merge conflicts and ensures each task can build on the previous one's changes.

---

## Open Questions

- [x] **Token budget for multi-tab**: Should `get_infographic()` increase `max_tokens` when using `multi_tab` template? If so, what value? — *Owner: Jesus*: set to None (no limit).
- [x] **Tab icon rendering**: Support emoji in tab labels (confirmed), but should we also support icon CSS classes (e.g., Font Awesome)? Or emoji-only for v1? — *Owner: Jesus*: both, csss classes and emojis.
- [x] **Accordion ID generation**: Auto-generate IDs for AccordionItems when not provided? Use slugified title or UUID? — *Owner: Jesus*: uuid is safer.
- [x] **Template auto-detection prompt**: What exact prompt should the pre-pass use? Should it return just a template name or also a brief rationale? — *Owner: Jesus*: also a brief rationale.
- [x] **nh3 allowlist scope**: Which HTML tags/attributes should be allowed in AccordionItem.html_content? Proposal: `p, br, strong, em, ul, ol, li, a[href], span, div, h3, h4, code, pre, table, tr, td, th, thead, tbody`. — *Owner: Jesus*: proposal accepted.
