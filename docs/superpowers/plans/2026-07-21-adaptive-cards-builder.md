# Unified Adaptive Cards Builder — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Consolidate five independent AC card-building systems into a shared Pydantic-first builder at `parrot/outputs/cards/`, upgrade everything to AC 1.5 with native Table and Action.ToggleVisibility.

**Architecture:** Three-layer declarative model — elements (AC 1.5 vocabulary), sections (semantic groupings), and CardSpec (top-level card). A pure-function renderer walks CardSpec → elements → AC 1.5 JSON. Each existing consumer keeps its public API and migrates internals to build CardSpec instances.

**Tech Stack:** Python 3.11+, Pydantic v2, pytest / pytest-asyncio.

## Global Constraints

- AC version is **1.5** universally — no fallback to older versions.
- All models use **Pydantic v2** `BaseModel` with strict type hints.
- Python snake_case in models; renderer converts to camelCase for AC JSON.
- Omit `None`/default values in serialized JSON to keep cards compact.
- Max card size: 28KB (Teams' limit). Raise `CardRenderError` if exceeded.
- No external dependencies — `parrot.outputs.cards` depends only on `pydantic`.
- Package location: `packages/ai-parrot/src/parrot/outputs/cards/`.
- Test location: `packages/ai-parrot/tests/unit/outputs/cards/`.

## File Structure

```
packages/ai-parrot/src/parrot/outputs/cards/
├── __init__.py          # Public API re-exports
├── elements.py          # ACElement base + display elements (TextBlock, Image, Table, Container, ColumnSet, FactSet)
├── inputs.py            # Input elements (InputText, InputNumber, InputToggle, InputDate, InputTime, InputChoiceSet)
├── actions.py           # ACAction base + ActionSubmit, ActionOpenUrl, ActionToggleVisibility, ActionShowCard
├── toggle.py            # ToggleGroup + AutoCollapsePolicy models
├── sections.py          # CardSection base + all semantic section types
├── spec.py              # CardSpec top-level model
├── renderer.py          # render() + render_text() + CardRenderError + section expanders + auto-collapse + serialization
├── markdown.py          # markdown_to_sections() parser
└── attachment.py        # build_attachment() + build_attachment_from_spec()

packages/ai-parrot/tests/unit/outputs/cards/
├── __init__.py
├── test_elements.py
├── test_inputs.py
├── test_actions.py
├── test_toggle.py
├── test_sections.py
├── test_renderer.py
├── test_renderer_auto_collapse.py
├── test_markdown.py
└── test_attachment.py
```

Consumer migration files (modified, not created):
- `packages/ai-parrot-integrations/src/parrot/integrations/msagentsdk/cards.py`
- `packages/ai-parrot-integrations/src/parrot/integrations/msteams/wrapper.py`
- `packages/ai-parrot-visualizations/src/parrot/outputs/a2ui_renderers/adaptive_cards.py`
- `packages/ai-parrot/src/parrot/forms/renderers/adaptive_card.py`
- `packages/ai-parrot-integrations/src/parrot/integrations/msteams/hitl_cards.py`

---

### Task 1: Element Models

**Files:**
- Create: `packages/ai-parrot/src/parrot/outputs/cards/__init__.py`
- Create: `packages/ai-parrot/src/parrot/outputs/cards/elements.py`
- Test: `packages/ai-parrot/tests/unit/outputs/cards/__init__.py`
- Test: `packages/ai-parrot/tests/unit/outputs/cards/test_elements.py`

**Interfaces:**
- Consumes: nothing (foundational)
- Produces: `ACElement` (base), `TextBlock`, `Image`, `Table`, `TableColumnDefinition`, `TableRow`, `TableCell`, `Container`, `ColumnSet`, `Column`, `FactSet`, `Fact` — all Pydantic `BaseModel` subclasses importable from `parrot.outputs.cards.elements`

- [ ] **Step 1: Write failing tests for element models**

```python
# tests/unit/outputs/cards/test_elements.py
"""Unit tests for AC 1.5 element models."""
import pytest
from pydantic import ValidationError


class TestTextBlock:
    def test_minimal(self):
        from parrot.outputs.cards.elements import TextBlock
        tb = TextBlock(text="hello")
        assert tb.element_type == "TextBlock"
        assert tb.text == "hello"
        assert tb.wrap is True
        assert tb.is_visible is True

    def test_all_properties(self):
        from parrot.outputs.cards.elements import TextBlock
        tb = TextBlock(
            text="title",
            weight="Bolder",
            size="Large",
            color="Good",
            font_type="Monospace",
            is_subtle=True,
            horizontal_alignment="Center",
            spacing="Medium",
            separator=True,
            max_lines=3,
            id="tb1",
            is_visible=False,
        )
        assert tb.weight == "Bolder"
        assert tb.id == "tb1"
        assert tb.is_visible is False

    def test_invalid_weight_rejected(self):
        from parrot.outputs.cards.elements import TextBlock
        with pytest.raises(ValidationError):
            TextBlock(text="x", weight="SuperBold")


class TestImage:
    def test_minimal(self):
        from parrot.outputs.cards.elements import Image
        img = Image(url="https://example.com/img.png")
        assert img.element_type == "Image"
        assert img.url == "https://example.com/img.png"
        assert img.alt_text == ""

    def test_data_uri(self):
        from parrot.outputs.cards.elements import Image
        img = Image(url="data:image/png;base64,abc123", alt_text="chart")
        assert img.url.startswith("data:image/")


class TestTable:
    def test_structure(self):
        from parrot.outputs.cards.elements import (
            Table, TableColumnDefinition, TableRow, TableCell, TextBlock,
        )
        table = Table(
            columns=[TableColumnDefinition(width="1"), TableColumnDefinition(width="2")],
            rows=[
                TableRow(cells=[
                    TableCell(items=[TextBlock(text="a")]),
                    TableCell(items=[TextBlock(text="b")]),
                ]),
            ],
        )
        assert table.element_type == "Table"
        assert table.first_row_as_header is True
        assert len(table.rows) == 1
        assert len(table.rows[0].cells) == 2

    def test_empty_table(self):
        from parrot.outputs.cards.elements import Table
        table = Table(columns=[], rows=[])
        assert table.rows == []


class TestContainer:
    def test_with_children(self):
        from parrot.outputs.cards.elements import Container, TextBlock
        c = Container(
            items=[TextBlock(text="inner")],
            style="Emphasis",
            id="c1",
            is_visible=False,
        )
        assert c.element_type == "Container"
        assert len(c.items) == 1
        assert c.is_visible is False


class TestColumnSet:
    def test_with_columns(self):
        from parrot.outputs.cards.elements import ColumnSet, Column, TextBlock
        cs = ColumnSet(
            columns=[
                Column(width="stretch", items=[TextBlock(text="col1")]),
                Column(width="auto", items=[TextBlock(text="col2")]),
            ],
        )
        assert cs.element_type == "ColumnSet"
        assert len(cs.columns) == 2


class TestFactSet:
    def test_facts(self):
        from parrot.outputs.cards.elements import FactSet, Fact
        fs = FactSet(facts=[
            Fact(title="Revenue", value="$1M"),
            Fact(title="Growth", value="+12%"),
        ])
        assert fs.element_type == "FactSet"
        assert len(fs.facts) == 2
```

- [ ] **Step 2: Run tests to verify they fail**

```bash
cd /home/jesuslara/proyectos/ai-parrot
source .venv/bin/activate
pytest packages/ai-parrot/tests/unit/outputs/cards/test_elements.py -v
```

Expected: `ModuleNotFoundError: No module named 'parrot.outputs.cards'`

- [ ] **Step 3: Implement element models**

```python
# packages/ai-parrot/src/parrot/outputs/cards/__init__.py
"""Unified Adaptive Card 1.5 builder."""

# packages/ai-parrot/src/parrot/outputs/cards/elements.py
"""Pydantic models for AC 1.5 display elements."""
from __future__ import annotations

from typing import Literal, Optional

from pydantic import BaseModel


class ACElement(BaseModel):
    """Base for all Adaptive Card elements."""
    element_type: str


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
    url: str
    alt_text: str = ""
    size: Literal["Auto", "Stretch", "Small", "Medium", "Large"] | None = None
    horizontal_alignment: Literal["Left", "Center", "Right"] | None = None
    spacing: Literal["None", "Small", "Default", "Medium",
                     "Large", "ExtraLarge", "Padding"] | None = None
    id: str | None = None
    is_visible: bool = True


class Fact(BaseModel):
    title: str
    value: str


class FactSet(ACElement):
    element_type: Literal["FactSet"] = "FactSet"
    facts: list[Fact] = []


class TableColumnDefinition(BaseModel):
    width: str | int = "1"


class TableCell(BaseModel):
    items: list[ACElement] = []


class TableRow(BaseModel):
    cells: list[TableCell]
    style: Literal["Default", "Accent", "Good",
                    "Warning", "Attention"] | None = None


class Table(ACElement):
    element_type: Literal["Table"] = "Table"
    columns: list[TableColumnDefinition]
    rows: list[TableRow]
    first_row_as_header: bool = True
    show_grid_lines: bool = True
    grid_style: Literal["Default", "Accent", "Good",
                         "Warning", "Attention"] | None = None
    horizontal_cell_content_alignment: Literal["Left", "Center", "Right"] | None = None
    vertical_cell_content_alignment: Literal["Top", "Center", "Bottom"] | None = None


class Column(BaseModel):
    width: str = "stretch"
    items: list[ACElement] = []


class ColumnSet(ACElement):
    element_type: Literal["ColumnSet"] = "ColumnSet"
    columns: list[Column] = []
    spacing: Literal["None", "Small", "Default", "Medium",
                     "Large", "ExtraLarge", "Padding"] | None = None
    separator: bool = False


class Container(ACElement):
    element_type: Literal["Container"] = "Container"
    items: list[ACElement] = []
    style: Literal["Default", "Emphasis", "Good", "Attention",
                    "Warning", "Accent"] | None = None
    spacing: Literal["None", "Small", "Default", "Medium",
                     "Large", "ExtraLarge", "Padding"] | None = None
    id: str | None = None
    is_visible: bool = True
```

- [ ] **Step 4: Run tests to verify they pass**

```bash
pytest packages/ai-parrot/tests/unit/outputs/cards/test_elements.py -v
```

Expected: All PASS.

- [ ] **Step 5: Commit**

```bash
git add packages/ai-parrot/src/parrot/outputs/cards/__init__.py \
       packages/ai-parrot/src/parrot/outputs/cards/elements.py \
       packages/ai-parrot/tests/unit/outputs/cards/__init__.py \
       packages/ai-parrot/tests/unit/outputs/cards/test_elements.py
git commit -m "feat(cards): AC 1.5 element models — TextBlock, Image, Table, Container, ColumnSet, FactSet"
```

---

### Task 2: Input Models and Action Models

**Files:**
- Create: `packages/ai-parrot/src/parrot/outputs/cards/inputs.py`
- Create: `packages/ai-parrot/src/parrot/outputs/cards/actions.py`
- Test: `packages/ai-parrot/tests/unit/outputs/cards/test_inputs.py`
- Test: `packages/ai-parrot/tests/unit/outputs/cards/test_actions.py`

**Interfaces:**
- Consumes: `ACElement` from `parrot.outputs.cards.elements` (Task 1)
- Produces: `InputText`, `InputNumber`, `InputToggle`, `InputDate`, `InputTime`, `InputChoiceSet`, `InputChoice` from `inputs.py`; `ACAction`, `ActionSubmit`, `ActionOpenUrl`, `ActionToggleVisibility`, `TargetElement`, `ActionShowCard` from `actions.py`

- [ ] **Step 1: Write failing tests for inputs**

```python
# tests/unit/outputs/cards/test_inputs.py
"""Unit tests for AC input element models."""
import pytest
from pydantic import ValidationError


class TestInputText:
    def test_minimal(self):
        from parrot.outputs.cards.inputs import InputText
        inp = InputText(id="name")
        assert inp.element_type == "Input.Text"
        assert inp.is_multiline is False
        assert inp.is_required is False

    def test_email_style(self):
        from parrot.outputs.cards.inputs import InputText
        inp = InputText(id="email", style="Email", is_required=True, label="Email")
        assert inp.style == "Email"
        assert inp.label == "Email"

    def test_multiline(self):
        from parrot.outputs.cards.inputs import InputText
        inp = InputText(id="notes", is_multiline=True, max_length=500)
        assert inp.is_multiline is True
        assert inp.max_length == 500


class TestInputNumber:
    def test_with_range(self):
        from parrot.outputs.cards.inputs import InputNumber
        inp = InputNumber(id="qty", min=1, max=100, value=5)
        assert inp.element_type == "Input.Number"
        assert inp.min == 1


class TestInputToggle:
    def test_defaults(self):
        from parrot.outputs.cards.inputs import InputToggle
        inp = InputToggle(id="agree", title="I agree")
        assert inp.element_type == "Input.Toggle"
        assert inp.value == "false"
        assert inp.value_on == "true"


class TestInputDate:
    def test_minimal(self):
        from parrot.outputs.cards.inputs import InputDate
        inp = InputDate(id="dob")
        assert inp.element_type == "Input.Date"
        assert inp.value is None


class TestInputTime:
    def test_minimal(self):
        from parrot.outputs.cards.inputs import InputTime
        inp = InputTime(id="start_time")
        assert inp.element_type == "Input.Time"


class TestInputChoiceSet:
    def test_single_select(self):
        from parrot.outputs.cards.inputs import InputChoiceSet, InputChoice
        inp = InputChoiceSet(
            id="role",
            choices=[InputChoice(title="Admin", value="admin"),
                     InputChoice(title="User", value="user")],
            style="compact",
        )
        assert inp.element_type == "Input.ChoiceSet"
        assert inp.is_multi_select is False
        assert len(inp.choices) == 2

    def test_multi_select(self):
        from parrot.outputs.cards.inputs import InputChoiceSet, InputChoice
        inp = InputChoiceSet(
            id="tags",
            choices=[InputChoice(title="A", value="a")],
            is_multi_select=True,
            style="expanded",
        )
        assert inp.is_multi_select is True
```

- [ ] **Step 2: Write failing tests for actions**

```python
# tests/unit/outputs/cards/test_actions.py
"""Unit tests for AC action models."""
import pytest
from pydantic import ValidationError


class TestActionSubmit:
    def test_minimal(self):
        from parrot.outputs.cards.actions import ActionSubmit
        a = ActionSubmit(title="Submit")
        assert a.action_type == "Action.Submit"
        assert a.data == {}

    def test_with_data_and_style(self):
        from parrot.outputs.cards.actions import ActionSubmit
        a = ActionSubmit(
            title="Cancel",
            style="destructive",
            data={"_action": "cancel"},
            associated_inputs="None",
        )
        assert a.style == "destructive"
        assert a.associated_inputs == "None"


class TestActionOpenUrl:
    def test_minimal(self):
        from parrot.outputs.cards.actions import ActionOpenUrl
        a = ActionOpenUrl(title="Open", url="https://example.com")
        assert a.action_type == "Action.OpenUrl"
        assert a.url == "https://example.com"


class TestActionToggleVisibility:
    def test_toggle_targets(self):
        from parrot.outputs.cards.actions import ActionToggleVisibility, TargetElement
        a = ActionToggleVisibility(
            title="Show details",
            target_elements=[
                TargetElement(element_id="detail_1"),
                TargetElement(element_id="detail_2", is_visible=True),
            ],
        )
        assert a.action_type == "Action.ToggleVisibility"
        assert len(a.target_elements) == 2
        assert a.target_elements[0].is_visible is None  # toggle mode
        assert a.target_elements[1].is_visible is True   # explicit set


class TestActionShowCard:
    def test_inline_card(self):
        from parrot.outputs.cards.actions import ActionShowCard
        from parrot.outputs.cards.spec import CardSpec
        from parrot.outputs.cards.sections import TextSection
        inner = CardSpec(
            title="Details",
            sections=[TextSection(text="More info here")],
        )
        a = ActionShowCard(title="Details", card=inner)
        assert a.action_type == "Action.ShowCard"
        assert a.card.title == "Details"
```

- [ ] **Step 3: Run tests to verify they fail**

```bash
pytest packages/ai-parrot/tests/unit/outputs/cards/test_inputs.py \
       packages/ai-parrot/tests/unit/outputs/cards/test_actions.py -v
```

Expected: `ModuleNotFoundError`

- [ ] **Step 4: Implement input models**

```python
# packages/ai-parrot/src/parrot/outputs/cards/inputs.py
"""Pydantic models for AC 1.5 input elements."""
from __future__ import annotations

from typing import Literal

from pydantic import BaseModel

from .elements import ACElement


class InputChoice(BaseModel):
    title: str
    value: str


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
    label: str | None = None
    error_message: str | None = None


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
    choices: list[InputChoice] = []
    value: str | None = None
    is_multi_select: bool = False
    style: Literal["compact", "expanded", "filtered"] | None = None
    is_required: bool = False
    label: str | None = None
```

- [ ] **Step 5: Implement action models**

Note: `ActionShowCard` references `CardSpec` (forward ref). Create a minimal `spec.py` and `sections.py` stub so the forward ref resolves. These will be fully implemented in Task 3.

```python
# packages/ai-parrot/src/parrot/outputs/cards/actions.py
"""Pydantic models for AC 1.5 actions."""
from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel


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


class TargetElement(BaseModel):
    element_id: str
    is_visible: bool | None = None


class ActionToggleVisibility(ACAction):
    action_type: Literal["Action.ToggleVisibility"] = "Action.ToggleVisibility"
    target_elements: list[TargetElement] = []


class ActionShowCard(ACAction):
    action_type: Literal["Action.ShowCard"] = "Action.ShowCard"
    card: Any  # typed as CardSpec at runtime; Any avoids circular import
```

- [ ] **Step 6: Run tests to verify they pass**

```bash
pytest packages/ai-parrot/tests/unit/outputs/cards/test_inputs.py \
       packages/ai-parrot/tests/unit/outputs/cards/test_actions.py -v
```

Expected: All PASS (the `TestActionShowCard` test imports `CardSpec` from `spec.py` which needs the stub — create it as part of this step if needed, or defer that single test to Task 3).

- [ ] **Step 7: Commit**

```bash
git add packages/ai-parrot/src/parrot/outputs/cards/inputs.py \
       packages/ai-parrot/src/parrot/outputs/cards/actions.py \
       packages/ai-parrot/tests/unit/outputs/cards/test_inputs.py \
       packages/ai-parrot/tests/unit/outputs/cards/test_actions.py
git commit -m "feat(cards): AC 1.5 input + action models — Input.*, Action.Submit/OpenUrl/ToggleVisibility/ShowCard"
```

---

### Task 3: Toggle, Sections, and CardSpec Models

**Files:**
- Create: `packages/ai-parrot/src/parrot/outputs/cards/toggle.py`
- Create: `packages/ai-parrot/src/parrot/outputs/cards/sections.py`
- Create: `packages/ai-parrot/src/parrot/outputs/cards/spec.py`
- Test: `packages/ai-parrot/tests/unit/outputs/cards/test_toggle.py`
- Test: `packages/ai-parrot/tests/unit/outputs/cards/test_sections.py`

**Interfaces:**
- Consumes: `ACElement` (Task 1), `ACAction` (Task 2), `InputChoice` (Task 2)
- Produces: `ToggleGroup`, `AutoCollapsePolicy`, all `CardSection` subclasses (`TextSection`, `TableSection`, `MetricsSection`, `DetailSection`, `ImageSection`, `CodeSection`, `StatusSection`, `ToggleSection`, `FormSection`, `FormFieldSpec`, `RawElementsSection`, `MetricEntry`, `DetailField`, `ImageEntry`), `CardSpec`

- [ ] **Step 1: Write failing tests for toggle models**

```python
# tests/unit/outputs/cards/test_toggle.py
"""Unit tests for toggle models."""


class TestToggleGroup:
    def test_defaults(self):
        from parrot.outputs.cards.elements import TextBlock
        from parrot.outputs.cards.toggle import ToggleGroup
        tg = ToggleGroup(content=[TextBlock(text="hidden")])
        assert tg.initially_visible is False
        assert tg.label_collapsed == "Show details"
        assert tg.label_expanded == "Hide details"
        assert tg.group_id is None

    def test_custom(self):
        from parrot.outputs.cards.elements import TextBlock
        from parrot.outputs.cards.toggle import ToggleGroup
        tg = ToggleGroup(
            content=[TextBlock(text="data")],
            label_collapsed="Show 15 more rows",
            label_expanded="Hide rows",
            initially_visible=True,
            group_id="table_overflow",
        )
        assert tg.group_id == "table_overflow"
        assert tg.initially_visible is True


class TestAutoCollapsePolicy:
    def test_defaults(self):
        from parrot.outputs.cards.toggle import AutoCollapsePolicy
        p = AutoCollapsePolicy()
        assert p.enabled is True
        assert p.table_row_threshold == 5
        assert p.text_char_threshold == 500
        assert p.code_line_threshold == 10
        assert p.image_count_threshold == 2

    def test_disabled(self):
        from parrot.outputs.cards.toggle import AutoCollapsePolicy
        p = AutoCollapsePolicy(enabled=False)
        assert p.enabled is False
```

- [ ] **Step 2: Write failing tests for sections and CardSpec**

```python
# tests/unit/outputs/cards/test_sections.py
"""Unit tests for section models and CardSpec."""


class TestTextSection:
    def test_defaults(self):
        from parrot.outputs.cards.sections import TextSection
        s = TextSection(text="hello")
        assert s.section_type == "text"
        assert s.role == "body"
        assert s.is_subtle is False


class TestTableSection:
    def test_structure(self):
        from parrot.outputs.cards.sections import TableSection
        s = TableSection(
            columns=["Name", "Age"],
            rows=[["Alice", "30"], ["Bob", "25"]],
            total_rows=100,
        )
        assert s.section_type == "table"
        assert len(s.rows) == 2
        assert s.max_display_rows == 20


class TestMetricsSection:
    def test_with_entries(self):
        from parrot.outputs.cards.sections import MetricsSection, MetricEntry
        s = MetricsSection(metrics=[
            MetricEntry(label="Rev", value="$1M", delta="+12%"),
        ])
        assert s.section_type == "metrics"
        assert s.metrics[0].delta == "+12%"


class TestDetailSection:
    def test_with_fields(self):
        from parrot.outputs.cards.sections import DetailSection, DetailField
        s = DetailSection(fields=[DetailField(label="Status", value="Active")])
        assert s.section_type == "detail"


class TestImageSection:
    def test_with_entries(self):
        from parrot.outputs.cards.sections import ImageSection, ImageEntry
        s = ImageSection(images=[
            ImageEntry(url="https://example.com/img.png", alt_text="chart"),
        ])
        assert s.section_type == "image"
        assert s.images[0].size == "Large"


class TestCodeSection:
    def test_with_language(self):
        from parrot.outputs.cards.sections import CodeSection
        s = CodeSection(code="print('hi')", language="python", label="Code (python):")
        assert s.section_type == "code"


class TestStatusSection:
    def test_defaults(self):
        from parrot.outputs.cards.sections import StatusSection
        s = StatusSection(message="All good")
        assert s.section_type == "status"
        assert s.level == "info"


class TestToggleSection:
    def test_wraps_toggle_group(self):
        from parrot.outputs.cards.elements import TextBlock
        from parrot.outputs.cards.sections import ToggleSection
        from parrot.outputs.cards.toggle import ToggleGroup
        tg = ToggleGroup(content=[TextBlock(text="hidden")])
        s = ToggleSection(toggle=tg)
        assert s.section_type == "toggle"


class TestFormSection:
    def test_with_fields(self):
        from parrot.outputs.cards.sections import FormSection, FormFieldSpec
        s = FormSection(fields=[
            FormFieldSpec(field_id="name", field_type="text", label="Name", required=True),
        ])
        assert s.section_type == "form"
        assert s.fields[0].required is True


class TestRawElementsSection:
    def test_passthrough(self):
        from parrot.outputs.cards.elements import TextBlock
        from parrot.outputs.cards.sections import RawElementsSection
        s = RawElementsSection(elements=[TextBlock(text="raw")])
        assert s.section_type == "raw"
        assert len(s.elements) == 1


class TestCardSpec:
    def test_minimal(self):
        from parrot.outputs.cards.spec import CardSpec
        spec = CardSpec()
        assert spec.version == "1.5"
        assert spec.sections == []
        assert spec.actions == []
        assert spec.auto_collapse is None

    def test_full(self):
        from parrot.outputs.cards.actions import ActionSubmit
        from parrot.outputs.cards.sections import TableSection, TextSection
        from parrot.outputs.cards.spec import CardSpec
        from parrot.outputs.cards.toggle import AutoCollapsePolicy
        spec = CardSpec(
            title="Report",
            summary="Q2 summary",
            sections=[
                TextSection(text="Overview"),
                TableSection(columns=["A"], rows=[["1"]]),
            ],
            actions=[ActionSubmit(title="OK")],
            auto_collapse=AutoCollapsePolicy(table_row_threshold=10),
        )
        assert spec.title == "Report"
        assert len(spec.sections) == 2
```

- [ ] **Step 3: Run tests to verify they fail**

```bash
pytest packages/ai-parrot/tests/unit/outputs/cards/test_toggle.py \
       packages/ai-parrot/tests/unit/outputs/cards/test_sections.py -v
```

Expected: `ModuleNotFoundError`

- [ ] **Step 4: Implement toggle.py**

```python
# packages/ai-parrot/src/parrot/outputs/cards/toggle.py
"""Toggle group and auto-collapse policy models."""
from __future__ import annotations

from pydantic import BaseModel

from .elements import ACElement


class ToggleGroup(BaseModel):
    label_expanded: str = "Hide details"
    label_collapsed: str = "Show details"
    content: list[ACElement]
    initially_visible: bool = False
    group_id: str | None = None


class AutoCollapsePolicy(BaseModel):
    enabled: bool = True
    table_row_threshold: int = 5
    text_char_threshold: int = 500
    code_line_threshold: int = 10
    image_count_threshold: int = 2
```

- [ ] **Step 5: Implement sections.py**

```python
# packages/ai-parrot/src/parrot/outputs/cards/sections.py
"""Composable semantic sections for CardSpec."""
from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel

from .elements import ACElement
from .inputs import InputChoice
from .toggle import ToggleGroup


class CardSection(BaseModel):
    section_type: str
    spacing: Literal["None", "Small", "Default", "Medium",
                     "Large", "ExtraLarge", "Padding"] | None = None
    separator: bool = False


class TextSection(CardSection):
    section_type: Literal["text"] = "text"
    text: str
    role: Literal["body", "title", "heading", "subtitle",
                   "label", "code", "monospace"] = "body"
    color: str | None = None
    is_subtle: bool = False


class TableSection(CardSection):
    section_type: Literal["table"] = "table"
    columns: list[str]
    rows: list[list[str]]
    total_rows: int | None = None
    max_display_rows: int = 20
    show_grid_lines: bool = True
    first_row_as_header: bool = True


class MetricEntry(BaseModel):
    label: str
    value: str
    delta: str | None = None


class MetricsSection(CardSection):
    section_type: Literal["metrics"] = "metrics"
    metrics: list[MetricEntry] = []


class DetailField(BaseModel):
    label: str
    value: str


class DetailSection(CardSection):
    section_type: Literal["detail"] = "detail"
    fields: list[DetailField] = []


class ImageEntry(BaseModel):
    url: str
    alt_text: str = ""
    size: Literal["Auto", "Stretch", "Small", "Medium", "Large"] = "Large"


class ImageSection(CardSection):
    section_type: Literal["image"] = "image"
    images: list[ImageEntry] = []


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


class FormFieldSpec(BaseModel):
    field_id: str
    field_type: str
    label: str
    description: str | None = None
    placeholder: str | None = None
    required: bool = False
    default: Any = None
    options: list[InputChoice] | None = None
    constraints: dict[str, Any] | None = None
    is_multiline: bool = False


class FormSection(CardSection):
    section_type: Literal["form"] = "form"
    fields: list[FormFieldSpec] = []


class RawElementsSection(CardSection):
    section_type: Literal["raw"] = "raw"
    elements: list[ACElement] = []
```

- [ ] **Step 6: Implement spec.py**

```python
# packages/ai-parrot/src/parrot/outputs/cards/spec.py
"""CardSpec — top-level Adaptive Card specification."""
from __future__ import annotations

from pydantic import BaseModel

from .actions import ACAction
from .sections import CardSection
from .toggle import AutoCollapsePolicy


class CardSpec(BaseModel):
    title: str | None = None
    summary: str | None = None
    sections: list[CardSection] = []
    actions: list[ACAction] = []
    auto_collapse: AutoCollapsePolicy | None = None
    version: str = "1.5"
    schema_url: str = "http://adaptivecards.io/schemas/adaptive-card.json"
```

- [ ] **Step 7: Run tests to verify they pass**

```bash
pytest packages/ai-parrot/tests/unit/outputs/cards/test_toggle.py \
       packages/ai-parrot/tests/unit/outputs/cards/test_sections.py -v
```

Expected: All PASS.

- [ ] **Step 8: Commit**

```bash
git add packages/ai-parrot/src/parrot/outputs/cards/toggle.py \
       packages/ai-parrot/src/parrot/outputs/cards/sections.py \
       packages/ai-parrot/src/parrot/outputs/cards/spec.py \
       packages/ai-parrot/tests/unit/outputs/cards/test_toggle.py \
       packages/ai-parrot/tests/unit/outputs/cards/test_sections.py
git commit -m "feat(cards): toggle, sections, and CardSpec models — complete declarative layer"
```

---

### Task 4: Renderer — Section Expanders and Serialization

**Files:**
- Create: `packages/ai-parrot/src/parrot/outputs/cards/renderer.py`
- Test: `packages/ai-parrot/tests/unit/outputs/cards/test_renderer.py`

**Interfaces:**
- Consumes: all models from Tasks 1-3 (`CardSpec`, all sections, all elements, all actions)
- Produces: `render(spec: CardSpec) -> dict[str, Any]`, `render_text(spec: CardSpec) -> str`, `CardRenderError`

- [ ] **Step 1: Write failing tests for the renderer**

```python
# tests/unit/outputs/cards/test_renderer.py
"""Unit tests for the CardSpec renderer."""
import json

import pytest


class TestRenderTextSection:
    def test_simple_text(self):
        from parrot.outputs.cards.renderer import render
        from parrot.outputs.cards.sections import TextSection
        from parrot.outputs.cards.spec import CardSpec
        spec = CardSpec(sections=[TextSection(text="Hello world")])
        card = render(spec)
        assert card["type"] == "AdaptiveCard"
        assert card["version"] == "1.5"
        assert card["$schema"] == "http://adaptivecards.io/schemas/adaptive-card.json"
        body = card["body"]
        assert len(body) == 1
        assert body[0]["type"] == "TextBlock"
        assert body[0]["text"] == "Hello world"
        assert body[0]["wrap"] is True

    def test_title_role(self):
        from parrot.outputs.cards.renderer import render
        from parrot.outputs.cards.sections import TextSection
        from parrot.outputs.cards.spec import CardSpec
        spec = CardSpec(sections=[TextSection(text="Title", role="title")])
        card = render(spec)
        tb = card["body"][0]
        assert tb["size"] == "Large"
        assert tb["weight"] == "Bolder"

    def test_monospace_role(self):
        from parrot.outputs.cards.renderer import render
        from parrot.outputs.cards.sections import TextSection
        from parrot.outputs.cards.spec import CardSpec
        spec = CardSpec(sections=[TextSection(text="code", role="monospace")])
        card = render(spec)
        assert card["body"][0]["fontType"] == "Monospace"


class TestRenderTableSection:
    def test_native_table(self):
        from parrot.outputs.cards.renderer import render
        from parrot.outputs.cards.sections import TableSection
        from parrot.outputs.cards.spec import CardSpec
        spec = CardSpec(sections=[TableSection(
            columns=["Name", "Age"],
            rows=[["Alice", "30"], ["Bob", "25"]],
        )])
        card = render(spec)
        tables = [e for e in card["body"] if e["type"] == "Table"]
        assert len(tables) == 1
        table = tables[0]
        assert table["firstRowAsHeader"] is True
        assert len(table["columns"]) == 2
        # Header row + 2 data rows
        assert len(table["rows"]) == 3

    def test_truncation_note(self):
        from parrot.outputs.cards.renderer import render
        from parrot.outputs.cards.sections import TableSection
        from parrot.outputs.cards.spec import CardSpec
        spec = CardSpec(sections=[TableSection(
            columns=["X"],
            rows=[[str(i)] for i in range(30)],
            total_rows=50,
            max_display_rows=20,
        )])
        card = render(spec)
        texts = [e for e in card["body"] if e["type"] == "TextBlock"]
        assert any("50" in t["text"] for t in texts)

    def test_ragged_rows_normalized(self):
        from parrot.outputs.cards.renderer import render
        from parrot.outputs.cards.sections import TableSection
        from parrot.outputs.cards.spec import CardSpec
        spec = CardSpec(sections=[TableSection(
            columns=["a", "b", "c"],
            rows=[["1"], ["1", "2", "3", "4"]],
        )])
        card = render(spec)
        table = [e for e in card["body"] if e["type"] == "Table"][0]
        for row in table["rows"]:
            assert len(row["cells"]) == 3


class TestRenderMetricsSection:
    def test_factset_output(self):
        from parrot.outputs.cards.renderer import render
        from parrot.outputs.cards.sections import MetricEntry, MetricsSection
        from parrot.outputs.cards.spec import CardSpec
        spec = CardSpec(sections=[MetricsSection(metrics=[
            MetricEntry(label="Rev", value="$1M", delta="+12%"),
        ])])
        card = render(spec)
        factsets = [e for e in card["body"] if e["type"] == "FactSet"]
        assert len(factsets) == 1
        assert factsets[0]["facts"][0]["title"] == "Rev"
        assert "+12%" in factsets[0]["facts"][0]["value"]


class TestRenderDetailSection:
    def test_factset_output(self):
        from parrot.outputs.cards.renderer import render
        from parrot.outputs.cards.sections import DetailField, DetailSection
        from parrot.outputs.cards.spec import CardSpec
        spec = CardSpec(sections=[DetailSection(fields=[
            DetailField(label="Status", value="Active"),
        ])])
        card = render(spec)
        factsets = [e for e in card["body"] if e["type"] == "FactSet"]
        assert factsets[0]["facts"][0]["value"] == "Active"


class TestRenderImageSection:
    def test_url_image(self):
        from parrot.outputs.cards.renderer import render
        from parrot.outputs.cards.sections import ImageEntry, ImageSection
        from parrot.outputs.cards.spec import CardSpec
        spec = CardSpec(sections=[ImageSection(images=[
            ImageEntry(url="https://example.com/chart.png", alt_text="chart"),
        ])])
        card = render(spec)
        images = [e for e in card["body"] if e["type"] == "Image"]
        assert len(images) == 1
        assert images[0]["url"] == "https://example.com/chart.png"
        assert images[0]["altText"] == "chart"


class TestRenderCodeSection:
    def test_monospace_block(self):
        from parrot.outputs.cards.renderer import render
        from parrot.outputs.cards.sections import CodeSection
        from parrot.outputs.cards.spec import CardSpec
        spec = CardSpec(sections=[CodeSection(
            code="print('hi')", language="python", label="Code (python):",
        )])
        card = render(spec)
        texts = [e for e in card["body"] if e["type"] == "TextBlock"]
        label = [t for t in texts if "Code" in t["text"]]
        code = [t for t in texts if t.get("fontType") == "Monospace"]
        assert len(label) == 1
        assert len(code) == 1
        assert code[0]["text"] == "print('hi')"


class TestRenderStatusSection:
    def test_colored_status(self):
        from parrot.outputs.cards.renderer import render
        from parrot.outputs.cards.sections import StatusSection
        from parrot.outputs.cards.spec import CardSpec
        spec = CardSpec(sections=[StatusSection(
            level="error", message="Failed", details="Timeout",
        )])
        card = render(spec)
        container = [e for e in card["body"] if e["type"] == "Container"][0]
        msg = container["items"][0]
        assert msg["color"] == "Attention"
        assert msg["text"] == "Failed"


class TestRenderFormSection:
    def test_input_elements(self):
        from parrot.outputs.cards.renderer import render
        from parrot.outputs.cards.sections import FormFieldSpec, FormSection
        from parrot.outputs.cards.spec import CardSpec
        spec = CardSpec(sections=[FormSection(fields=[
            FormFieldSpec(field_id="name", field_type="text", label="Name", required=True),
            FormFieldSpec(field_id="age", field_type="number", label="Age"),
        ])])
        card = render(spec)
        inputs = [e for e in card["body"] if e["type"].startswith("Input.")]
        assert len(inputs) == 2
        assert inputs[0]["type"] == "Input.Text"
        assert inputs[0]["id"] == "name"
        assert inputs[0]["isRequired"] is True
        assert inputs[1]["type"] == "Input.Number"


class TestRenderToggleSection:
    def test_explicit_toggle(self):
        from parrot.outputs.cards.elements import TextBlock
        from parrot.outputs.cards.renderer import render
        from parrot.outputs.cards.sections import ToggleSection
        from parrot.outputs.cards.spec import CardSpec
        from parrot.outputs.cards.toggle import ToggleGroup
        spec = CardSpec(sections=[ToggleSection(toggle=ToggleGroup(
            content=[TextBlock(text="hidden content")],
            group_id="detail",
        ))])
        card = render(spec)
        containers = [e for e in card["body"] if e["type"] == "Container"]
        assert any(c.get("id") == "detail_content" for c in containers)
        assert any(c.get("isVisible") is False for c in containers)
        toggle_actions = [a for a in card.get("actions", [])
                         if a["type"] == "Action.ToggleVisibility"]
        assert len(toggle_actions) == 1


class TestRenderRawSection:
    def test_passthrough(self):
        from parrot.outputs.cards.elements import TextBlock
        from parrot.outputs.cards.renderer import render
        from parrot.outputs.cards.sections import RawElementsSection
        from parrot.outputs.cards.spec import CardSpec
        spec = CardSpec(sections=[RawElementsSection(
            elements=[TextBlock(text="raw element", weight="Bolder")],
        )])
        card = render(spec)
        assert card["body"][0]["type"] == "TextBlock"
        assert card["body"][0]["weight"] == "Bolder"


class TestRenderActions:
    def test_submit_and_openurl(self):
        from parrot.outputs.cards.actions import ActionOpenUrl, ActionSubmit
        from parrot.outputs.cards.renderer import render
        from parrot.outputs.cards.spec import CardSpec
        spec = CardSpec(actions=[
            ActionSubmit(title="OK", data={"x": 1}),
            ActionOpenUrl(title="Docs", url="https://docs.example.com"),
        ])
        card = render(spec)
        assert len(card["actions"]) == 2
        assert card["actions"][0]["type"] == "Action.Submit"
        assert card["actions"][1]["type"] == "Action.OpenUrl"


class TestRenderCardSpec:
    def test_title_and_summary(self):
        from parrot.outputs.cards.renderer import render
        from parrot.outputs.cards.spec import CardSpec
        spec = CardSpec(title="Report", summary="Q2 data")
        card = render(spec)
        texts = [e for e in card["body"] if e["type"] == "TextBlock"]
        titles = [t for t in texts if t.get("weight") == "Bolder"]
        assert any("Report" in t["text"] for t in titles)
        assert any("Q2 data" in t["text"] for t in texts)

    def test_omits_none_values(self):
        from parrot.outputs.cards.renderer import render
        from parrot.outputs.cards.sections import TextSection
        from parrot.outputs.cards.spec import CardSpec
        spec = CardSpec(sections=[TextSection(text="clean")])
        card = render(spec)
        tb = card["body"][0]
        assert "color" not in tb
        assert "fontType" not in tb
        assert "maxLines" not in tb
        assert "id" not in tb

    def test_size_guard(self):
        from parrot.outputs.cards.renderer import CardRenderError, render
        from parrot.outputs.cards.sections import TextSection
        from parrot.outputs.cards.spec import CardSpec
        huge = TextSection(text="x" * 30_000)
        spec = CardSpec(sections=[huge])
        with pytest.raises(CardRenderError):
            render(spec, max_card_bytes=1_000)


class TestRenderText:
    def test_fallback(self):
        from parrot.outputs.cards.renderer import render_text
        from parrot.outputs.cards.sections import MetricEntry, MetricsSection, TextSection
        from parrot.outputs.cards.spec import CardSpec
        spec = CardSpec(
            title="Report",
            sections=[
                TextSection(text="Overview"),
                MetricsSection(metrics=[MetricEntry(label="Rev", value="$1M")]),
            ],
        )
        text = render_text(spec)
        assert "Report" in text
        assert "Overview" in text
        assert "Rev" in text
        assert "$1M" in text
```

- [ ] **Step 2: Run tests to verify they fail**

```bash
pytest packages/ai-parrot/tests/unit/outputs/cards/test_renderer.py -v
```

Expected: `ModuleNotFoundError: No module named 'parrot.outputs.cards.renderer'`

- [ ] **Step 3: Implement renderer.py**

This is the largest single file. Key internal functions:

```python
# packages/ai-parrot/src/parrot/outputs/cards/renderer.py
"""CardSpec → Adaptive Card 1.5 JSON renderer."""
from __future__ import annotations

import json
import logging
from typing import Any

from .actions import (
    ACAction,
    ActionOpenUrl,
    ActionShowCard,
    ActionSubmit,
    ActionToggleVisibility,
)
from .elements import (
    ACElement,
    Column,
    ColumnSet,
    Container,
    Fact,
    FactSet,
    Image,
    Table,
    TableCell,
    TableColumnDefinition,
    TableRow,
    TextBlock,
)
from .inputs import (
    InputChoiceSet,
    InputDate,
    InputNumber,
    InputText,
    InputTime,
    InputToggle,
)
from .sections import (
    CardSection,
    CodeSection,
    DetailSection,
    FormFieldSpec,
    FormSection,
    ImageSection,
    MetricsSection,
    RawElementsSection,
    StatusSection,
    TableSection,
    TextSection,
    ToggleSection,
)
from .spec import CardSpec
from .toggle import AutoCollapsePolicy, ToggleGroup

logger = logging.getLogger(__name__)

_LEVEL_TO_COLOR = {
    "success": "Good",
    "warning": "Warning",
    "error": "Attention",
    "info": "Default",
}

_FIELD_TYPE_TO_INPUT = {
    "text": "Input.Text",
    "text_area": "Input.Text",
    "number": "Input.Number",
    "integer": "Input.Number",
    "boolean": "Input.Toggle",
    "date": "Input.Date",
    "datetime": "Input.Date",
    "time": "Input.Time",
    "select": "Input.ChoiceSet",
    "multi_select": "Input.ChoiceSet",
    "email": "Input.Text",
    "url": "Input.Text",
    "phone": "Input.Text",
    "password": "Input.Text",
    "color": "Input.Text",
    "hidden": "Input.Text",
}

# snake_case → camelCase mapping for AC JSON serialization.
# Only non-trivial mappings listed; the serializer handles
# the generic snake→camel conversion for unlisted keys.
_FIELD_RENAMES: dict[str, str] = {
    "element_type": "type",
    "action_type": "type",
    "alt_text": "altText",
    "font_type": "fontType",
    "is_subtle": "isSubtle",
    "is_visible": "isVisible",
    "is_required": "isRequired",
    "is_multiline": "isMultiline",
    "is_multi_select": "isMultiSelect",
    "horizontal_alignment": "horizontalAlignment",
    "vertical_cell_content_alignment": "verticalCellContentAlignment",
    "horizontal_cell_content_alignment": "horizontalCellContentAlignment",
    "max_lines": "maxLines",
    "max_length": "maxLength",
    "first_row_as_header": "firstRowAsHeader",
    "show_grid_lines": "showGridLines",
    "grid_style": "gridStyle",
    "error_message": "errorMessage",
    "value_on": "valueOn",
    "value_off": "valueOff",
    "associated_inputs": "associatedInputs",
    "target_elements": "targetElements",
    "element_id": "elementId",
    "schema_url": "$schema",
}


class CardRenderError(Exception):
    """Raised when a CardSpec cannot be rendered within limits."""


# ── Section expanders ─────────────────────────────────────────────────

def _expand_text(section: TextSection) -> tuple[list[ACElement], list[ACAction]]:
    kwargs: dict[str, Any] = {}
    if section.role == "title":
        kwargs.update(size="Large", weight="Bolder")
    elif section.role in ("heading", "subtitle", "label"):
        kwargs["weight"] = "Bolder"
    elif section.role in ("code", "monospace"):
        kwargs["font_type"] = "Monospace"
    if section.color:
        kwargs["color"] = section.color
    if section.is_subtle:
        kwargs["is_subtle"] = True
    return [TextBlock(text=section.text, **kwargs)], []


def _expand_table(section: TableSection) -> tuple[list[ACElement], list[ACAction]]:
    n_cols = len(section.columns)
    col_defs = [TableColumnDefinition(width="1") for _ in section.columns]

    header_cells = [TableCell(items=[TextBlock(text=c, weight="Bolder")])
                    for c in section.columns]
    rows = [TableRow(cells=header_cells)]

    display_rows = section.rows[:section.max_display_rows]
    for row_data in display_rows:
        cells_data = [str(c) for c in row_data[:n_cols]]
        cells_data += [""] * (n_cols - len(cells_data))
        rows.append(TableRow(cells=[
            TableCell(items=[TextBlock(text=cell)]) for cell in cells_data
        ]))

    elements: list[ACElement] = [Table(
        columns=col_defs,
        rows=rows,
        first_row_as_header=section.first_row_as_header,
        show_grid_lines=section.show_grid_lines,
    )]

    total = section.total_rows if section.total_rows is not None else len(section.rows)
    if total > len(display_rows):
        elements.append(TextBlock(
            text=f"Showing {len(display_rows)} of {total}",
            is_subtle=True,
        ))
    return elements, []


def _expand_metrics(section: MetricsSection) -> tuple[list[ACElement], list[ACAction]]:
    facts = []
    for m in section.metrics:
        value = m.value
        if m.delta:
            value = f"{value} ({m.delta})"
        facts.append(Fact(title=m.label, value=value))
    return [FactSet(facts=facts)], []


def _expand_detail(section: DetailSection) -> tuple[list[ACElement], list[ACAction]]:
    facts = [Fact(title=f.label, value=f.value) for f in section.fields]
    return [FactSet(facts=facts)], []


def _expand_image(section: ImageSection) -> tuple[list[ACElement], list[ACAction]]:
    elements = [
        Image(url=img.url, alt_text=img.alt_text, size=img.size,
              horizontal_alignment="Center")
        for img in section.images
    ]
    return elements, []


def _expand_code(section: CodeSection) -> tuple[list[ACElement], list[ACAction]]:
    elements: list[ACElement] = []
    if section.label:
        elements.append(TextBlock(text=section.label, weight="Bolder", spacing="Medium"))
    elements.append(TextBlock(text=section.code, font_type="Monospace", spacing="Small"))
    return elements, []


def _expand_status(section: StatusSection) -> tuple[list[ACElement], list[ACAction]]:
    items: list[ACElement] = [
        TextBlock(
            text=section.message,
            weight="Bolder",
            color=_LEVEL_TO_COLOR.get(section.level, "Default"),
        ),
    ]
    if section.details:
        items.append(TextBlock(text=section.details))
    return [Container(items=items)], []


def _expand_toggle(section: ToggleSection) -> tuple[list[ACElement], list[ACAction]]:
    tg = section.toggle
    group_id = tg.group_id or "tg_0"
    container_id = f"{group_id}_content"

    container = Container(
        id=container_id,
        items=[_serialize_to_element(e) if not isinstance(e, ACElement) else e
               for e in tg.content],
        is_visible=tg.initially_visible,
    )
    action = ActionToggleVisibility(
        title=tg.label_collapsed if not tg.initially_visible else tg.label_expanded,
        target_elements=[__import__("parrot.outputs.cards.actions",
                                     fromlist=["TargetElement"]).TargetElement(
            element_id=container_id,
        )],
    )
    return [container], [action]


def _expand_form(section: FormSection) -> tuple[list[ACElement], list[ACAction]]:
    elements: list[ACElement] = []
    for field in section.fields:
        elements.extend(_build_form_field(field))
    return elements, []


def _build_form_field(field: FormFieldSpec) -> list[ACElement]:
    elements: list[ACElement] = []
    input_type = _FIELD_TYPE_TO_INPUT.get(field.field_type, "Input.Text")

    if input_type == "Input.Text":
        kwargs: dict[str, Any] = {}
        if field.field_type == "email":
            kwargs["style"] = "Email"
        elif field.field_type == "url":
            kwargs["style"] = "Url"
        elif field.field_type == "password":
            kwargs["style"] = "Password"
        if field.field_type == "text_area":
            kwargs["is_multiline"] = True
        elif field.is_multiline:
            kwargs["is_multiline"] = True
        if field.constraints and field.constraints.get("max_length"):
            kwargs["max_length"] = field.constraints["max_length"]
        if field.constraints and field.constraints.get("pattern"):
            kwargs["regex"] = field.constraints["pattern"]
        elements.append(InputText(
            id=field.field_id,
            label=field.label,
            placeholder=field.placeholder or "",
            value=str(field.default) if field.default is not None else "",
            is_required=field.required,
            **kwargs,
        ))
    elif input_type == "Input.Number":
        kwargs = {}
        if field.constraints:
            if field.constraints.get("min_value") is not None:
                kwargs["min"] = field.constraints["min_value"]
            if field.constraints.get("max_value") is not None:
                kwargs["max"] = field.constraints["max_value"]
        elements.append(InputNumber(
            id=field.field_id,
            label=field.label,
            placeholder=field.placeholder or "",
            value=field.default,
            is_required=field.required,
            **kwargs,
        ))
    elif input_type == "Input.Toggle":
        elements.append(InputToggle(
            id=field.field_id,
            title=field.description or field.label,
            label=field.label,
            value="true" if field.default else "false",
            is_required=field.required,
        ))
    elif input_type == "Input.Date":
        elements.append(InputDate(
            id=field.field_id,
            label=field.label,
            value=str(field.default) if field.default else None,
            is_required=field.required,
        ))
    elif input_type == "Input.Time":
        elements.append(InputTime(
            id=field.field_id,
            label=field.label,
            value=str(field.default) if field.default else None,
            is_required=field.required,
        ))
    elif input_type == "Input.ChoiceSet":
        choices = []
        if field.options:
            from .inputs import InputChoice
            choices = [InputChoice(title=o.title, value=o.value) for o in field.options]
        is_multi = field.field_type == "multi_select"
        elements.append(InputChoiceSet(
            id=field.field_id,
            label=field.label,
            choices=choices,
            value=str(field.default) if field.default else None,
            is_multi_select=is_multi,
            style="expanded" if is_multi else "compact",
            is_required=field.required,
        ))
    return elements


def _expand_raw(section: RawElementsSection) -> tuple[list[ACElement], list[ACAction]]:
    return list(section.elements), []


_SECTION_EXPANDERS: dict[str, Any] = {
    "text": _expand_text,
    "table": _expand_table,
    "metrics": _expand_metrics,
    "detail": _expand_detail,
    "image": _expand_image,
    "code": _expand_code,
    "status": _expand_status,
    "toggle": _expand_toggle,
    "form": _expand_form,
    "raw": _expand_raw,
}


def _serialize_to_element(obj: Any) -> ACElement:
    if isinstance(obj, ACElement):
        return obj
    return TextBlock(text=str(obj))


# ── Serialization ─────────────────────────────────────────────────────

def _snake_to_camel(name: str) -> str:
    parts = name.split("_")
    return parts[0] + "".join(p.capitalize() for p in parts[1:])


def _serialize_element(element: ACElement) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for field_name, field_info in element.model_fields.items():
        value = getattr(element, field_name)
        if value is None:
            continue
        if value == field_info.default and field_name not in ("element_type", "text", "url",
                                                                "id", "title", "facts",
                                                                "columns", "rows", "items",
                                                                "cells", "choices"):
            continue
        ac_key = _FIELD_RENAMES.get(field_name, _snake_to_camel(field_name))
        if isinstance(value, list):
            serialized_list = []
            for item in value:
                if isinstance(item, ACElement):
                    serialized_list.append(_serialize_element(item))
                elif isinstance(item, BaseModel):
                    serialized_list.append(_serialize_model(item))
                else:
                    serialized_list.append(item)
            if serialized_list or field_name in ("items", "columns", "rows",
                                                  "cells", "facts", "choices"):
                result[ac_key] = serialized_list
        elif isinstance(value, ACElement):
            result[ac_key] = _serialize_element(value)
        elif isinstance(value, BaseModel):
            result[ac_key] = _serialize_model(value)
        else:
            result[ac_key] = value
    return result


def _serialize_model(model: BaseModel) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for field_name in model.model_fields:
        value = getattr(model, field_name)
        if value is None:
            continue
        ac_key = _FIELD_RENAMES.get(field_name, _snake_to_camel(field_name))
        if isinstance(value, list):
            result[ac_key] = [
                _serialize_element(v) if isinstance(v, ACElement)
                else _serialize_model(v) if isinstance(v, BaseModel)
                else v
                for v in value
            ]
        elif isinstance(value, ACElement):
            result[ac_key] = _serialize_element(value)
        elif isinstance(value, BaseModel):
            result[ac_key] = _serialize_model(value)
        else:
            result[ac_key] = value
    return result


def _serialize_action(action: ACAction) -> dict[str, Any]:
    result: dict[str, Any] = {"type": action.action_type, "title": action.title}
    if action.style and action.style != "default":
        result["style"] = action.style
    if isinstance(action, ActionSubmit):
        if action.data:
            result["data"] = action.data
        if action.associated_inputs:
            result["associatedInputs"] = action.associated_inputs
    elif isinstance(action, ActionOpenUrl):
        result["url"] = action.url
    elif isinstance(action, ActionToggleVisibility):
        result["targetElements"] = [
            {"elementId": t.element_id, **({"isVisible": t.is_visible}
                                            if t.is_visible is not None else {})}
            for t in action.target_elements
        ]
    elif isinstance(action, ActionShowCard):
        result["card"] = render(action.card)
    return result


# Need BaseModel import for isinstance checks in serialization
from pydantic import BaseModel  # noqa: E402


# ── Public API ────────────────────────────────────────────────────────

def render(spec: CardSpec, *, max_card_bytes: int = 28_000) -> dict[str, Any]:
    body: list[dict[str, Any]] = []
    all_actions: list[ACAction] = list(spec.actions)

    # Title and summary
    if spec.title:
        body.append(_serialize_element(TextBlock(
            text=spec.title, weight="Bolder", size="Large",
        )))
    if spec.summary:
        body.append(_serialize_element(TextBlock(text=spec.summary)))

    # Expand sections
    toggle_counter = 0
    for section in spec.sections:
        expander = _SECTION_EXPANDERS.get(section.section_type)
        if expander is None:
            logger.warning("Unknown section type: %s", section.section_type)
            continue

        if isinstance(section, ToggleSection) and section.toggle.group_id is None:
            section.toggle.group_id = f"tg_{toggle_counter}"
            toggle_counter += 1

        elements, actions = expander(section)
        for element in elements:
            serialized = _serialize_element(element)
            if section.separator and not body:
                pass
            elif section.separator:
                serialized["separator"] = True
            if section.spacing:
                serialized["spacing"] = section.spacing
            body.append(serialized)
        all_actions.extend(actions)

    card: dict[str, Any] = {
        "$schema": spec.schema_url,
        "type": "AdaptiveCard",
        "version": spec.version,
        "body": body,
    }
    if all_actions:
        card["actions"] = [_serialize_action(a) for a in all_actions]

    serialized_size = len(json.dumps(card).encode("utf-8"))
    if serialized_size > max_card_bytes:
        raise CardRenderError(
            f"card size {serialized_size} exceeds max_card_bytes={max_card_bytes}"
        )
    return card


def render_text(spec: CardSpec) -> str:
    try:
        lines: list[str] = []
        if spec.title:
            lines.append(f"**{spec.title}**")
        if spec.summary:
            lines.append(spec.summary)
        for section in spec.sections:
            if isinstance(section, TextSection):
                lines.append(section.text)
            elif isinstance(section, TableSection):
                if section.columns:
                    lines.append(" | ".join(section.columns))
                    for row in section.rows[:section.max_display_rows]:
                        lines.append(" | ".join(str(c) for c in row))
            elif isinstance(section, MetricsSection):
                for m in section.metrics:
                    text = f"{m.label}: {m.value}"
                    if m.delta:
                        text += f" ({m.delta})"
                    lines.append(text)
            elif isinstance(section, DetailSection):
                for f in section.fields:
                    lines.append(f"{f.label}: {f.value}")
            elif isinstance(section, StatusSection):
                lines.append(f"[{section.level.upper()}] {section.message}")
                if section.details:
                    lines.append(section.details)
            elif isinstance(section, CodeSection):
                if section.label:
                    lines.append(section.label)
                lines.append(f"```{section.language or ''}\n{section.code}\n```")
            elif isinstance(section, ImageSection):
                for img in section.images:
                    lines.append(f"[Image: {img.alt_text or img.url}]")
        return "\n".join(lines)
    except Exception:
        return "Unable to render result."
```

- [ ] **Step 4: Run tests to verify they pass**

```bash
pytest packages/ai-parrot/tests/unit/outputs/cards/test_renderer.py -v
```

Expected: All PASS.

- [ ] **Step 5: Commit**

```bash
git add packages/ai-parrot/src/parrot/outputs/cards/renderer.py \
       packages/ai-parrot/tests/unit/outputs/cards/test_renderer.py
git commit -m "feat(cards): renderer — section expanders, AC 1.5 serialization, size guard, text fallback"
```

---

### Task 5: Auto-Collapse and Attachment Helper

**Files:**
- Modify: `packages/ai-parrot/src/parrot/outputs/cards/renderer.py` (add auto-collapse stage)
- Create: `packages/ai-parrot/src/parrot/outputs/cards/attachment.py`
- Test: `packages/ai-parrot/tests/unit/outputs/cards/test_renderer_auto_collapse.py`
- Test: `packages/ai-parrot/tests/unit/outputs/cards/test_attachment.py`

**Interfaces:**
- Consumes: `render()` from Task 4, `AutoCollapsePolicy` from Task 3
- Produces: auto-collapse behavior in `render()` when `spec.auto_collapse` is set; `build_attachment(card: dict) -> dict`, `build_attachment_from_spec(spec: CardSpec) -> dict`

- [ ] **Step 1: Write failing tests for auto-collapse**

```python
# tests/unit/outputs/cards/test_renderer_auto_collapse.py
"""Unit tests for auto-collapse behavior in the renderer."""
import pytest


class TestAutoCollapseTable:
    def test_table_exceeding_threshold_gets_toggle(self):
        from parrot.outputs.cards.renderer import render
        from parrot.outputs.cards.sections import TableSection
        from parrot.outputs.cards.spec import CardSpec
        from parrot.outputs.cards.toggle import AutoCollapsePolicy
        spec = CardSpec(
            sections=[TableSection(
                columns=["X"],
                rows=[[str(i)] for i in range(20)],
                max_display_rows=20,
            )],
            auto_collapse=AutoCollapsePolicy(table_row_threshold=5),
        )
        card = render(spec)
        # Should have a toggle action for the overflow
        toggle_actions = [a for a in card.get("actions", [])
                         if a["type"] == "Action.ToggleVisibility"]
        assert len(toggle_actions) >= 1
        # Should have a hidden container with the overflow rows
        containers = [e for e in card["body"] if e.get("type") == "Container"
                     and e.get("isVisible") is False]
        assert len(containers) >= 1

    def test_table_under_threshold_no_toggle(self):
        from parrot.outputs.cards.renderer import render
        from parrot.outputs.cards.sections import TableSection
        from parrot.outputs.cards.spec import CardSpec
        from parrot.outputs.cards.toggle import AutoCollapsePolicy
        spec = CardSpec(
            sections=[TableSection(columns=["X"], rows=[["1"], ["2"]])],
            auto_collapse=AutoCollapsePolicy(table_row_threshold=5),
        )
        card = render(spec)
        toggle_actions = [a for a in card.get("actions", [])
                         if a["type"] == "Action.ToggleVisibility"]
        assert len(toggle_actions) == 0


class TestAutoCollapseText:
    def test_long_text_gets_toggle(self):
        from parrot.outputs.cards.renderer import render
        from parrot.outputs.cards.sections import TextSection
        from parrot.outputs.cards.spec import CardSpec
        from parrot.outputs.cards.toggle import AutoCollapsePolicy
        spec = CardSpec(
            sections=[TextSection(text="word " * 200)],
            auto_collapse=AutoCollapsePolicy(text_char_threshold=100),
        )
        card = render(spec)
        toggle_actions = [a for a in card.get("actions", [])
                         if a["type"] == "Action.ToggleVisibility"]
        assert len(toggle_actions) >= 1

    def test_short_text_no_toggle(self):
        from parrot.outputs.cards.renderer import render
        from parrot.outputs.cards.sections import TextSection
        from parrot.outputs.cards.spec import CardSpec
        from parrot.outputs.cards.toggle import AutoCollapsePolicy
        spec = CardSpec(
            sections=[TextSection(text="short")],
            auto_collapse=AutoCollapsePolicy(text_char_threshold=100),
        )
        card = render(spec)
        toggle_actions = [a for a in card.get("actions", [])
                         if a["type"] == "Action.ToggleVisibility"]
        assert len(toggle_actions) == 0


class TestAutoCollapseCode:
    def test_long_code_gets_toggle(self):
        from parrot.outputs.cards.renderer import render
        from parrot.outputs.cards.sections import CodeSection
        from parrot.outputs.cards.spec import CardSpec
        from parrot.outputs.cards.toggle import AutoCollapsePolicy
        code = "\n".join(f"line {i}" for i in range(20))
        spec = CardSpec(
            sections=[CodeSection(code=code)],
            auto_collapse=AutoCollapsePolicy(code_line_threshold=5),
        )
        card = render(spec)
        toggle_actions = [a for a in card.get("actions", [])
                         if a["type"] == "Action.ToggleVisibility"]
        assert len(toggle_actions) >= 1


class TestAutoCollapseDisabled:
    def test_disabled_no_toggles(self):
        from parrot.outputs.cards.renderer import render
        from parrot.outputs.cards.sections import TextSection
        from parrot.outputs.cards.spec import CardSpec
        from parrot.outputs.cards.toggle import AutoCollapsePolicy
        spec = CardSpec(
            sections=[TextSection(text="word " * 200)],
            auto_collapse=AutoCollapsePolicy(enabled=False),
        )
        card = render(spec)
        toggle_actions = [a for a in card.get("actions", [])
                         if a["type"] == "Action.ToggleVisibility"]
        assert len(toggle_actions) == 0
```

- [ ] **Step 2: Write failing tests for attachment helper**

```python
# tests/unit/outputs/cards/test_attachment.py
"""Unit tests for attachment helper."""


class TestBuildAttachment:
    def test_wraps_card(self):
        from parrot.outputs.cards.attachment import build_attachment
        card = {"type": "AdaptiveCard", "version": "1.5", "body": []}
        att = build_attachment(card)
        assert att["contentType"] == "application/vnd.microsoft.card.adaptive"
        assert att["content"] is card

    def test_from_spec(self):
        from parrot.outputs.cards.attachment import build_attachment_from_spec
        from parrot.outputs.cards.spec import CardSpec
        spec = CardSpec(title="Test")
        att = build_attachment_from_spec(spec)
        assert att["contentType"] == "application/vnd.microsoft.card.adaptive"
        assert att["content"]["type"] == "AdaptiveCard"
```

- [ ] **Step 3: Run tests to verify they fail**

```bash
pytest packages/ai-parrot/tests/unit/outputs/cards/test_renderer_auto_collapse.py \
       packages/ai-parrot/tests/unit/outputs/cards/test_attachment.py -v
```

Expected: auto-collapse tests fail (no auto-collapse logic yet); attachment tests fail (`ModuleNotFoundError`).

- [ ] **Step 4: Add auto-collapse stage to renderer.py**

Add `_apply_auto_collapse()` function to `renderer.py` and call it in `render()` between section expansion and serialization. The function inspects expanded sections and wraps oversized content in generated `ToggleGroup` instances:

- Table: splits rows at threshold, first N in a preview Table, remainder in a hidden Container with its own Table
- Text: truncates at char threshold with "..." preview, full in hidden Container
- Code: truncates at line threshold, preview first N lines, full in hidden Container
- Each auto-generated toggle gets ID `tg_auto_{counter}`

Integrate by calling `_apply_auto_collapse()` after all sections are expanded but before serialization, only when `spec.auto_collapse` is set and `spec.auto_collapse.enabled` is True.

- [ ] **Step 5: Implement attachment.py**

```python
# packages/ai-parrot/src/parrot/outputs/cards/attachment.py
"""Bot Framework attachment envelope helpers."""
from __future__ import annotations

from typing import Any

AC_CONTENT_TYPE = "application/vnd.microsoft.card.adaptive"


def build_attachment(card: dict[str, Any]) -> dict[str, Any]:
    return {"contentType": AC_CONTENT_TYPE, "content": card}


def build_attachment_from_spec(spec: Any) -> dict[str, Any]:
    from .renderer import render
    return build_attachment(render(spec))
```

- [ ] **Step 6: Run tests to verify they pass**

```bash
pytest packages/ai-parrot/tests/unit/outputs/cards/test_renderer_auto_collapse.py \
       packages/ai-parrot/tests/unit/outputs/cards/test_attachment.py -v
```

Expected: All PASS.

- [ ] **Step 7: Commit**

```bash
git add packages/ai-parrot/src/parrot/outputs/cards/renderer.py \
       packages/ai-parrot/src/parrot/outputs/cards/attachment.py \
       packages/ai-parrot/tests/unit/outputs/cards/test_renderer_auto_collapse.py \
       packages/ai-parrot/tests/unit/outputs/cards/test_attachment.py
git commit -m "feat(cards): auto-collapse stage + attachment envelope helper"
```

---

### Task 6: Markdown Parser

**Files:**
- Create: `packages/ai-parrot/src/parrot/outputs/cards/markdown.py`
- Test: `packages/ai-parrot/tests/unit/outputs/cards/test_markdown.py`

**Interfaces:**
- Consumes: `TextSection`, `TableSection`, `CodeSection`, `ImageSection` from `sections.py` (Task 3)
- Produces: `markdown_to_sections(text: str) -> list[CardSection]`

- [ ] **Step 1: Write failing tests**

```python
# tests/unit/outputs/cards/test_markdown.py
"""Unit tests for the markdown-to-sections parser."""
import pytest


class TestMarkdownToSections:
    def test_plain_text(self):
        from parrot.outputs.cards.markdown import markdown_to_sections
        from parrot.outputs.cards.sections import TextSection
        result = markdown_to_sections("Hello world")
        assert len(result) == 1
        assert isinstance(result[0], TextSection)
        assert result[0].text == "Hello world"

    def test_pipe_table(self):
        from parrot.outputs.cards.markdown import markdown_to_sections
        from parrot.outputs.cards.sections import TableSection
        md = "| Name | Age |\n| --- | --- |\n| Alice | 30 |\n| Bob | 25 |"
        result = markdown_to_sections(md)
        tables = [s for s in result if isinstance(s, TableSection)]
        assert len(tables) == 1
        assert tables[0].columns == ["Name", "Age"]
        assert len(tables[0].rows) == 2
        assert tables[0].rows[0] == ["Alice", "30"]

    def test_text_then_table_then_text(self):
        from parrot.outputs.cards.markdown import markdown_to_sections
        from parrot.outputs.cards.sections import TableSection, TextSection
        md = "Intro text\n\n| A | B |\n| - | - |\n| 1 | 2 |\n\nConclusion"
        result = markdown_to_sections(md)
        assert isinstance(result[0], TextSection)
        assert isinstance(result[1], TableSection)
        assert isinstance(result[2], TextSection)

    def test_fenced_code_block(self):
        from parrot.outputs.cards.markdown import markdown_to_sections
        from parrot.outputs.cards.sections import CodeSection
        md = "Before\n```python\nprint('hi')\n```\nAfter"
        result = markdown_to_sections(md)
        codes = [s for s in result if isinstance(s, CodeSection)]
        assert len(codes) == 1
        assert codes[0].code == "print('hi')"
        assert codes[0].language == "python"

    def test_image_reference(self):
        from parrot.outputs.cards.markdown import markdown_to_sections
        from parrot.outputs.cards.sections import ImageSection
        md = "Text\n![Chart](https://example.com/chart.png)\nMore text"
        result = markdown_to_sections(md)
        images = [s for s in result if isinstance(s, ImageSection)]
        assert len(images) == 1
        assert images[0].images[0].url == "https://example.com/chart.png"
        assert images[0].images[0].alt_text == "Chart"

    def test_empty_string(self):
        from parrot.outputs.cards.markdown import markdown_to_sections
        result = markdown_to_sections("")
        assert result == []

    def test_inline_markdown_preserved(self):
        from parrot.outputs.cards.markdown import markdown_to_sections
        from parrot.outputs.cards.sections import TextSection
        md = "This has **bold** and *italic* text"
        result = markdown_to_sections(md)
        assert len(result) == 1
        assert isinstance(result[0], TextSection)
        assert "**bold**" in result[0].text
```

- [ ] **Step 2: Run tests to verify they fail**

```bash
pytest packages/ai-parrot/tests/unit/outputs/cards/test_markdown.py -v
```

Expected: `ModuleNotFoundError`

- [ ] **Step 3: Implement markdown.py**

```python
# packages/ai-parrot/src/parrot/outputs/cards/markdown.py
"""Markdown text → list[CardSection] parser."""
from __future__ import annotations

import re

from .sections import (
    CardSection,
    CodeSection,
    ImageSection,
    ImageEntry,
    TableSection,
    TextSection,
)

_IMAGE_RE = re.compile(r'^!\[([^\]]*)\]\(([^)]+)\)\s*$')
_FENCE_OPEN_RE = re.compile(r'^```(\w*)\s*$')
_FENCE_CLOSE_RE = re.compile(r'^```\s*$')
_TABLE_ROW_RE = re.compile(r'^\|(.+)\|\s*$')
_TABLE_SEP_RE = re.compile(r'^[\s|:-]+$')


def markdown_to_sections(text: str) -> list[CardSection]:
    if not text or not text.strip():
        return []

    lines = text.split('\n')
    sections: list[CardSection] = []
    current_text: list[str] = []
    i = 0

    def flush_text():
        if current_text:
            joined = '\n'.join(current_text).strip()
            if joined:
                sections.append(TextSection(text=joined))
            current_text.clear()

    while i < len(lines):
        line = lines[i]
        stripped = line.strip()

        # Fenced code block
        fence_match = _FENCE_OPEN_RE.match(stripped)
        if fence_match and not stripped.endswith('```'):
            flush_text()
            language = fence_match.group(1) or None
            code_lines: list[str] = []
            i += 1
            while i < len(lines):
                if _FENCE_CLOSE_RE.match(lines[i].strip()):
                    break
                code_lines.append(lines[i])
                i += 1
            sections.append(CodeSection(code='\n'.join(code_lines), language=language))
            i += 1
            continue

        # Standalone image
        img_match = _IMAGE_RE.match(stripped)
        if img_match:
            flush_text()
            alt_text = img_match.group(1)
            url = img_match.group(2)
            sections.append(ImageSection(images=[ImageEntry(url=url, alt_text=alt_text)]))
            i += 1
            continue

        # Pipe table
        if _TABLE_ROW_RE.match(stripped):
            # Look ahead for separator row
            if (i + 1 < len(lines)
                    and _TABLE_ROW_RE.match(lines[i + 1].strip())
                    and _TABLE_SEP_RE.match(
                        lines[i + 1].strip().strip('|').replace(' ', ''))):
                flush_text()
                header_line = stripped[1:-1]
                headers = [h.strip() for h in header_line.split('|')]
                i += 2  # skip header + separator
                rows: list[list[str]] = []
                while i < len(lines) and _TABLE_ROW_RE.match(lines[i].strip()):
                    row_line = lines[i].strip()[1:-1]
                    vals = [v.strip() for v in row_line.split('|')]
                    rows.append(vals[:len(headers)])
                    i += 1
                sections.append(TableSection(columns=headers, rows=rows))
                continue

        current_text.append(line)
        i += 1

    flush_text()
    return sections
```

- [ ] **Step 4: Run tests to verify they pass**

```bash
pytest packages/ai-parrot/tests/unit/outputs/cards/test_markdown.py -v
```

Expected: All PASS.

- [ ] **Step 5: Commit**

```bash
git add packages/ai-parrot/src/parrot/outputs/cards/markdown.py \
       packages/ai-parrot/tests/unit/outputs/cards/test_markdown.py
git commit -m "feat(cards): markdown-to-sections parser — tables, code blocks, images"
```

---

### Task 7: Public API and Existing Test Verification

**Files:**
- Modify: `packages/ai-parrot/src/parrot/outputs/cards/__init__.py` (populate re-exports)
- Test: run full test suite to verify no regressions

**Interfaces:**
- Consumes: all modules from Tasks 1-6
- Produces: clean public API importable as `from parrot.outputs.cards import CardSpec, render, ...`

- [ ] **Step 1: Populate `__init__.py` with all public re-exports**

```python
# packages/ai-parrot/src/parrot/outputs/cards/__init__.py
"""Unified Adaptive Card 1.5 builder.

Usage:
    from parrot.outputs.cards import CardSpec, TableSection, render
    spec = CardSpec(title="Report", sections=[TableSection(...)])
    card_json = render(spec)
"""
from .actions import (
    ACAction,
    ActionOpenUrl,
    ActionShowCard,
    ActionSubmit,
    ActionToggleVisibility,
    TargetElement,
)
from .attachment import AC_CONTENT_TYPE, build_attachment, build_attachment_from_spec
from .elements import (
    ACElement,
    Column,
    ColumnSet,
    Container,
    Fact,
    FactSet,
    Image,
    Table,
    TableCell,
    TableColumnDefinition,
    TableRow,
    TextBlock,
)
from .inputs import (
    InputChoice,
    InputChoiceSet,
    InputDate,
    InputNumber,
    InputText,
    InputTime,
    InputToggle,
)
from .markdown import markdown_to_sections
from .renderer import CardRenderError, render, render_text
from .sections import (
    CardSection,
    CodeSection,
    DetailField,
    DetailSection,
    FormFieldSpec,
    FormSection,
    ImageEntry,
    ImageSection,
    MetricEntry,
    MetricsSection,
    RawElementsSection,
    StatusSection,
    TableSection,
    TextSection,
    ToggleSection,
)
from .spec import CardSpec
from .toggle import AutoCollapsePolicy, ToggleGroup
```

- [ ] **Step 2: Write an import smoke test**

```python
# Add to test_elements.py or a new test_init.py
class TestPublicAPI:
    def test_all_imports(self):
        from parrot.outputs.cards import (
            ACAction, ACElement, ActionOpenUrl, ActionShowCard,
            ActionSubmit, ActionToggleVisibility, AutoCollapsePolicy,
            CardRenderError, CardSpec, CodeSection, Container,
            DetailField, DetailSection, FactSet, FormFieldSpec,
            FormSection, Image, ImageEntry, ImageSection,
            InputChoiceSet, InputText, MetricEntry, MetricsSection,
            RawElementsSection, StatusSection, Table, TableSection,
            TextBlock, TextSection, ToggleGroup, ToggleSection,
            build_attachment, markdown_to_sections, render, render_text,
        )
        # All importable without error
        assert CardSpec is not None
```

- [ ] **Step 3: Run the full cards test suite**

```bash
pytest packages/ai-parrot/tests/unit/outputs/cards/ -v
```

Expected: All PASS.

- [ ] **Step 4: Run existing test suites to verify no regressions**

```bash
pytest packages/ai-parrot/tests/unit/forms/test_adaptive_card_renderer.py -v
pytest packages/ai-parrot-integrations/tests/unit/test_msagent_card_render.py -v
pytest packages/ai-parrot-visualizations/tests/outputs/a2ui_renderers/test_adaptive_cards.py -v
```

Expected: All existing tests still PASS (we haven't modified consumers yet).

- [ ] **Step 5: Commit**

```bash
git add packages/ai-parrot/src/parrot/outputs/cards/__init__.py \
       packages/ai-parrot/tests/unit/outputs/cards/
git commit -m "feat(cards): public API re-exports and import smoke test"
```

---

### Task 8: Migrate msagentsdk/cards.py

**Files:**
- Modify: `packages/ai-parrot-integrations/src/parrot/integrations/msagentsdk/cards.py`
- Modify: `packages/ai-parrot-integrations/tests/unit/test_msagent_card_render.py` (update assertions for AC 1.5 + Table)
- Test: existing tests at `test_msagent_card_render.py`, `test_msagent_card_e2e.py`

**Interfaces:**
- Consumes: `CardSpec`, `render`, `render_text`, `build_attachment`, section models from `parrot.outputs.cards`
- Produces: same public API — `render_card(SemanticUIResult) -> dict`, `render_text(SemanticUIResult) -> str`, `render_text_card(str) -> dict`, `render_data_card(...) -> dict`, `build_card_attachment(dict) -> dict`

- [ ] **Step 1: Refactor `render_card` to use CardSpec internally**

Replace the internal `_render_table`, `_render_metrics`, `_render_detail`, `_render_status` functions and `_RENDERERS` dispatch with a single `_semantic_to_card_spec()` that maps `SemanticUIResult` to `CardSpec`, then calls `parrot.outputs.cards.render()`. Keep the public `render_card()` signature identical.

- [ ] **Step 2: Refactor `render_text`, `render_text_card`, `render_data_card`**

- `render_text()` stays as-is (it's a total fallback that must never raise — keep the existing implementation or delegate to `parrot.outputs.cards.render_text()` via a CardSpec).
- `render_text_card()` → build `CardSpec(sections=[TextSection(text=text)])`, call `render()`.
- `render_data_card()` → build `CardSpec` with `TextSection` + `TableSection`, call `render()`.
- `build_card_attachment()` → delegate to `parrot.outputs.cards.build_attachment()`.

- [ ] **Step 3: Update test assertions**

In `test_msagent_card_render.py`:
- Change `assert card["version"] == "1.4"` → `assert card["version"] == "1.5"`.
- Update `ALLOWED_ELEMENTS` to include `"Table"` and remove the ColumnSet-based table assertions.
- Table tests should assert native Table element structure instead of ColumnSet.
- Action tests remain unchanged (Action.Submit, Action.OpenUrl still work).

- [ ] **Step 4: Run tests**

```bash
pytest packages/ai-parrot-integrations/tests/unit/test_msagent_card_render.py \
       packages/ai-parrot-integrations/tests/unit/test_msagent_card_e2e.py -v
```

Expected: All PASS with updated assertions.

- [ ] **Step 5: Commit**

```bash
git add packages/ai-parrot-integrations/src/parrot/integrations/msagentsdk/cards.py \
       packages/ai-parrot-integrations/tests/unit/test_msagent_card_render.py
git commit -m "refactor(msagentsdk): migrate cards.py to shared parrot.outputs.cards builder — AC 1.5 + native Table"
```

---

### Task 9: Migrate msteams/wrapper.py

**Files:**
- Modify: `packages/ai-parrot-integrations/src/parrot/integrations/msteams/wrapper.py`
- Test: run existing msteams tests

**Interfaces:**
- Consumes: `CardSpec`, `render`, `markdown_to_sections`, section models, `build_attachment` from `parrot.outputs.cards`
- Produces: same public behavior — `_build_adaptive_card(ParsedResponse) -> dict`, `_render_markdown_content()` removed (replaced by `markdown_to_sections`)

- [ ] **Step 1: Replace `_build_adaptive_card` internals**

Replace the ~250 lines of inline dict construction with:
1. Build a `_parsed_to_card_spec(parsed: ParsedResponse) -> CardSpec` method that maps parsed text → `markdown_to_sections()`, code → `CodeSection`, table_data → `TableSection`, charts → `ImageSection` (via `chart.to_data_uri()`), images → `ImageSection`.
2. `_build_adaptive_card()` calls `_parsed_to_card_spec()` then `render()`.
3. Enable `AutoCollapsePolicy()` by default.

- [ ] **Step 2: Remove `_render_markdown_content` and `_markdown_table_to_adaptive`**

These methods (~200 lines) are replaced by `markdown_to_sections()` from `parrot.outputs.cards.markdown`.

- [ ] **Step 3: Run existing tests**

```bash
pytest packages/ai-parrot-integrations/tests/ -k "msteams" -v --timeout=30
```

Expected: All PASS. If any tests assert specific ColumnSet-based table structure, update them to assert native Table structure.

- [ ] **Step 4: Commit**

```bash
git add packages/ai-parrot-integrations/src/parrot/integrations/msteams/wrapper.py
git commit -m "refactor(msteams): migrate wrapper.py to shared card builder — AC 1.5, native Table, auto-collapse"
```

---

### Task 10: Migrate A2UI, Forms, and HITL Card Renderers

**Files:**
- Modify: `packages/ai-parrot-visualizations/src/parrot/outputs/a2ui_renderers/adaptive_cards.py`
- Modify: `packages/ai-parrot/src/parrot/forms/renderers/adaptive_card.py`
- Modify: `packages/ai-parrot-integrations/src/parrot/integrations/msteams/hitl_cards.py`
- Test: existing tests for all three

**Interfaces:**
- Consumes: shared elements, sections, `CardSpec`, `render()` from `parrot.outputs.cards`
- Produces: same public APIs for all three renderers

- [ ] **Step 1: Migrate A2UI adaptive_cards.py**

Replace `_map_node()` → shared element instances (`TextBlock`, `Image`, `ColumnSet`, `Column`, `Container`). Build a `CardSpec(sections=[RawElementsSection(elements=...)])` and call `render()`. Deep links remain as TextBlock elements. Version assertion in tests changes from `_AC_VERSION` constant to `"1.5"` (already matched).

- [ ] **Step 2: Run A2UI tests**

```bash
pytest packages/ai-parrot-visualizations/tests/outputs/a2ui_renderers/test_adaptive_cards.py -v
```

Expected: All PASS.

- [ ] **Step 3: Migrate forms/renderers/adaptive_card.py**

Replace `_build_input_element()`, `_build_field()`, `_build_section_body()` with mapping to `FormSection(fields=[FormFieldSpec(...)])`. Replace `_build_form_actions()`, `_build_wizard_actions()` with `ActionSubmit` instances. Replace `_wrap_card()` with `CardSpec` + `render()`. The `render_summary()` method uses `DetailSection` + `FactSet` for the summary card.

- [ ] **Step 4: Run forms tests**

```bash
pytest packages/ai-parrot/tests/unit/forms/test_adaptive_card_renderer.py -v
```

Expected: All PASS.

- [ ] **Step 5: Migrate msteams/hitl_cards.py**

Replace inline dict construction in `TeamsCardRenderer.render()` with `CardSpec` building. HITL-specific interaction layouts use `RawElementsSection` + `FormSection` for input elements. `interaction_id` passes through `ActionSubmit.data`. The AC version stays `"1.5"` (already matched).

- [ ] **Step 6: Run HITL tests**

```bash
pytest packages/ai-parrot-integrations/tests/test_hitl_cards.py -v
```

Expected: All PASS.

- [ ] **Step 7: Run full test suite**

```bash
pytest packages/ai-parrot/tests/ packages/ai-parrot-integrations/tests/ \
       packages/ai-parrot-visualizations/tests/ --timeout=60 -x -q
```

Expected: All PASS. No regressions.

- [ ] **Step 8: Commit**

```bash
git add packages/ai-parrot-visualizations/src/parrot/outputs/a2ui_renderers/adaptive_cards.py \
       packages/ai-parrot/src/parrot/forms/renderers/adaptive_card.py \
       packages/ai-parrot-integrations/src/parrot/integrations/msteams/hitl_cards.py
git commit -m "refactor: migrate A2UI, forms, and HITL card renderers to shared parrot.outputs.cards builder"
```
