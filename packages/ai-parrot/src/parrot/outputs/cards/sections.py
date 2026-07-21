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
