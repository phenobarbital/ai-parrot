---
type: feature
base_branch: dev
reuse_feature_id: FEAT-301
---

# Feature Specification: Themed Component Catalog — HTML Renderer v2

**Feature ID**: FEAT-301
**Date**: 2026-08-19
**Author**: Jesus Lara
**Status**: draft
**Target version**: 0.26.x
**Proposal**: `sdd/proposals/infographic-theme-catalog-a2ui.proposal.md` (run 2, high confidence)
**Research state**: `sdd/state/FEAT-301/`

---

## 1. Motivation & Business Requirements

### Problem Statement

The infographic HTML renderer (`InfographicHTMLRenderer`) ships 15 block types
and 4 built-in themes but lacks the FieldSync design-system vocabulary needed
for technical documentation outputs: chain/flow diagrams, step-by-step guides,
code snippets with syntax hints, and card grid layouts. Additionally:

- **~20 literal CSS colors** in `BASE_CSS` break theme consistency (callout
  backgrounds, hover states, container whites, print styles).
- **`INFOGRAPHIC_SYSTEM_PROMPT`** documents only 12 of 15 existing blocks —
  `accordion`, `checklist`, `tab_view` are missing from the LLM's instruction
  set.
- **I18nText** (bilingual EN/ES) has no model support — block text fields are
  plain `str` with no locale dispatch.
- **Document chrome** (version bar, changelog pills, authorship footer) is
  absent from the renderer.
- **Dependencies** (`markdown-it-py`, `markupsafe`, `orjson`) are imported but
  not declared in `ai-parrot-visualizations/pyproject.toml`.

### Goals

1. Extend `BlockType` from 15 → 19 members (`chain`, `steps`, `code`,
   `card_grid`) with corresponding Pydantic models.
2. Introduce `ThemeConfig` v2 fields (code palette, method-badge palette,
   soft/surface/callout semantic tokens) and register a 5th built-in theme
   (`petrol`) matching the FieldSync design system.
3. Migrate all literal CSS colors in `BASE_CSS` to CSS custom properties.
4. Add `I18nText` union type (`str | Dict[str, str]`) for bilingual block
   content, with a client-side `setLang()` switcher.
5. Add document chrome (top bar with version/status pills, changelog sidebar,
   authorship footer) to the HTML renderer.
6. Add micro-syntax expansion (`[[chip:…]]`, `[[m:…]]`, `[[comp:…]]`) for
   inline semantic fragments.
7. Update `INFOGRAPHIC_SYSTEM_PROMPT` to document all 19 block types.
8. Extend the A2UI adapter `_Converter` with explicit mappings for the 4 new
   block types (currently they fall through to generic `_card_like()` → Card).
9. Declare undeclared runtime dependencies in `pyproject.toml`.

### Non-Goals (explicitly out of scope)

- **A2UI infrastructure** (envelope models, catalog registry, renderers,
  delivery bridges) — fully resolved by FEAT-273 (22 tasks, completed
  2026-07-11).
- **New A2UI catalog components** for the 4 new block types — v1 strategy is
  Card-based lowering with semantic `properties` hints; dedicated components
  are a separate follow-up.
- **Template system changes** — `InfographicTemplateRegistry` and
  `RecipeRunner` are block-agnostic and require no modifications.
- **Server/handler changes** — the render endpoint (FEAT-327) consumes
  `InfographicResponse` and delegates to the renderer; it is block-agnostic.

---

## 2. Architectural Design

### Overview

This feature extends two layers of the existing infographic pipeline:

1. **Model layer** (`parrot.models.infographic`): 4 new block models, I18nText
   type, DocumentMeta model, ThemeConfig v2 fields, petrol theme registration.
2. **Renderer layer** (`parrot.outputs.formats.infographic_html`): 4 new block
   renderers, CSS variable migration, document chrome, i18n span emitter,
   micro-syntax expander.
3. **Adapter layer** (`parrot.outputs.a2ui.adapters.infographic`): explicit
   `_Converter` methods for 4 new block types.

All changes are additive — new `Optional` fields with `None` defaults, new
enum members, new renderer methods. Zero breaking changes to existing payloads
or API surfaces.

### Component Diagram

```
                     ┌─────────────────────────────┐
                     │  parrot.models.infographic   │
                     │  ─────────────────────────── │
                     │  BlockType (15→19)           │
                     │  I18nText (NEW)              │
                     │  ChainBlock (NEW)            │
                     │  StepsBlock (NEW)            │
                     │  CodeBlock (NEW)             │
                     │  CardGridBlock (NEW)         │
                     │  DocumentMeta (NEW)          │
                     │  ThemeConfig v2 fields       │
                     │  petrol theme (5th)          │
                     │  InfographicResponse.doc_meta│
                     └───────────┬─────────────────┘
                                 │
                    ┌────────────┴────────────┐
                    │                         │
          ┌─────────▼──────────┐    ┌────────▼────────────────┐
          │ InfographicHTML    │    │ A2UI adapter             │
          │ Renderer           │    │ _Converter.walk()        │
          │ ──────────────     │    │ ────────────────         │
          │ 4 new renderers    │    │ 4 new explicit mappings  │
          │ CSS var migration  │    │ (Card-based lowering)    │
          │ Document chrome    │    └─────────────────────────┘
          │ I18n span emitter  │
          │ Micro-syntax       │
          └────────────────────┘
```

