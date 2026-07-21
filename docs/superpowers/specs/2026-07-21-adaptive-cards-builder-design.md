# Unified Adaptive Cards Builder — Design Spec

**Date**: 2026-07-21
**Status**: Approved
**Scope**: Consolidate all five Adaptive Card building systems into a shared, Pydantic-first card builder at `parrot/outputs/cards/`, upgrade to AC 1.5, add native Table and Action.ToggleVisibility support.

---

## Problem

AI-Parrot has five independent systems that produce Adaptive Card JSON, each building raw dicts inline with duplicated element construction logic:

| # | Module | AC Version | Input Model | Purpose |
|---|--------|-----------|-------------|---------|
| 1 | `msteams/wrapper.py` `_build_adaptive_card` | 1.4 | `ParsedResponse` | Rich output cards (markdown, tables, charts, images) |
| 2 | `msagentsdk/cards.py` | 1.4 | `SemanticUIResult` | Typed semantic cards (table, metrics, detail, status + actions) |
| 3 | `a2ui_renderers/adaptive_cards.py` | 1.5 | A2UI `CreateSurface` (lowered Basic tree) | Display-only cards from A2UI component tree |
| 4 | `forms/renderers/adaptive_card.py` | 1.5 | `FormSchema` | Input collection cards (forms, wizards, summaries) |
| 5 | `msteams/hitl_cards.py` | 1.5 | `HumanInteraction` | HITL approval/form cards |

