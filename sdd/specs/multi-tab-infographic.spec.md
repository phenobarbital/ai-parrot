# Feature Specification: Multi-Tab Infographic Template + New Component Blocks

**Feature ID**: FEAT-102
**Date**: 2026-04-15
**Author**: Jesus
**Status**: approved
**Target version**: 1.x.x

---

## 1. Motivation & Business Requirements

### Problem Statement

The current infographic system (`InfographicResponse`) uses a flat list of `InfographicBlock` items. This works for single-view reports (executive, dashboard, comparison) but cannot represent multi-section, tabbed infographics. Complex reports — such as methodology documentation with 5+ logical sections — require navigable tabs, collapsible accordion sections, visual checklists, and richer table/list styling.

The existing 12 block types and flat block list structure cannot express these patterns.

### Goals
- Introduce a `TabViewBlock` that enables tabbed navigation within infographics, where each tab contains its own sequence of content blocks.
- Add `AccordionBlock` for collapsible sections with nested content blocks or sanitized HTML.
- Add `ChecklistBlock` for visual checkbox-style lists.
- Extend `BulletListBlock` with `color`, `columns`, and `style` fields for richer list rendering.
- Refactor `TableBlock` to support `ColumnDef`, `TableStyle`, and advanced styling options.
- Create a `multi_tab` template definition for the new layout pattern.
- Add template auto-detection via a two-step LLM pre-pass when no template is specified.
- Maintain full backward compatibility with existing infographics.

### Non-Goals (explicitly out of scope)
- Telegram WebApp-compatible rendering (deferred to v2).
- CDN-based JavaScript libraries.
- User-defined custom block types / plugin system.
- Drag-and-drop tab reordering or interactive editing.
- PDF export pipeline changes (current print CSS is sufficient).

---

## 2. Architectural Design

### Overview

Extend the existing block-based infographic system by adding 3 new block types (`TabViewBlock`, `AccordionBlock`, `ChecklistBlock`) to the `InfographicBlock` discriminated union, and extending 2 existing blocks (`BulletListBlock`, `TableBlock`) with styling fields. The `InfographicResponse` model remains unchanged — `TabViewBlock` is simply another block in the union, keeping the "everything is a block" philosophy.

The renderer gains 3 new render methods plus updates to 2 existing ones, along with inline vanilla JS for tab switching and accordion toggling. A curated JS collection approach keeps scripts organized and CDN-free.

Template auto-detection adds a lightweight LLM pre-pass in `get_infographic()` when `template=None`.

### Component Diagram
```
get_infographic(question, template=None|"multi_tab")
  │
  ├── [template=None] → Pre-pass LLM call → select template
  │
  ├── InfographicTemplate.to_prompt_instruction()
  │     └── Extended for tab_view block descriptions
  │
  ├── ask() → structured_output=InfographicResponse
  │     └── JSON with TabViewBlock containing TabPane[].blocks[]
  │
  ├── InfographicResponse._normalise_payload()
  │     └── Handles tab_view, accordion, checklist normalization
  │
  └── InfographicHTMLRenderer.render_to_html()
        ├── _render_tab_view() → nav + panes + recursive block rendering
        ├── _render_accordion() → collapsible sections + recursive rendering
        ├── _render_checklist() → checkbox visual list
        ├── _render_bullet_list() → updated with color/columns/style
        ├── _render_table() → updated with ColumnDef/TableStyle
        └── Inline JS (tab switching, accordion toggle)
```

### Integration Points

| Existing Component | Integration Type | Notes |
|---|---|---|
| `parrot/models/infographic.py` | extends | +3 new block models, extend BulletListBlock + TableBlock, expand BlockType enum, update InfographicBlock union |
| `parrot/models/infographic_templates.py` | extends | +TEMPLATE_MULTI_TAB, extend to_prompt_instruction() for tab_view, register in _register_builtins() |
| `parrot/outputs/formats/infographic_html.py` | extends | +3 new render methods, update 2 existing, +CSS, +inline JS collection |
| `parrot/bots/abstract.py` | modifies | Add template auto-detection pre-pass in get_infographic() |
| `pyproject.toml` | depends on | Add `nh3` dependency |

### Data Models