### Integration Points

| Existing Component | Integration Type | Notes |
|---|---|---|
| `BlockType` enum | extends | Add 4 members: `CHAIN`, `STEPS`, `CODE`, `CARD_GRID` |
| `InfographicBlock` union | extends | Add 4 new block models to the union |
| `InfographicResponse` | extends | Add `document_meta: Optional[DocumentMeta]` field |
| `ThemeConfig` | extends | Add Optional v2 fields (CodePalette, etc.) |
| `ThemeRegistry` / `theme_registry` | uses | Register `petrol` theme |
| `_BLOCK_MODEL_MAP` | extends | Add 4 entries for new block types |
| `_block_renderers` dict | extends | Add 4 renderer methods |
| `BASE_CSS` | modifies | Migrate ~20 literal colors → `var(--…)` |
| `INFOGRAPHIC_SYSTEM_PROMPT` | modifies | Document all 19 block types |
| `_Converter.walk()` | extends | Add dispatch branches for 4 new types |
| `_Converter._card_like()` | extends | Add Card-lowering logic for new types |
| `ai-parrot-visualizations/pyproject.toml` | modifies | Declare missing deps |

### Data Models

```python
# New types in parrot/models/infographic.py

I18nText = Union[str, Dict[str, str]]
"""Bilingual text: plain ``str`` for single-language, or
``{"en": "...", "es": "..."}`` for locale dispatch."""

class ChainBlock(BaseModel):
    """Flow/chain diagram block — sequential process with labeled nodes."""
    type: Literal["chain"] = "chain"
    title: Optional[I18nText] = None
    nodes: List[ChainNode]                # NEW model
    direction: Literal["horizontal", "vertical"] = "horizontal"

class StepsBlock(BaseModel):
    """Step-by-step guide with numbered/labeled stages."""
    type: Literal["steps"] = "steps"
    title: Optional[I18nText] = None
    steps: List[StepItem]                 # NEW model
    style: Literal["numbered", "icon"] = "numbered"

class CodeBlock(BaseModel):
    """Code snippet block with optional language hint and line highlights."""
    type: Literal["code"] = "code"
    title: Optional[I18nText] = None
    code: str
    language: Optional[str] = None
    highlight_lines: Optional[List[int]] = None

class CardGridBlock(BaseModel):
    """Grid of cards (e.g., feature comparison, team roster)."""
    type: Literal["card_grid"] = "card_grid"
    title: Optional[I18nText] = None
    cards: List[GridCard]                 # NEW model
    columns: int = Field(default=3, ge=1, le=6)

class DocumentMeta(BaseModel):
    """Top-level document metadata for chrome rendering."""
    version: Optional[str] = None
    status: Optional[str] = None
    author: Optional[str] = None
    changelog: Optional[List[ChangelogEntry]] = None

class ChangelogEntry(BaseModel):
    """Single changelog entry."""
    version: str
    date: str
    summary: I18nText
```

### New Public Interfaces

```python
# ThemeConfig v2 additions (parrot/models/infographic.py)
class CodePalette(BaseModel):
    """Syntax-highlight token colors for CodeBlock rendering."""
    keyword: str = Field("#c678dd")
    string: str = Field("#98c379")
    comment: str = Field("#5c6370")
    number: str = Field("#d19a66")
    function: str = Field("#61afef")
    background: str = Field("#282c34")
    text: str = Field("#abb2bf")

class MethodBadgePalette(BaseModel):
    """Color tokens for HTTP method badges in micro-syntax."""
    get: str = Field("#10b981")
    post: str = Field("#6366f1")
    put: str = Field("#f59e0b")
    delete: str = Field("#ef4444")
    patch: str = Field("#8b5cf6")

# New Optional fields on ThemeConfig:
#   code_palette: Optional[CodePalette] = None
#   method_badge_palette: Optional[MethodBadgePalette] = None
#   surface_bg: Optional[str] = None         # card surface (default: derives from neutral_bg)
#   soft_primary: Optional[str] = None       # pill/chip tinted bg (derives from primary)
#   callout_info_bg: Optional[str] = None    # info callout background
#   callout_success_bg: Optional[str] = None
#   callout_warning_bg: Optional[str] = None
#   callout_error_bg: Optional[str] = None
#   callout_tip_bg: Optional[str] = None

# derive_soft() helper:
def derive_soft(hex_color: str, alpha: float = 0.12) -> str:
    """Derive a soft/tinted background from a hex color.

    Used for pill backgrounds, chip tints, callout backgrounds.
    """
```

---

## 3. Module Breakdown

### Module 1: Block Models & I18nText (`infographic.py`)

- **Path**: `packages/ai-parrot/src/parrot/models/infographic.py`
- **Responsibility**: Add 4 new block types + supporting models, I18nText
  union, DocumentMeta, ChangelogEntry. Update `InfographicBlock` union and
  `InfographicResponse` with `document_meta`.
