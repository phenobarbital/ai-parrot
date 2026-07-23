"""Pydantic models for AC 1.5 display elements."""
from __future__ import annotations

from typing import Literal

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
    type: Literal["TableCell"] = "TableCell"
    items: list[ACElement] = []


class TableRow(BaseModel):
    type: Literal["TableRow"] = "TableRow"
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


class Column(ACElement):
    element_type: Literal["Column"] = "Column"
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