This duplication means:
- Tables are built three different ways (ColumnSet in #1, ColumnSet in #2, ColumnSet in #3) — none using the native AC 1.5 `Table` element.
- No system supports `Action.ToggleVisibility` for collapsible sections.
- AC version is inconsistent (1.4 vs 1.5).
- Markdown-to-table parsing logic is duplicated and locked inside `msteams/wrapper.py`.
- Adding a new AC element type requires changes across multiple modules.

## Solution

A shared **Element Toolkit with Composable Sections** at `parrot/outputs/cards/`:

- **Elements layer**: Pydantic models mapping 1:1 to AC 1.5 elements (TextBlock, Table, Image, Container, Input.*, Action.*, etc.)
- **Sections layer**: Semantic groupings (TableSection, MetricsSection, FormSection, ToggleSection, etc.) that express intent without AC implementation details.
- **CardSpec**: Top-level model — title + sections + actions + auto-collapse policy.
- **Renderer**: Pure function `render(CardSpec) -> dict` that walks sections → elements → AC 1.5 JSON.

Each existing consumer keeps its public API unchanged and migrates internals to build `CardSpec` instances instead of raw dicts.

## Design Decisions

| Decision | Choice | Rationale |
|----------|--------|-----------|
| Package location | `parrot/outputs/cards/` in `ai-parrot` core | All packages depend on core; consistent with `parrot/outputs/` namespace |
| AC version | 1.5 universally | Teams and Copilot support 1.5; no YAGNI fallback to older versions |
| Table element | Native AC 1.5 `Table` | Cleaner than ColumnSet hacks; proper header/grid support |
| API style | Declarative Pydantic models | Consistent with codebase (SemanticUIResult, FormSchema, etc.) |
| Toggle support | Both auto-collapse and explicit toggle groups | Auto-collapse is convenience sugar that generates ToggleGroups internally |
| Migration strategy | Incremental per-consumer | Each consumer adapts independently; no big-bang switch |

---

## Package Layout

```
packages/ai-parrot/src/parrot/outputs/cards/
├── __init__.py          # Public API re-exports
├── elements.py          # Pydantic models for AC 1.5 display elements
├── sections.py          # Composable semantic sections
├── spec.py              # CardSpec top-level model
├── actions.py           # Action models (Submit, OpenUrl, ToggleVisibility, ShowCard)
├── inputs.py            # Input element models (Text, Number, Toggle, Date, etc.)
├── toggle.py            # ToggleGroup + AutoCollapsePolicy
├── renderer.py          # CardSpec → AC 1.5 JSON
├── markdown.py          # Markdown text → list[CardSection] parser
└── attachment.py        # Bot Framework attachment envelope helper
```

---

## Element Models (`elements.py`)

Every AC 1.5 display element gets a typed Pydantic model. These map 1:1 to the Adaptive Card schema.

```python
class ACElement(BaseModel):
    """Base for all Adaptive Card elements."""
    element_type: str  # discriminator, maps to AC "type"

class TextBlock(ACElement):
    element_type: Literal["TextBlock"] = "TextBlock"
    text: str
    wrap: bool = True
    weight: Literal["Default", "Bolder", "Lighter"] | None = None
    size: Literal["Default", "Small", "Medium", "Large", "ExtraLarge"] | None = None
    color: Literal["Default", "Dark", "Light", "Accent",
                    "Good", "Warning", "Attention"] | None = None
    font_type: Literal["Default", "Monospace"] | None = None
    is_subtle: bool = False
    horizontal_alignment: Literal["Left", "Center", "Right"] | None = None
    spacing: Literal["None", "Small", "Default", "Medium",
                     "Large", "ExtraLarge", "Padding"] | None = None
    separator: bool = False
    max_lines: int | None = None
    id: str | None = None
    is_visible: bool = True

class Image(ACElement):
    element_type: Literal["Image"] = "Image"
    url: str                       # http/https or data:image/... URI
    alt_text: str = ""
    size: Literal["Auto", "Stretch", "Small", "Medium", "Large"] | None = None
    horizontal_alignment: Literal["Left", "Center", "Right"] | None = None
    spacing: str | None = None
    id: str | None = None
    is_visible: bool = True

class Table(ACElement):
    """AC 1.5 native Table element."""
    element_type: Literal["Table"] = "Table"
    columns: list["TableColumnDefinition"]
    rows: list["TableRow"]
    first_row_as_header: bool = True
    show_grid_lines: bool = True
    grid_style: Literal["Default", "Accent", "Good",
                         "Warning", "Attention"] | None = None
    horizontal_cell_content_alignment: Literal["Left", "Center", "Right"] | None = None
    vertical_cell_content_alignment: Literal["Top", "Center", "Bottom"] | None = None

class TableColumnDefinition(BaseModel):
    width: str | int = "1"         # pixel or weight

class TableRow(BaseModel):
    cells: list["TableCell"]
    style: Literal["Default", "Accent", "Good",
                    "Warning", "Attention"] | None = None

class TableCell(BaseModel):
    items: list["ACElement"] = []  # usually a single TextBlock

class Container(ACElement):
    element_type: Literal["Container"] = "Container"
    items: list["ACElement"] = []
    style: Literal["Default", "Emphasis", "Good", "Attention",
                    "Warning", "Accent"] | None = None
    spacing: str | None = None
    id: str | None = None
    is_visible: bool = True

class ColumnSet(ACElement):
    element_type: Literal["ColumnSet"] = "ColumnSet"
    columns: list["Column"] = []
    spacing: str | None = None
    separator: bool = False

class Column(BaseModel):
    width: str = "stretch"
    items: list["ACElement"] = []

class FactSet(ACElement):
    element_type: Literal["FactSet"] = "FactSet"
    facts: list["Fact"] = []

class Fact(BaseModel):
    title: str
    value: str
```

Properties use snake_case in Python; the renderer converts to camelCase for AC JSON output. `id` and `is_visible` appear on elements that can be ToggleVisibility targets.

---

## Input Models (`inputs.py`)

AC input elements for form and HITL cards, sharing the `ACElement` base.

```python
class InputText(ACElement):
    element_type: Literal["Input.Text"] = "Input.Text"
    id: str
    placeholder: str = ""
    value: str = ""
    is_multiline: bool = False
    max_length: int | None = None
    regex: str | None = None
    style: Literal["Text", "Email", "Url", "Tel", "Password"] | None = None
    is_required: bool = False
    label: str | None = None          # AC 1.3+ native label
    error_message: str | None = None  # AC 1.3+ validation message

class InputNumber(ACElement):
    element_type: Literal["Input.Number"] = "Input.Number"
    id: str
    placeholder: str = ""
    value: float | int | None = None
    min: float | int | None = None
    max: float | int | None = None
    is_required: bool = False
    label: str | None = None
    error_message: str | None = None

class InputToggle(ACElement):
    element_type: Literal["Input.Toggle"] = "Input.Toggle"
    id: str
    title: str
    value: str = "false"
    value_on: str = "true"
    value_off: str = "false"
    is_required: bool = False
    label: str | None = None

class InputDate(ACElement):
    element_type: Literal["Input.Date"] = "Input.Date"
    id: str
    value: str | None = None
    min: str | None = None
    max: str | None = None
    is_required: bool = False
    label: str | None = None

class InputTime(ACElement):
    element_type: Literal["Input.Time"] = "Input.Time"
    id: str
    value: str | None = None
    min: str | None = None
    max: str | None = None
    is_required: bool = False
    label: str | None = None

class InputChoiceSet(ACElement):
    element_type: Literal["Input.ChoiceSet"] = "Input.ChoiceSet"
    id: str
    choices: list["InputChoice"] = []
    value: str | None = None
    is_multi_select: bool = False
    style: Literal["compact", "expanded", "filtered"] | None = None
    is_required: bool = False
    label: str | None = None

class InputChoice(BaseModel):
    title: str
    value: str
```

AC 1.3+ native `label` and `errorMessage` on input elements replaces the current pattern of separate TextBlocks for labels — cleaner cards with built-in client-side validation.

---

## Actions (`actions.py`)

```python
class ACAction(BaseModel):
    """Base for all Adaptive Card actions."""
    action_type: str
    title: str
    style: Literal["default", "positive", "destructive"] | None = None

class ActionSubmit(ACAction):
    action_type: Literal["Action.Submit"] = "Action.Submit"
    data: dict[str, Any] = {}
    associated_inputs: Literal["Auto", "None"] | None = None

class ActionOpenUrl(ACAction):
    action_type: Literal["Action.OpenUrl"] = "Action.OpenUrl"
    url: str

class ActionToggleVisibility(ACAction):
    action_type: Literal["Action.ToggleVisibility"] = "Action.ToggleVisibility"
    target_elements: list["TargetElement"] = []

class TargetElement(BaseModel):
    """Reference to an element whose visibility is toggled."""
    element_id: str
    is_visible: bool | None = None  # None = toggle, True/False = set explicitly

class ActionShowCard(ACAction):
    """Show an inline sub-card on click."""
    action_type: Literal["Action.ShowCard"] = "Action.ShowCard"
    card: "CardSpec"  # forward ref resolved at model_rebuild()
```

`ActionExecute` (Universal Actions) is deliberately omitted — it requires Bot Invoke infrastructure AI-Parrot doesn't use yet. Easy to add later as another `ACAction` subclass.

---

## Toggle Logic (`toggle.py`)

```python
class ToggleGroup(BaseModel):
    """Declarative toggle group — caller specifies what collapses."""
    label_expanded: str = "Hide details"
    label_collapsed: str = "Show details"
    content: list["ACElement"]
    initially_visible: bool = False
    group_id: str | None = None     # auto-generated if None

class AutoCollapsePolicy(BaseModel):
    """Policy for the renderer's auto-collapse behavior."""
    enabled: bool = True
    table_row_threshold: int = 5
    text_char_threshold: int = 500
    code_line_threshold: int = 10
    image_count_threshold: int = 2
```

**How it works at render time:**

1. **Explicit toggles**: Caller includes a `ToggleSection` in the card. The renderer emits a `Container` with `id="{group_id}_content"`, `isVisible={initially_visible}`, plus an `Action.ToggleVisibility` targeting that container.

2. **Auto-collapse**: When `AutoCollapsePolicy.enabled` is true, the renderer inspects expanded elements after section expansion. Content exceeding a threshold gets split into a preview (always visible) and remainder (wrapped in a generated `ToggleGroup` with contextual label like "Show 15 more rows").

3. **ID generation**: Deterministic — `"{group_id}_content"` for the container, `"{group_id}_toggle"` for the action. Auto-generated IDs use `"tg_auto_{index}"`.

Auto-collapse is syntactic sugar — it generates `ToggleGroup` instances internally, so the renderer has one code path for toggle serialization.

---

## CardSpec and Sections (`spec.py`, `sections.py`)

### CardSpec (`spec.py`)

```python
class CardSpec(BaseModel):
    """Top-level Adaptive Card specification.
    
    Every card in the system — display, form, HITL — is expressed
    as a CardSpec before rendering to AC JSON.
    """
    title: str | None = None
    summary: str | None = None
    sections: list["CardSection"] = []
    actions: list["ACAction"] = []
    auto_collapse: AutoCollapsePolicy | None = None
    version: str = "1.5"
    schema_url: str = "http://adaptivecards.io/schemas/adaptive-card.json"
```

### Sections (`sections.py`)

Semantic section types — each knows what content it carries; the renderer maps it to AC elements.

```python
class CardSection(BaseModel):
    """Base for all composable sections."""
    section_type: str
    spacing: str | None = None
    separator: bool = False

class TextSection(CardSection):
    section_type: Literal["text"] = "text"
    text: str
    role: Literal["body", "title", "heading", "subtitle",
                   "label", "code", "monospace"] = "body"
    color: str | None = None
    is_subtle: bool = False

class TableSection(CardSection):
    """Tabular data — renders as native AC 1.5 Table."""
    section_type: Literal["table"] = "table"
    columns: list[str]
    rows: list[list[str]]
    total_rows: int | None = None
    max_display_rows: int = 20
    show_grid_lines: bool = True
    first_row_as_header: bool = True

class MetricsSection(CardSection):
    section_type: Literal["metrics"] = "metrics"
    metrics: list["MetricEntry"] = []

class MetricEntry(BaseModel):
    label: str
    value: str
    delta: str | None = None

class DetailSection(CardSection):
    section_type: Literal["detail"] = "detail"
    fields: list["DetailField"] = []

class DetailField(BaseModel):
    label: str
    value: str

class ImageSection(CardSection):
    section_type: Literal["image"] = "image"
    images: list["ImageEntry"] = []

class ImageEntry(BaseModel):
    url: str
    alt_text: str = ""
    size: Literal["Auto", "Stretch", "Small", "Medium", "Large"] = "Large"

class CodeSection(CardSection):
    section_type: Literal["code"] = "code"
    code: str
    language: str | None = None
    label: str | None = None

class StatusSection(CardSection):
    section_type: Literal["status"] = "status"
    level: Literal["success", "warning", "error", "info"] = "info"
    message: str
    details: str | None = None

class ToggleSection(CardSection):
    section_type: Literal["toggle"] = "toggle"
    toggle: ToggleGroup

class FormSection(CardSection):
    section_type: Literal["form"] = "form"
    fields: list["FormFieldSpec"] = []

class FormFieldSpec(BaseModel):
    field_id: str
    field_type: str                 # string key matching FieldType enum values
                                    # ("text", "number", "boolean", "select", etc.)
                                    # Kept as str to avoid pulling forms dependency;
                                    # the renderer's _expand_form() maps to Input.* elements.
    label: str
    description: str | None = None
    placeholder: str | None = None
    required: bool = False
    default: Any = None
    options: list["InputChoice"] | None = None
    constraints: dict[str, Any] | None = None
    is_multiline: bool = False

class RawElementsSection(CardSection):
    """Escape hatch — pass pre-built ACElement instances directly."""
    section_type: Literal["raw"] = "raw"
    elements: list["ACElement"] = []
```

---

## Renderer (`renderer.py`)

Pure function: `CardSpec` in, AC 1.5 JSON `dict` out. No I/O, no side effects.

```python
def render(spec: CardSpec) -> dict[str, Any]:
    """Render a CardSpec to Adaptive Card 1.5 JSON."""

def render_text(spec: CardSpec) -> str:
    """Render a CardSpec as plain/markdown text fallback. Never raises."""
```

### Render Pipeline

**Stage 1 — Section expansion.** Each section type has a dedicated expander:

```python
_SECTION_EXPANDERS = {
    "text":    _expand_text,       # → TextBlock (with role-based styling)
    "table":   _expand_table,      # → Table (native AC 1.5)
    "metrics": _expand_metrics,    # → FactSet
    "detail":  _expand_detail,     # → FactSet
    "image":   _expand_image,      # → Image elements
    "code":    _expand_code,       # → TextBlock(fontType=Monospace) + optional label
    "status":  _expand_status,     # → Container with colored TextBlocks
    "toggle":  _expand_toggle,     # → Container(isVisible) + Action.ToggleVisibility
    "form":    _expand_form,       # → Input.* elements with labels
    "raw":     _expand_raw,        # → pass-through
}
```

Each expander returns `tuple[list[ACElement], list[ACAction]]` — body elements plus any actions the section introduces (toggle buttons, form submits).

**Stage 2 — Auto-collapse.** When `spec.auto_collapse` is set, the renderer walks the expanded body and wraps oversized content in generated ToggleGroups:

- Table with > `table_row_threshold` rows: preview first N rows, toggle the rest
- TextBlock with > `text_char_threshold` chars: truncated preview, toggle full
- Code with > `code_line_threshold` lines: first N lines, toggle full
- Images beyond `image_count_threshold`: show first N, toggle the rest

Generated ToggleGroups get deterministic IDs (`tg_auto_{index}`).

**Stage 3 — Serialization.** Walk the element tree, convert each Pydantic model to AC JSON:

- `element_type` → `"type"`
- snake_case fields → camelCase (explicit mapping per model, not generic conversion)
- Omit `None`/default values to keep cards compact
- Recurse into children (Container.items, Table.rows, ColumnSet.columns, etc.)

**Size guard**: After serialization, check `len(json.dumps(card).encode("utf-8"))` against `max_card_bytes` (default 28KB — Teams' limit). Raise `CardRenderError` if exceeded so callers can fall back to `render_text()`.

---

## Markdown Parser (`markdown.py`)

```python
def markdown_to_sections(text: str) -> list[CardSection]:
    """Parse markdown text into a list of CardSections.
    
    Splits on structural boundaries:
    - Contiguous prose → TextSection
    - Pipe-delimited tables → TableSection (columns/rows extracted)
    - Fenced code blocks (```lang ... ```) → CodeSection
    - Image references (![alt](url)) → ImageSection (standalone lines only)
    
    Inline markdown (bold, italic, links, lists) is left intact
    inside TextSections — Teams renders it natively in TextBlocks.
    """
```

Consolidates the ~200 lines of regex-based parsing currently in `_render_markdown_content()` and `_markdown_table_to_adaptive()` from `msteams/wrapper.py` into a single reusable function.

---

## Attachment Helper (`attachment.py`)

```python
AC_CONTENT_TYPE = "application/vnd.microsoft.card.adaptive"

def build_attachment(card: dict[str, Any]) -> dict[str, Any]:
    """Wrap an AC JSON dict in the Bot Framework attachment envelope."""
    return {"contentType": AC_CONTENT_TYPE, "content": card}

def build_attachment_from_spec(spec: CardSpec) -> dict[str, Any]:
    """Render a CardSpec and wrap in an attachment envelope."""
    return build_attachment(render(spec))
```

Replaces duplicate `build_card_attachment()` in `msagentsdk/cards.py` and inline wrapping in `msteams/wrapper.py`.

---

## Public API (`__init__.py`)

```python
# Core
from .spec import CardSpec
from .sections import (
    CardSection, TextSection, TableSection, MetricsSection,
    DetailSection, ImageSection, CodeSection, StatusSection,
    ToggleSection, FormSection, FormFieldSpec, RawElementsSection,
    MetricEntry, DetailField, ImageEntry,
)

# Elements (for RawElementsSection / advanced use)
from .elements import (
    ACElement, TextBlock, Image, Table, TableColumnDefinition,
    TableRow, TableCell, Container, ColumnSet, Column, FactSet, Fact,
)

# Inputs
from .inputs import (
    InputText, InputNumber, InputToggle, InputDate,
    InputTime, InputChoiceSet, InputChoice,
)

# Actions
from .actions import (
    ACAction, ActionSubmit, ActionOpenUrl,
    ActionToggleVisibility, ActionShowCard, TargetElement,
)

# Toggle
from .toggle import ToggleGroup, AutoCollapsePolicy

# Rendering
from .renderer import render, render_text, CardRenderError

# Utilities
from .attachment import build_attachment, build_attachment_from_spec
from .markdown import markdown_to_sections
```

---

## Consumer Migration

Each consumer keeps its public API unchanged. Migration is internal — swap raw dict construction for `CardSpec` building and `render()` calls.

### `msagentsdk/cards.py`

**Before**: `SemanticUIResult` → inline dict construction → AC 1.4 JSON.
**After**: `SemanticUIResult` → `_semantic_to_card_spec()` → `render()` → AC 1.5 JSON.

```python
def render_card(result: SemanticUIResult, *, max_table_rows=15, max_card_bytes=25_000) -> dict:
    spec = _semantic_to_card_spec(result, max_table_rows=max_table_rows)
    return cards_renderer.render(spec)
```

`SemanticUIResult` model stays unchanged — it remains the domain agent's structured output contract. The `_render_table`, `_render_metrics`, `_render_detail`, `_render_status` functions are replaced by the mapping function. `render_text()`, `render_text_card()`, `render_data_card()`, and `build_card_attachment()` all delegate similarly.

### `msteams/wrapper.py`

**Before**: `ParsedResponse` → `_build_adaptive_card()` builds ~450 lines of dicts inline.
**After**: `ParsedResponse` → `_parsed_to_card_spec()` → `render()`.

The `_render_markdown_content()` and `_markdown_table_to_adaptive()` methods are replaced by the shared `markdown_to_sections()` utility. Charts are mapped to `ImageSection` via `chart.to_data_uri()`. Auto-collapse is enabled by default.

### `a2ui_renderers/adaptive_cards.py`

**Before**: `BasicNode` → `_map_node()` → inline AC dicts.
**After**: `BasicNode` → `_map_node_to_element()` → shared `ACElement` instances → `RawElementsSection` in a `CardSpec` → `render()`.

Uses `RawElementsSection` because A2UI has its own semantic model — the card builder handles serialization and the AC envelope.

### `forms/renderers/adaptive_card.py`

**Before**: `FormField` → `_build_input_element()` → inline AC dicts.
**After**: `FormField` → `FormFieldSpec` → `FormSection` → `CardSpec` → `render()`.

The `_FIELD_TYPE_MAPPING` and `_build_input_element()` logic move into the shared renderer's `_expand_form()`. The forms renderer becomes a thin adapter.

### `msteams/hitl_cards.py`

**Before**: `HumanInteraction` → `TeamsCardRenderer.render()` → inline AC dicts.
**After**: `HumanInteraction` → `CardSpec` with `FormSection` + `RawElementsSection` → `render()`.

HITL cards use `FormSection` for Input elements and `RawElementsSection` for interaction-specific layouts. `interaction_id` on Submit actions passes through `ActionSubmit.data`.

---

## Usage Example

```python
from parrot.outputs.cards import (
    CardSpec, TableSection, TextSection, MetricsSection,
    MetricEntry, AutoCollapsePolicy, ActionSubmit, render,
)

spec = CardSpec(
    title="Sales Report",
    summary="Q2 2026 summary",
    sections=[
        MetricsSection(metrics=[
            MetricEntry(label="Revenue", value="$1.2M", delta="+12%"),
            MetricEntry(label="Deals Closed", value="47", delta="+3"),
        ]),
        TableSection(
            columns=["Region", "Revenue", "Target"],
            rows=[["LATAM", "$400K", "$350K"], ["EMEA", "$800K", "$750K"]],
        ),
    ],
    actions=[
        ActionSubmit(title="Show breakdown",
                     data={"prompt": "break down by rep"}),
    ],
    auto_collapse=AutoCollapsePolicy(table_row_threshold=10),
)

card_json = render(spec)
```

---

## Testing Strategy

- **Unit tests per module**: elements, inputs, actions, sections, toggle, renderer, markdown parser — each tested in isolation.
- **Snapshot tests**: Golden JSON outputs for each section type to catch serialization regressions.
- **Round-trip tests**: `CardSpec` → `render()` → validate against AC 1.5 JSON schema.
- **Migration parity tests**: For each consumer, assert that the new `CardSpec`-based output matches the old inline-dict output (modulo AC version bump and Table element change).
- **Auto-collapse tests**: Verify threshold behavior, ID generation, and nested toggle correctness.
- **Size guard tests**: Verify `CardRenderError` on oversized cards and `render_text()` fallback.

---

## Out of Scope

- **`ActionExecute` (Universal Actions)**: Requires Bot Invoke infrastructure not yet in AI-Parrot. Easy to add as another `ACAction` subclass when needed.
- **`Carousel` / `MediaSet`**: AC 1.6+ elements not yet widely supported in Teams.
- **Version-aware fallback**: No ColumnSet fallback for AC < 1.5 hosts (YAGNI per design decision).
- **Interactive chart elements**: Charts remain rasterized PNG images embedded as `ImageSection`. Interactive charting would require a separate surface (e.g., task module with embedded web content).