- **Depends on**: None (foundation module)
- **Changes**:
  - Add `BlockType.CHAIN`, `STEPS`, `CODE`, `CARD_GRID` to enum (after line 87)
  - Add `I18nText = Union[str, Dict[str, str]]` type alias
  - Add `ChainNode`, `StepItem`, `GridCard` support models
  - Add `ChainBlock`, `StepsBlock`, `CodeBlock`, `CardGridBlock` models
  - Add `ChangelogEntry`, `DocumentMeta` models
  - Add `InfographicResponse.document_meta: Optional[DocumentMeta] = None`
  - Extend `InfographicBlock` union (line 825) with 4 new types
  - Update `__init__.py` exports (line 24)

### Module 2: ThemeConfig v2 + Petrol Theme (`infographic.py`)

- **Path**: `packages/ai-parrot/src/parrot/models/infographic.py`
- **Responsibility**: Add v2 semantic tokens to ThemeConfig, `derive_soft()`
  helper, extend `to_css_variables()`, register `petrol` built-in theme.
- **Depends on**: None (can be built in parallel with Module 1)
- **Changes**:
  - Add `CodePalette`, `MethodBadgePalette` sub-models (before ThemeConfig)
  - Add Optional v2 fields to `ThemeConfig` (after line 1055)
  - Add `derive_soft()` module-level helper
  - Extend `to_css_variables()` to emit v2 tokens when present
  - Register `petrol` theme after `midnight` (after line 1228)

### Module 3: HTML Block Renderers + Chrome + I18n (`infographic_html.py`)

- **Path**: `packages/ai-parrot-visualizations/src/parrot/outputs/formats/infographic_html.py`
- **Responsibility**: Add 4 new `_render_*` methods, micro-syntax expander,
  document chrome (top bar, changelog, footer), I18n span emitter + `setLang()` JS.
- **Depends on**: Module 1 (new block models), Module 2 (v2 theme tokens)
- **Changes**:
  - Add imports for 4 new block models
  - Add 4 entries to `_BLOCK_MODEL_MAP` (after line 84)
  - Add 4 entries to `_block_renderers` dict (after line 690)
  - Add `_render_chain()`, `_render_steps()`, `_render_code()`, `_render_card_grid()` methods
  - Add `_expand_microsyntax(text)` helper (chip, method-badge, component-ref)
  - Add `_render_document_chrome()` for top bar + changelog
  - Add `_render_i18n_span(text)` for `I18nText` locale dispatch
  - Add `setLang()` JavaScript snippet to `_build_interaction_js()`

### Module 4: CSS Variable Migration (`infographic_html.py`)

- **Path**: `packages/ai-parrot-visualizations/src/parrot/outputs/formats/infographic_html.py`
- **Responsibility**: Replace ~20 literal CSS hex colors in `BASE_CSS` with
  CSS custom properties, using ThemeConfig v2 tokens where applicable.
- **Depends on**: Module 2 (v2 callout/surface tokens must exist)
- **Changes**:
  - Replace `white` / `#fff` → `var(--neutral-bg)` or `var(--surface-bg)` (lines 165, 216, 243, 263)
  - Replace callout `background` colors → `var(--callout-info-bg)`, etc. (lines 346–369)
  - Replace `tr:hover` background → `var(--neutral-border)` or similar (line 274)
  - Replace `box-shadow` rgba → `var(--shadow-color)` or keep as-is (opacity-based, theme-safe)
  - Replace callout `h3` colors → `var(--callout-*-text)` tokens (lines 354, 359, 364, 369)
  - Replace print-style colors appropriately (lines 486–489)
  - Add new CSS custom properties to `to_css_variables()` for v2 tokens

### Module 5: System Prompt Update (`infographic.py` — prompt file)

- **Path**: `packages/ai-parrot-visualizations/src/parrot/outputs/formats/infographic.py`
- **Responsibility**: Update `INFOGRAPHIC_SYSTEM_PROMPT` to document all 19
  block types (currently only 12).
- **Depends on**: Module 1 (must know final block type names and fields)
- **Changes**:
  - Add `accordion`, `checklist`, `tab_view` to the existing block list (lines 22–33)
  - Add `chain`, `steps`, `code`, `card_grid` with field descriptions
  - Add I18nText convention documentation
  - Add `document_meta` field documentation

### Module 6: A2UI Adapter Extension (`adapters/infographic.py`)

- **Path**: `packages/ai-parrot/src/parrot/outputs/a2ui/adapters/infographic.py`
- **Responsibility**: Add explicit `_Converter` methods for 4 new block types
  so they produce semantically richer Card components instead of the generic
  `_card_like()` fallback.
- **Depends on**: Module 1 (block model definitions)
- **Changes**:
  - Add `_chain()`, `_steps()`, `_code()`, `_card_grid()` methods to `_Converter`
  - Update `walk()` dispatch (after line 410) with 4 new branches before the
    `else: _card_like()` fallback
  - Each method produces a `Card` descriptor with semantic `properties`
    (e.g., `code` → Card with `body` as fenced code block, `badge: language`)

### Module 7: Dependency Declaration (`pyproject.toml`)

- **Path**: `packages/ai-parrot-visualizations/pyproject.toml`
- **Responsibility**: Declare `markdown-it-py`, `markupsafe`, `orjson` as
  explicit dependencies.
