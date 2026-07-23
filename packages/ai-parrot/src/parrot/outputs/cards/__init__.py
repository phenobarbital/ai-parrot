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
from .spec import DEFAULT_ADAPTIVE_CARD_VERSION, CardSpec
from .toggle import AutoCollapsePolicy, ToggleGroup