```python
# New enums
class TableStyle(str, Enum):
    DEFAULT = "default"
    STRIPED = "striped"
    BORDERED = "bordered"
    COMPACT = "compact"
    COMPARISON = "comparison"

class BulletListStyle(str, Enum):
    DEFAULT = "default"
    TITLED = "titled"       # Styled header with dot indicators
    COMPACT = "compact"

# Extended BulletListBlock (new optional fields)
class BulletListBlock(BaseModel):
    type: Literal["bullet_list"] = "bullet_list"
    title: Optional[str]
    items: List[str]
    ordered: Optional[bool] = False
    icon: Optional[str] = None
    # New fields:
    color: Optional[str] = None       # Dot indicator color (hex)
    columns: Optional[int] = None     # Grid columns (1-4)
    style: Optional[BulletListStyle] = None

# Refactored TableBlock
class ColumnDef(BaseModel):
    header: str
    width: Optional[str] = None      # CSS width
    align: Optional[Literal["left", "center", "right"]] = None
    color: Optional[str] = None      # Header accent color

class TableBlock(BaseModel):
    type: Literal["table"] = "table"
    title: Optional[str] = None
    columns: Union[List[str], List[ColumnDef]]  # Backward compat: accept both
    rows: List[List[Any]]
    highlight_first_column: Optional[bool] = False
    sortable: Optional[bool] = False
    # New fields:
    style: Optional[TableStyle] = None
    responsive: Optional[bool] = True
    caption: Optional[str] = None

# New: AccordionBlock
class AccordionItem(BaseModel):
    id: Optional[str] = None          # Auto-generated if None
    title: str
    subtitle: Optional[str] = None
    badge: Optional[str] = None
    badge_color: Optional[str] = None
    number: Optional[int] = None
    number_color: Optional[str] = None
    content_blocks: List["InfographicBlock"] = []   # Recursive, type-safe
    html_content: Optional[str] = None              # Escape hatch, sanitized via nh3
    expanded: bool = False

class AccordionBlock(BaseModel):
    type: Literal["accordion"] = "accordion"
    title: Optional[str] = None
    items: List[AccordionItem]
    allow_multiple: bool = True

# New: ChecklistBlock
class ChecklistItem(BaseModel):
    text: str
    checked: bool = False
    description: Optional[str] = None

class ChecklistBlock(BaseModel):
    type: Literal["checklist"] = "checklist"
    title: Optional[str] = None
    items: List[ChecklistItem]
    style: Optional[Literal["default", "acceptance", "todo", "compact"]] = "default"

# New: TabViewBlock
class TabPane(BaseModel):
    id: str                            # Unique slug
    label: str                         # Tab button text
    icon: Optional[str] = None         # Emoji or icon
    blocks: List["InfographicBlock"]   # Recursive block list

class TabViewBlock(BaseModel):
    type: Literal["tab_view"] = "tab_view"
    tabs: List[TabPane]                # min_length=2
    active_tab: Optional[str] = None   # ID of default active tab
    style: Optional[Literal["pills", "underline", "boxed"]] = "pills"
```

### New Public Interfaces

No new public classes or functions beyond the data models above. The existing `get_infographic()` method gains auto-detection behavior when `template=None`. The existing `InfographicHTMLRenderer.render_to_html()` handles all new block types transparently.

---

## 3. Module Breakdown

### Module 1: Block Models & Enums
- **Path**: `parrot/models/infographic.py`
- **Responsibility**: Define `AccordionBlock`, `ChecklistBlock`, `TabViewBlock`, `TabPane`, `AccordionItem`, `ChecklistItem`, `ColumnDef`, `TableStyle`, `BulletListStyle` enums. Extend `BulletListBlock` with `color`, `columns`, `style`. Refactor `TableBlock` with `ColumnDef` support, `TableStyle`, `responsive`, `caption`. Expand `BlockType` enum. Update `InfographicBlock` union. Call `model_rebuild()` for forward references. Update `_normalise_payload()` for new block type quirks.
- **Depends on**: None (foundation module)

### Module 2: Multi-Tab Template
- **Path**: `parrot/models/infographic_templates.py`
- **Responsibility**: Define `TEMPLATE_MULTI_TAB` with `BlockSpec` for title + tab_view. Extend `to_prompt_instruction()` to generate LLM instructions for tab_view blocks (describing TabPane structure, allowed inner block types, nesting constraints). Register in `_register_builtins()`.
- **Depends on**: Module 1 (new BlockType values)

### Module 3: Template Auto-Detection
- **Path**: `parrot/bots/abstract.py`
- **Responsibility**: In `get_infographic()`, when `template=None`, make a lightweight LLM pre-pass asking "which template best fits this question?" with the list of available templates. Use the returned template name for the main generation call. Fall back to `"basic"` on failure.
- **Depends on**: Module 2 (multi_tab template must be registered)