- **Depends on**: None
- **Changes**:
  - Add to `dependencies` list (after line 29):
    ```
    "markdown-it-py>=3.0",
    "markupsafe>=2.1",
    "orjson>=3.9",
    ```

---

## 4. Test Specification

### Unit Tests

| Test | Module | Description |
|---|---|---|
| `test_block_type_enum_19_members` | 1 | BlockType has exactly 19 members after extension |
| `test_chain_block_model` | 1 | ChainBlock validates with nodes + direction |
| `test_steps_block_model` | 1 | StepsBlock validates with steps + style |
| `test_code_block_model` | 1 | CodeBlock validates with code + language + highlight_lines |
| `test_card_grid_block_model` | 1 | CardGridBlock validates with cards + columns constraint |
| `test_i18n_text_plain_str` | 1 | I18nText accepts plain str |
| `test_i18n_text_dict` | 1 | I18nText accepts `{"en": "...", "es": "..."}` |
| `test_document_meta_optional` | 1 | InfographicResponse with `document_meta=None` validates |
| `test_document_meta_populated` | 1 | InfographicResponse with full DocumentMeta validates |
| `test_infographic_response_backward_compat` | 1 | Existing payloads (15 block types) still validate |
| `test_theme_config_v2_backward_compat` | 2 | ThemeConfig with only v1 fields still validates |
| `test_theme_config_v2_fields` | 2 | ThemeConfig with CodePalette + v2 tokens validates |
| `test_derive_soft` | 2 | `derive_soft("#6366f1", 0.12)` returns valid rgba |
| `test_to_css_variables_v2` | 2 | `to_css_variables()` emits v2 tokens when present |
| `test_petrol_theme_registered` | 2 | `theme_registry.get("petrol")` succeeds |
| `test_theme_count_five` | 2 | `theme_registry.list_themes()` returns 5 themes |
| `test_render_chain_block` | 3 | `_render_chain()` produces valid HTML |
| `test_render_steps_block` | 3 | `_render_steps()` produces valid HTML |
| `test_render_code_block` | 3 | `_render_code()` produces valid HTML with language class |
| `test_render_card_grid_block` | 3 | `_render_card_grid()` produces valid HTML grid |
| `test_microsyntax_chip` | 3 | `[[chip:Active]]` expands to chip span |
| `test_microsyntax_method_badge` | 3 | `[[m:GET]]` expands to method badge |
| `test_microsyntax_component` | 3 | `[[comp:AgentCrew]]` expands to component link |
| `test_document_chrome` | 3 | Document chrome renders with version pill + changelog |
| `test_i18n_span_emitter` | 3 | `I18nText` dict renders as dual `<span lang="…">` |
| `test_no_literal_colors_in_base_css` | 4 | `BASE_CSS` contains zero literal hex/named colors outside `var()` |
| `test_callout_colors_use_variables` | 4 | Callout backgrounds reference `var(--callout-*)` |
| `test_system_prompt_19_blocks` | 5 | INFOGRAPHIC_SYSTEM_PROMPT mentions all 19 block types |
| `test_system_prompt_i18n` | 5 | INFOGRAPHIC_SYSTEM_PROMPT documents I18nText convention |
| `test_a2ui_chain_to_card` | 6 | `_Converter` maps chain block to Card with semantic props |
| `test_a2ui_steps_to_card` | 6 | `_Converter` maps steps block to Card with numbered body |
| `test_a2ui_code_to_card` | 6 | `_Converter` maps code block to Card with badge=language |
| `test_a2ui_card_grid_to_cards` | 6 | `_Converter` maps card_grid to multiple Card descriptors |

### Integration Tests

| Test | Description |
|---|---|
| `test_render_all_19_block_types` | Full `render_to_html()` with a payload containing all 19 block types |
| `test_render_petrol_theme` | Full render with `theme="petrol"` produces valid HTML |
| `test_render_i18n_bilingual` | Full render with I18nText fields + `setLang()` JS present |
| `test_a2ui_envelope_new_blocks` | `infographic_response_to_envelope()` handles all 19 block types |
| `test_backward_compat_existing_payload` | Existing 15-block payloads render identically before/after |

### Test Data / Fixtures

```python
@pytest.fixture
def all_blocks_payload():
    """InfographicResponse dict with all 19 block types."""
    return {
        "theme": "petrol",
        "blocks": [
            {"type": "title", "title": "Test Infographic"},
            {"type": "hero_card", "label": "Metric", "value": "42"},
            {"type": "summary", "content": "Summary text"},
            {"type": "chart", "chart_type": "bar", "labels": ["A"], "series": [{"name": "s", "values": [1]}]},
            {"type": "bullet_list", "items": ["item 1"]},
            {"type": "table", "columns": ["A"], "rows": [["1"]]},
            {"type": "image", "url": "data:image/png;base64,AA==", "alt": "img"},
            {"type": "quote", "text": "Quote", "author": "Author"},
            {"type": "callout", "level": "info", "content": "Info"},
            {"type": "divider"},
            {"type": "timeline", "events": [{"date": "2026-01-01", "title": "Event"}]},
            {"type": "progress", "items": [{"label": "Task", "value": "80%"}]},
            {"type": "accordion", "items": [{"title": "Section", "content_blocks": []}]},
            {"type": "checklist", "items": [{"text": "Done", "checked": True}]},
            {"type": "tab_view", "tabs": [{"label": "Tab1", "blocks": []}]},
            # NEW blocks:
            {"type": "chain", "nodes": [{"label": "A"}, {"label": "B"}]},
            {"type": "steps", "steps": [{"label": "Step 1", "description": "Do thing"}]},
            {"type": "code", "code": "print('hello')", "language": "python"},
            {"type": "card_grid", "cards": [{"title": "Card 1", "body": "Content"}], "columns": 2},
        ],
    }

@pytest.fixture
def petrol_theme_config():
    """ThemeConfig for the petrol theme (expected values)."""
    from parrot.models.infographic import theme_registry
    return theme_registry.get("petrol")
```

---

## 5. Acceptance Criteria

- [x] All unit tests pass: `pytest tests/models/test_infographic*.py -v`
- [x] All integration tests pass: `pytest tests/outputs/test_infographic*.py -v`
- [ ] `BlockType` enum has exactly 19 members
- [ ] `ThemeConfig` v2 fields are Optional with None defaults (backward-compatible)
- [ ] `petrol` theme is the 5th registered built-in theme
- [ ] `to_css_variables()` emits v2 tokens when present, omits them when None
- [ ] `I18nText` accepts both `str` and `Dict[str, str]` (Pydantic Union)
- [ ] `InfographicResponse.document_meta` is Optional, defaults to None
- [ ] All 4 new block renderers produce valid, self-contained HTML
- [ ] `BASE_CSS` contains zero literal hex/named colors outside `var()` refs
  (excluding print styles where `!important` literal overrides are acceptable)
- [ ] `INFOGRAPHIC_SYSTEM_PROMPT` documents all 19 block types
- [ ] A2UI adapter `_Converter.walk()` has explicit branches for all 4 new types
- [ ] Micro-syntax `[[chip:…]]`, `[[m:…]]`, `[[comp:…]]` expand in summary/text blocks
- [ ] Document chrome renders when `document_meta` is populated
- [ ] I18n `<span lang="…">` elements render for `Dict` I18nText values
- [ ] `setLang()` JS function toggles visibility by `lang` attribute
- [ ] `markdown-it-py`, `markupsafe`, `orjson` declared in `pyproject.toml`
- [ ] Existing 15-block payloads render identically (visual regression check)
- [ ] No breaking changes to existing public API
- [ ] No new `frozen=True` or `extra="forbid"` on block models (convention match)

---

## 6. Codebase Contract

> **CRITICAL — Anti-Hallucination Anchor**
> This section is the single source of truth for what exists in the codebase.
> Implementation agents MUST NOT reference imports, attributes, or methods
> not listed here without first verifying they exist via `grep` or `read`.

### Verified Imports

```python
# parrot/models/infographic.py — verified at packages/ai-parrot/src/parrot/models/infographic.py
from typing import List, Optional, Any, Annotated, ClassVar, Dict, Literal, Tuple, Union  # line 25
from enum import Enum                     # line 38
from pydantic import BaseModel, Discriminator, Field, field_validator, model_validator  # line 39

# parrot/models/__init__.py — verified exports (line 24-49)
from parrot.models.infographic import (
    BlockType, ChartType, TrendDirection, CalloutLevel,
    InfographicBlock, InfographicResponse,
    TitleBlock, HeroCardBlock, SummaryBlock, ChartBlock, ChartDataSeries,
    BulletListBlock, TableBlock, ImageBlock, QuoteBlock, CalloutBlock,
    DividerBlock, TimelineBlock, TimelineEvent, ProgressBlock, ProgressItem,
    ThemeConfig, ThemeRegistry, theme_registry,
)
# NOTE: AccordionBlock, ChecklistBlock, TabViewBlock are NOT in __init__.py exports.
# They are imported directly in infographic_html.py (line 53-59).

# infographic_html.py — verified at packages/ai-parrot-visualizations/.../infographic_html.py
import markdown_it                        # line 15
import orjson                             # line 16
from markupsafe import escape             # line 17
from pydantic import ValidationError      # line 18
from .base import BaseRenderer            # line 27
from . import register_renderer           # line 28
from ...models.outputs import OutputMode  # line 29
from ...models.infographic import (       # lines 30-60
    BlockType, BulletListBlock, BulletListStyle, CalloutBlock, CalloutLevel,
    ChartBlock, ChartDataSeries, ChartType, ColumnDef, DividerBlock,
    HeroCardBlock, ImageBlock, InfographicResponse, ProgressBlock,
    QuoteBlock, SummaryBlock, TableBlock, TableStyle, TimelineBlock,
    TitleBlock, TrendDirection, ThemeConfig, theme_registry,
    AccordionBlock, AccordionItem, ChecklistBlock, ChecklistItem,
    TabViewBlock, TabPane,
)

# A2UI adapter — verified at packages/ai-parrot/src/parrot/outputs/a2ui/adapters/infographic.py
from parrot.outputs.a2ui.builders import build_infographic  # line 66
from parrot.outputs.a2ui.models import CreateSurface        # line 67
```

### Existing Class Signatures