### Module 4: Renderer — New Block Methods
- **Path**: `parrot/outputs/formats/infographic_html.py`
- **Responsibility**: Implement `_render_tab_view()`, `_render_accordion()`, `_render_checklist()`. Update `_render_bullet_list()` and `_render_table()` for new styling fields. Add entries to `_block_renderers` dispatch dict. Implement recursive `_render_block()` with depth tracking (`max_depth=3`). Generate inline vanilla JS for tab switching and accordion toggling. Add CSS for all new block types using ThemeConfig CSS variables. Add print CSS for tabs (show all panes) and accordions (expand all). Sanitize `AccordionItem.html_content` with `nh3`.
- **Depends on**: Module 1 (new block models)

### Module 5: Tests
- **Path**: `tests/test_infographic_html.py` (extend), new `tests/test_infographic_multi_tab.py`
- **Responsibility**: Unit tests for each new block model (serialization, deserialization, validation). Round-trip tests (Pydantic → JSON → Pydantic) for recursive structures. Renderer tests for each new/updated block. Integration test: full multi-tab infographic generation and HTML validation. Edge case tests: empty tabs, single tab rejection, max depth exceeded, html_content sanitization.
- **Depends on**: Modules 1, 2, 4

---

## 4. Test Specification

### Unit Tests
| Test | Module | Description |
|---|---|---|
| `test_accordion_block_serialization` | Module 1 | AccordionBlock with content_blocks round-trips through JSON |
| `test_accordion_item_html_content_only` | Module 1 | AccordionItem with html_content (no content_blocks) validates |
| `test_checklist_block_serialization` | Module 1 | ChecklistBlock with mixed checked/unchecked items |
| `test_tab_view_block_min_tabs` | Module 1 | TabViewBlock rejects < 2 tabs |
| `test_tab_view_recursive_blocks` | Module 1 | TabPane.blocks contains valid InfographicBlock instances |
| `test_bullet_list_new_fields` | Module 1 | BulletListBlock with color, columns, style validates |
| `test_bullet_list_backward_compat` | Module 1 | Existing BulletListBlock JSON (without new fields) still validates |
| `test_table_column_def` | Module 1 | TableBlock with ColumnDef columns validates |
| `test_table_backward_compat` | Module 1 | Existing TableBlock JSON (string columns) still validates |
| `test_table_style_enum` | Module 1 | TableStyle enum values are correct |
| `test_normalise_payload_tab_view` | Module 1 | _normalise_payload handles tab_view quirks |
| `test_template_multi_tab_prompt` | Module 2 | TEMPLATE_MULTI_TAB.to_prompt_instruction() includes tab instructions |
| `test_template_registry_multi_tab` | Module 2 | multi_tab is registered and retrievable |
| `test_render_tab_view` | Module 4 | Tab navigation HTML with correct IDs, active state |
| `test_render_accordion` | Module 4 | Accordion with expand/collapse structure |
| `test_render_checklist` | Module 4 | Checklist with checkbox visuals |
| `test_render_bullet_list_columns` | Module 4 | Bullet list with grid columns CSS |
| `test_render_table_styled` | Module 4 | Table with striped/bordered/comparison styles |
| `test_render_depth_limit` | Module 4 | Blocks beyond max_depth=3 produce warning comment |
| `test_accordion_html_sanitization` | Module 4 | html_content is sanitized via nh3 (XSS tags removed) |
| `test_multiple_tab_views_unique_ids` | Module 4 | Multiple TabViewBlocks get unique JS scope prefixes |
| `test_print_css_tabs_expanded` | Module 4 | Print stylesheet shows all tab panes |

### Integration Tests
| Test | Description |
|---|---|
| `test_multi_tab_full_roundtrip` | Construct InfographicResponse with TabViewBlock containing Accordion+Checklist, render to HTML, validate structure |
| `test_backward_compat_existing_templates` | All 6 existing templates still produce valid HTML |

### Test Data / Fixtures
```python
@pytest.fixture
def multi_tab_response():
    """Full multi-tab InfographicResponse with all new block types."""
    return InfographicResponse(
        template="multi_tab",
        theme="light",
        blocks=[
            TitleBlock(title="Test Report", subtitle="Multi-tab"),
            TabViewBlock(tabs=[
                TabPane(id="overview", label="Overview", blocks=[
                    SummaryBlock(content="Overview content"),
                ]),
                TabPane(id="details", label="Details", blocks=[
                    AccordionBlock(items=[
                        AccordionItem(title="Phase 1", content_blocks=[
                            BulletListBlock(items=["Item 1", "Item 2"], color="#534AB7", columns=2),
                        ]),
                    ]),
                    ChecklistBlock(title="Criteria", items=[
                        ChecklistItem(text="Criterion 1", checked=True),
                        ChecklistItem(text="Criterion 2"),
                    ]),
                ]),
            ]),
        ],
    )
```