```python
# packages/ai-parrot/src/parrot/models/infographic.py

class BlockType(str, Enum):                         # line 71
    TITLE = "title"                                 # line 73
    HERO_CARD = "hero_card"                         # line 74
    # ... 13 more members ...
    TAB_VIEW = "tab_view"                           # line 87

_CSS_COLOR_RE = re.compile(...)                     # line 46-50 — validates hex/rgb/hsl/named/var()

class ThemeConfig(BaseModel):                       # line 1033
    name: str                                       # line 1040
    primary: str = Field("#6366f1")                 # line 1041
    primary_dark: str = Field("#4f46e5")            # line 1042
    primary_light: str = Field("#818cf8")           # line 1043
    accent_green: str = Field("#10b981")            # line 1044
    accent_amber: str = Field("#f59e0b")            # line 1045
    accent_red: str = Field("#ef4444")              # line 1046
    neutral_bg: str = Field("#f8fafc")              # line 1047
    neutral_border: str = Field("#e2e8f0")          # line 1048
    neutral_muted: str = Field("#64748b")           # line 1049
    neutral_text: str = Field("#0f172a")            # line 1050
    body_bg: str = Field("#f1f5f9")                 # line 1051
    font_family: str = Field(...)                   # line 1052-1055
    def to_css_variables(self) -> str:              # line 1075
    @field_validator(..., mode="before")            # line 1058-1063
    def _validate_color_fields(cls, v) -> Any:      # line 1066

class ThemeRegistry:                                # line 1098
    _themes: Dict[str, ThemeConfig]                 # line 1106
    def register(self, theme: ThemeConfig) -> None: # line 1108
    def get(self, name: str) -> ThemeConfig:        # line 1116
    def list_themes(self) -> List[str]:             # line 1135
    def list_themes_detailed(self) -> List[Dict]:   # line 1143

theme_registry = ThemeRegistry()                    # line 1162
# 4 built-in themes registered: light(1166), dark(1181), corporate(1196), midnight(1211)

class InfographicResponse(BaseModel):               # line 848
    template: Optional[str] = None                  # line 854
    theme: Optional[str] = None                     # line 858
    blocks: List[Annotated[InfographicBlock, Discriminator("type")]]  # line 862
    metadata: Optional[Dict[str, Any]] = Field(default_factory=dict)  # line 866

InfographicBlock = Union[TitleBlock, ..., TabViewBlock]  # lines 825-841
# model_rebuild() called on AccordionItem, TabPane, InfographicResponse  # lines 933-935
```

```python
# packages/ai-parrot-visualizations/src/parrot/outputs/formats/infographic_html.py

_BLOCK_MODEL_MAP: Dict[str, Any] = {               # line 69-85
    "title": TitleBlock,
    "hero_card": HeroCardBlock,
    # ... 13 entries total for 15 block types (checklist, accordion, tab_view included)
}

BASE_CSS = """..."""                                 # lines 153-617 (large string literal)
# Literal colors found (must migrate):
#   line 165: background: white;
#   line 168: box-shadow rgba(0,0,0,0.05)
#   line 172: color: #fff;
#   line 216: background: #fff;
#   line 220: box-shadow rgba(0,0,0,0.06)
#   line 243: background: #fff;
#   line 263: color: #fff;
#   line 274: tr:hover { background: #f1f5f9; }
#   lines 346-369: callout .info/.success/.warning/.error/.tip backgrounds + h3 colors
#   lines 486-489: @media print overrides
#   line 574: color: #fff; (timeline badge)

@register_renderer(OutputMode.INFOGRAPHIC)
class InfographicHTMLRenderer(BaseRenderer):        # line 656
    _md: markdown_it.MarkdownIt                     # line 669
    _tab_view_counter: int                          # line 670
    _theme_cfg: Optional[ThemeConfig]               # line 674
    _block_renderers: Dict[str, Any]                # line 675-691 (15 entries)

    async def render(self, response, ...) -> Tuple[str, Optional[Any]]:  # line 695
    def render_to_html(self, data, theme=None) -> str:                   # line 724
    def _assemble_document(self, page_title, theme_css, blocks_html, ...) -> str:  # line 794
    def _render_blocks(self, data) -> str:          # (iterates blocks, calls _block_renderers)
    def _build_interaction_js(self, data) -> str:   # (accordion/tab JS)
```

```python
# packages/ai-parrot/src/parrot/outputs/a2ui/adapters/infographic.py

CHART_TYPE_MAP: dict[str, str] = {                  # line 76-89 (12 entries)
    "bar": "bar", "line": "line", ..., "gauge": "bar"
}

class _Converter:                                   # line 188
    data_model: dict[str, dict[str, Any]]           # line 192
    def _chart(self, block) -> dict:                # line 204
    def _table(self, block) -> dict:                # line 236
    def _hero_card(self, block) -> dict:            # line 261
    def _timeline(self, block) -> dict:             # line 272
    def _progress(self, block) -> list[dict]:       # line 287
    def _card_like(self, block, block_type) -> dict:  # line 299
    def walk(self, blocks, sections, *, depth=0, seen_title=False):  # line 357
        # Walk dispatch (line 400-412):
        #   chart → _chart, table → _table, hero_card → _hero_card,
        #   timeline → _timeline, progress → _progress, else → _card_like
    def _flatten_container(self, block, block_type, sections, depth):  # line 416

def infographic_response_to_envelope(               # line 447
    response, *, surface_id="infographic",
    title=None, theme=None,
) -> CreateSurface:

# packages/ai-parrot/src/parrot/outputs/a2ui/builders.py
def build_infographic(                              # line 151
    *, title, sections, subtitle=None,
    theme=None, surface_id="infographic",
    data_model=None,
) -> CreateSurface:
```

```python
# packages/ai-parrot-visualizations/src/parrot/outputs/formats/infographic.py

INFOGRAPHIC_SYSTEM_PROMPT = """..."""                # lines 16-46
# Documents 12 blocks: title, hero_card, summary, chart, bullet_list,
# table, image, quote, callout, divider, timeline, progress.
# MISSING: accordion, checklist, tab_view (3 existing), plus 4 new.

def extract_infographic_data(response) -> dict:     # line 49
```

### Integration Points

| New Component | Connects To | Via | Verified At |
|---|---|---|---|
| `ChainBlock` model | `InfographicBlock` union | Union member | `infographic.py:825` |
| `StepsBlock` model | `InfographicBlock` union | Union member | `infographic.py:825` |
| `CodeBlock` model | `InfographicBlock` union | Union member | `infographic.py:825` |
| `CardGridBlock` model | `InfographicBlock` union | Union member | `infographic.py:825` |
| `DocumentMeta` model | `InfographicResponse.document_meta` | Optional field | `infographic.py:848` |
| `CodePalette` | `ThemeConfig.code_palette` | Optional field | `infographic.py:1033` |
| `MethodBadgePalette` | `ThemeConfig.method_badge_palette` | Optional field | `infographic.py:1033` |
| `_render_chain()` | `_block_renderers["chain"]` | dict entry | `infographic_html.py:675` |
| `_render_steps()` | `_block_renderers["steps"]` | dict entry | `infographic_html.py:675` |
| `_render_code()` | `_block_renderers["code"]` | dict entry | `infographic_html.py:675` |
| `_render_card_grid()` | `_block_renderers["card_grid"]` | dict entry | `infographic_html.py:675` |
| `_Converter._chain()` | `_Converter.walk()` dispatch | elif branch | `adapters/infographic.py:400` |
| `petrol` theme | `theme_registry.register()` | call | `infographic.py:1162` |

### Does NOT Exist (Anti-Hallucination)

- ~~`parrot.models.infographic.I18nText`~~ — does not exist yet; must be created
- ~~`parrot.models.infographic.ChainBlock`~~ — does not exist; must be created
- ~~`parrot.models.infographic.StepsBlock`~~ — does not exist; must be created
- ~~`parrot.models.infographic.CodeBlock`~~ — does not exist; must be created
- ~~`parrot.models.infographic.CardGridBlock`~~ — does not exist; must be created
- ~~`parrot.models.infographic.DocumentMeta`~~ — does not exist; must be created
- ~~`parrot.models.infographic.ChangelogEntry`~~ — does not exist; must be created
- ~~`parrot.models.infographic.CodePalette`~~ — does not exist; must be created
- ~~`parrot.models.infographic.MethodBadgePalette`~~ — does not exist; must be created
- ~~`parrot.models.infographic.derive_soft()`~~ — does not exist; must be created
- ~~`InfographicResponse.document_meta`~~ — field does not exist yet
- ~~`ThemeConfig.code_palette`~~ — field does not exist yet
- ~~`ThemeConfig.surface_bg`~~ — field does not exist yet
- ~~`ThemeConfig.soft_primary`~~ — field does not exist yet
- ~~`ThemeConfig.callout_info_bg`~~ — field does not exist yet
- ~~`_Converter._chain()`~~ — method does not exist; walk() falls through to `_card_like()` for unknown types
- ~~`AccordionBlock` in `parrot.models.__init__`~~ — not re-exported; import directly from `parrot.models.infographic`
- ~~`InfographicHTMLRenderer._render_chain()`~~ — does not exist; must be created
- ~~`theme_registry.get("petrol")`~~ — raises KeyError; theme must be registered
- ~~`BASE_CSS` uses `var(--callout-info-bg)`~~ — literal hex colors, not variables

---

## 7. Implementation Notes & Constraints

### Patterns to Follow

- **Block model convention**: plain `BaseModel` — no `frozen=True`, no
  `extra="forbid"`. Follow `TitleBlock`/`HeroCardBlock` patterns. [F108, F003]
- **Discriminator pattern**: each block model must have
  `type: Literal["<value>"] = "<value>"` as its first field — the
  `Discriminator("type")` on `InfographicBlock` requires it.
- **I18nText widening**: use `Union[str, Dict[str, str]]` — Pydantic v2
  accepts plain `str` through the union automatically, so existing payloads
  remain valid without changes.
- **CSS variable naming**: follow the existing `--primary` / `--neutral-*`
  kebab-case convention. New v2 tokens: `--code-bg`, `--code-text`,
  `--badge-get`, `--surface-bg`, `--soft-primary`, `--callout-info-bg`, etc.