---

## 5. Acceptance Criteria

- [x] All new block models validate correctly with Pydantic v2 discriminated unions.
- [ ] Forward references resolve via `model_rebuild()` — no circular import errors.
- [ ] Existing infographics (all 6 templates) produce identical output (zero regressions).
- [ ] `BulletListBlock` backward compatible: JSON without `color`/`columns`/`style` still validates.
- [ ] `TableBlock` backward compatible: JSON with `List[str]` columns still validates.
- [ ] `TabViewBlock` rejects < 2 tabs at validation time.
- [ ] Rendered HTML uses only CSS variables from `ThemeConfig` (no hardcoded colors in new blocks).
- [ ] Tab switching works via inline vanilla JS (no CDN).
- [ ] Accordion expand/collapse works via inline vanilla JS.
- [ ] `AccordionItem.html_content` is sanitized via `nh3` before rendering.
- [ ] Nesting depth enforced: blocks beyond depth 3 are skipped with a comment.
- [ ] Print CSS: tab nav hidden, all panes visible, accordions expanded.
- [ ] Responsive: tab nav wraps, tables scroll/stack, bullet columns collapse.
- [ ] `multi_tab` template registered and selectable.
- [ ] Template auto-detection selects `multi_tab` for multi-section questions when `template=None`.
- [ ] All unit tests pass (`pytest tests/ -v -k infographic`).
- [ ] No breaking changes to existing public API.

---

## 6. Codebase Contract

### Verified Imports
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