- **Renderer method naming**: `_render_{block_type}(self, block) -> str`
  matching the existing pattern.
- **A2UI adapter pattern**: each `_Converter` method returns a
  `_descriptor("Card", {...})` dict. Follow `_hero_card()` / `_timeline()`
  patterns for the call signature.
- **`_validate_color_fields` validator**: add new color fields to the
  `@field_validator(...)` decorator list on ThemeConfig (line 1058-1063).
- **model_rebuild()**: after extending `InfographicBlock` union, the existing
  `model_rebuild()` calls on line 933-935 will pick up the new types
  automatically.
- **Escape policy**: all user-facing text goes through `markupsafe.escape()`
  before insertion into HTML templates. Micro-syntax expansion happens AFTER
  escape, so `[[chip:…]]` markers are post-processed on already-safe content.

### Known Risks / Gotchas

1. **`__init__.py` exports must be updated**: `AccordionBlock`, `ChecklistBlock`,
   `TabViewBlock` are already missing from `parrot/models/__init__.py` exports
   (line 24-49). The 4 new block models should be added, along with the 3
   missing ones (or the import pattern in `infographic_html.py` kept as-is,
   importing directly from the module).
2. **`to_css_variables()` backward compat**: v2 tokens must be emitted
   conditionally — only when the field is not None — so existing themes that
   don't specify them still produce valid CSS.
3. **Print styles**: `@media print` rules (lines 486-489) use `!important`
   overrides with literal colors (`white`, `#eee`, `black`, `#ccc`). These
   are intentional for print rendering and may remain as literals, or be
   migrated to separate print-specific tokens.
4. **`box-shadow` rgba**: the `rgba(0,0,0,0.05)` / `rgba(0,0,0,0.06)` values
   are opacity-based and theme-safe (black shadow at low opacity works on any
   background). These can remain as-is or be tokenized as `--shadow-light`.
5. **I18nText and nested blocks**: `AccordionItem.content_blocks` and
   `TabPane.blocks` use `List[Any]` — I18nText fields on nested blocks will
   work naturally since Pydantic validates them at construction time, not at
   nesting time.

### External Dependencies

| Package | Version | Reason |
|---|---|---|
| `markdown-it-py` | `>=3.0` | Markdown rendering in summary/text blocks (already used, undeclared) |
| `markupsafe` | `>=2.1` | HTML escaping (already used, undeclared) |
| `orjson` | `>=3.9` | Fast JSON serialization (already used, undeclared) |

---

## 8. Open Questions

> All questions from the proposal (run 1 + run 2) have been resolved.

### Resolved by Research

- [x] **Does FEAT-273 conflict with WS-C?** — *Resolved in proposal*: No — FEAT-273 **resolved** WS-C entirely. WS-C is out of scope. [F107]
- [x] **Do existing block models use `frozen=True`?** — *Resolved in proposal*: No. Plain `BaseModel` throughout — convention confirmed. [F108]
- [x] **How many built-in themes exist?** — *Resolved in proposal*: 4 (light, dark, corporate, midnight). Petrol will be the 5th. [F108]
- [x] **Are downstream consumers block-aware?** — *Resolved in proposal*: Only 3 of 8 need changes (HTML renderer, system prompt, A2UI adapter). [F100-F103]
- [x] **Has infographic.py changed since the original proposal?** — *Resolved in proposal*: Zero commits since 2026-07-10. Extension surface is pristine. [F108]
- [x] **Are dependencies declared?** — *Resolved in proposal*: No. `markdown-it-py`, `markupsafe`, `orjson` are missing. [F106]

### Resolved by Human Decision

- [x] **WS-C scope** — *Resolved in run-1*: WS-C deferred → subsequently resolved by FEAT-273. Excluded from this spec.
- [x] **Migrate existing literal CSS colors** — *Resolved in run-1*: Confirmed — migrate ~20 literal colors to CSS variables.
- [x] **Document all blocks in system prompt** — *Resolved in run-1*: Confirmed — all 19 blocks must be in the prompt.
- [x] **Include A2UI adapter extension in FEAT-301** — *Resolved in run-2*: Yes, include as a task (Module 6).
- [x] **I18nText still wanted** — *Resolved in run-2*: Yes, bilingual EN/ES confirmed (Module 1 + Module 3).

---

## Worktree Strategy

- **Isolation**: `per-spec` — all tasks run sequentially in one worktree.
- **Rationale**: Modules 1-6 are tightly coupled (Module 3-6 all depend on
  Module 1/2). Sequential execution avoids merge conflicts on `infographic.py`
  and `infographic_html.py`.
- **Cross-feature dependencies**: None — `infographic.py` has had zero
  commits since 2026-07-10 and no active feature targets it.
- **Recommended worktree name**: `feat-301-infographic-theme-catalog`

```bash
git checkout dev && git pull --ff-only origin dev
git worktree add -b feat-301-infographic-theme-catalog \
  .claude/worktrees/feat-301-infographic-theme-catalog HEAD
```

---

## Revision History

| Version | Date | Author | Change |
|---|---|---|---|
| 0.1 | 2026-08-19 | Jesus Lara (via Claude) | Initial spec from run-2 proposal (FEAT-301) |