### Existing Class Signatures
```python
# parrot/models/infographic.py:39-52
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

# parrot/models/infographic.py:218-230
class BulletListBlock(BaseModel):
    type: Literal["bullet_list"] = "bullet_list"       # line 220
    title: Optional[str] = Field(None)                  # line 221
    items: List[str] = Field(...)                       # line 222
    ordered: Optional[bool] = Field(False)              # line 226
    icon: Optional[str] = Field(None)                   # line 227

# parrot/models/infographic.py:233-284
class TableBlock(BaseModel):
    type: Literal["table"] = "table"                    # line 235
    title: Optional[str] = Field(None)                  # line 236
    columns: List[str] = Field(...)                     # line 237
    rows: List[List[Any]] = Field(...)                  # line 238
    highlight_first_column: Optional[bool] = Field(False)  # line 242
    sortable: Optional[bool] = Field(False)             # line 246
    # Has _normalize_table_data() model_validator        # line 251

# parrot/models/infographic.py:392-405
InfographicBlock = Union[
    TitleBlock, HeroCardBlock, SummaryBlock, ChartBlock,
    BulletListBlock, TableBlock, ImageBlock, QuoteBlock,
    CalloutBlock, DividerBlock, TimelineBlock, ProgressBlock,
]

# parrot/models/infographic.py:412-479
class InfographicResponse(BaseModel):
    template: Optional[str] = Field(None)               # line 418
    theme: Optional[str] = Field(None)                  # line 422
    blocks: List[Annotated[InfographicBlock, Discriminator("type")]]  # line 426
    metadata: Optional[Dict[str, Any]] = Field(default_factory=dict)  # line 430
    # Has _normalise_payload() model_validator           # line 435

# parrot/models/infographic.py:486-531
class ThemeConfig(BaseModel):
    name: str                   # line 493
    primary: str                # line 494
    primary_dark: str           # line 495
    primary_light: str          # line 496
    accent_green: str           # line 497
    accent_amber: str           # line 498
    accent_red: str             # line 499
    neutral_bg: str             # line 500
    neutral_border: str         # line 501
    neutral_muted: str          # line 502
    neutral_text: str           # line 503
    body_bg: str                # line 504
    font_family: str            # line 505
    def to_css_variables(self) -> str: ...  # line 511

# parrot/models/infographic_templates.py:21-44
class BlockSpec(BaseModel):
    block_type: BlockType                               # line 22
    required: bool = True                               # line 23
    description: Optional[str] = None                   # line 24
    min_items: Optional[int] = None                     # line 25
    max_items: Optional[int] = None                     # line 26
    constraints: Optional[Dict[str, str]] = {}          # line 27

# parrot/models/infographic_templates.py:47-93
class InfographicTemplate(BaseModel):
    name: str                                           # line 49
    description: str                                    # line 50
    block_specs: List[BlockSpec]                        # line 51
    default_theme: Optional[str] = None                 # line 55
    def to_prompt_instruction(self) -> str: ...         # line 60

# parrot/outputs/formats/infographic_html.py:412-439
class InfographicHTMLRenderer(BaseRenderer):
    def __init__(self) -> None:                         # line 424
        self._md = markdown_it.MarkdownIt()             # line 425
        self._block_renderers: Dict[str, Any] = {       # line 426
            "title": self._render_title,
            # ... 12 entries
        }
    async def render(self, response, environment, export_format, include_code, **kwargs) -> Tuple[str, Optional[Any]]: ...  # line 443
    def render_to_html(self, data: Union[InfographicResponse, dict], theme: Optional[str] = None) -> str: ...  # line 473
    def _assemble_document(self, page_title, theme_css, blocks_html, echarts_script="") -> str: ...  # line 535
    def _render_blocks(self, data: InfographicResponse) -> str: ...  # line 564

# parrot/bots/abstract.py:2599-2700
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

### Integration Points
| New Component | Connects To | Via | Verified At |
|---|---|---|---|
| `TabViewBlock` | `InfographicBlock` union | Union member | `infographic.py:392` |
| `AccordionBlock` | `InfographicBlock` union | Union member | `infographic.py:392` |
| `ChecklistBlock` | `InfographicBlock` union | Union member | `infographic.py:392` |
| `_render_tab_view()` | `InfographicHTMLRenderer._block_renderers` | Dict entry | `infographic_html.py:426` |
| `_render_accordion()` | `InfographicHTMLRenderer._block_renderers` | Dict entry | `infographic_html.py:426` |
| `_render_checklist()` | `InfographicHTMLRenderer._block_renderers` | Dict entry | `infographic_html.py:426` |
| `TEMPLATE_MULTI_TAB` | `InfographicTemplateRegistry._register_builtins()` | Registration | `infographic_templates.py:320` |
| Auto-detection pre-pass | `get_infographic()` | Conditional branch when template=None | `abstract.py:2660` |

### Does NOT Exist (Anti-Hallucination)
- ~~`parrot.models.infographic.TabViewBlock`~~ — does not exist yet (to be created in Module 1)
- ~~`parrot.models.infographic.AccordionBlock`~~ — does not exist yet (to be created in Module 1)
- ~~`parrot.models.infographic.ChecklistBlock`~~ — does not exist yet (to be created in Module 1)
- ~~`parrot.models.infographic.TabPane`~~ — does not exist yet
- ~~`parrot.models.infographic.AccordionItem`~~ — does not exist yet
- ~~`parrot.models.infographic.ChecklistItem`~~ — does not exist yet
- ~~`parrot.models.infographic.ColumnDef`~~ — does not exist yet
- ~~`parrot.models.infographic.TableStyle`~~ — does not exist yet
- ~~`parrot.models.infographic.BulletListStyle`~~ — does not exist yet
- ~~`parrot.models.infographic.StyledTableBlock`~~ — will NOT be created (TableBlock refactored instead)
- ~~`parrot.models.infographic.TitledBulletListBlock`~~ — will NOT be created (BulletListBlock extended instead)
- ~~`bleach`~~ — NOT in dependencies, NOT to be used (deprecated). Use `nh3` instead.
- ~~`nh3`~~ — NOT yet in dependencies (must be added to pyproject.toml)
- ~~`InfographicHTMLRenderer._render_tab_view`~~ — does not exist yet
- ~~`InfographicHTMLRenderer._render_accordion`~~ — does not exist yet
- ~~`InfographicHTMLRenderer._render_checklist`~~ — does not exist yet
- ~~`TEMPLATE_MULTI_TAB`~~ — does not exist yet
- ~~`BulletListBlock.color`~~ — does not exist yet
- ~~`BulletListBlock.columns`~~ — does not exist yet
- ~~`BulletListBlock.style`~~ — does not exist yet
- ~~`TableBlock.style`~~ — does not exist yet (the field, not the enum)
- ~~`TableBlock.column_defs`~~ — will NOT exist (columns field is refactored to accept Union[List[str], List[ColumnDef]])
- ~~`TableBlock.responsive`~~ — does not exist yet
- ~~`TableBlock.caption`~~ — does not exist yet

---

## 7. Implementation Notes & Constraints

### Patterns to Follow
- Use Pydantic v2 discriminated unions (`Discriminator("type")`) for all block types — existing pattern at `infographic.py:426`.
- Use `model_rebuild()` after defining the `InfographicBlock` union to resolve forward references in `TabPane.blocks` and `AccordionItem.content_blocks`.
- Follow the `_block_renderers` dispatch dict pattern in `InfographicHTMLRenderer` for new render methods.
- Use `html.escape()` for all user-provided text in HTML output (existing pattern throughout renderer).
- Use CSS variables from `ThemeConfig` exclusively (no hardcoded colors).
- Inline JS must be vanilla — no external libraries or CDN.

### Nesting Rules (Enforced)
- `max_depth=3`: TabView → Accordion → flat blocks.
- `TabViewBlock` must NOT appear inside `TabPane.blocks` (no nested tabs).
- `AccordionBlock` must NOT appear inside `AccordionItem.content_blocks` (no nested accordions).
- The renderer tracks depth and skips blocks that exceed `max_depth`, emitting an HTML comment.

### AccordionItem Content Priority
- If `content_blocks` is non-empty, render those blocks recursively. Ignore `html_content`.
- If `content_blocks` is empty and `html_content` is provided, sanitize via `nh3` and render.
- If both are empty, render an empty accordion body.

### TableBlock Refactoring — Backward Compatibility
- `columns` field type changes from `List[str]` to `Union[List[str], List[ColumnDef]]`.
- The existing `_normalize_table_data()` validator must be preserved and extended to handle `ColumnDef` objects.
- When `columns` is `List[str]`, behavior is identical to current. When `List[ColumnDef]`, the renderer uses width/align/color from each ColumnDef.

### JS Collection Pattern
- Define tab-switching and accordion-toggle JS as named string constants in the renderer module.
- Inject only the JS needed: tab JS only if TabViewBlock present, accordion JS only if AccordionBlock present.
- Each TabViewBlock instance gets a unique prefix (tv0, tv1, ...) to scope its JS/DOM IDs.

### Known Risks / Gotchas
- **LLM structured output reliability**: Multi-tab JSON is 15-25 KB. Larger payloads increase likelihood of malformed JSON from the LLM. The `_normalise_payload()` must be robust. Mitigation: thorough normalization and graceful fallbacks.
- **Forward reference ordering**: `AccordionItem` and `TabPane` must be defined before `InfographicBlock` union, with `model_rebuild()` called after. Incorrect ordering causes Pydantic errors.
- **Auto-detection latency**: The pre-pass LLM call adds ~1-3 seconds. Mitigation: use a short prompt with low max_tokens. Consider caching common question→template mappings in the future.

### External Dependencies
| Package | Version | Reason |
|---|---|---|
| `nh3` | `>=0.2.14` | HTML sanitization for AccordionItem.html_content (Rust-based, successor to bleach) |

---

## Worktree Strategy

- **Isolation**: `per-spec` — all tasks run sequentially in a single worktree.
- **Rationale**: Three core files (`infographic.py`, `infographic_templates.py`, `infographic_html.py`) are modified by nearly every task. Sequential execution avoids merge conflicts.
- **Cross-feature dependencies**: None. The infographic system is self-contained.
- **Worktree creation**:
  ```bash
  git worktree add -b feat-102-multi-tab-infographic \
    .claude/worktrees/feat-102-multi-tab-infographic HEAD
  ```

---

## 8. Open Questions

- [x] **Token budget for multi-tab**: Should `get_infographic()` increase `max_tokens` when using `multi_tab` template? — *Owner: Jesus*: set max_tokens to None (no limit).
- [x] **Tab icons**: Support emoji in tab labels (confirmed). Also support icon CSS classes, or emoji-only for v1? — *Owner: Jesus*: support icon css classes.
- [x] **Accordion ID generation**: Auto-generate IDs for AccordionItems using slugified title or UUID? — *Owner: Jesus*: uuid is safer.
- [x] **Auto-detection prompt wording**: Exact prompt for the template pre-pass LLM call. — *Owner: Jesus*: accept suggestions.
- [x] **nh3 allowlist**: Proposed tags: `p, br, strong, em, ul, ol, li, a[href], span, div, h3, h4, code, pre, table, tr, td, th, thead, tbody`. — *Owner: Jesus*: proposal accepted.

---

## Revision History

| Version | Date | Author | Change |
|---|---|---|---|
| 0.1 | 2026-04-15 | Jesus | Initial draft from brainstorm |
