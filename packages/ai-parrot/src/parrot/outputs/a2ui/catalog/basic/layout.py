"""A2UI v1.0 Basic Catalog — layout primitives (TASK-2536).

``Row``, ``Column``, ``List``, ``Card``, ``Tabs``, ``Divider``, ``Modal``.
Every field, enum, and default is transcribed from the vendored
``catalog/basic/spec/catalog.json`` (pinned SHA
``90157ec10f36cf8e192daa71c95d2684af20c756``) — see
``test_basic_primitives.py`` for the anti-drift comparison.

One-way import rule (G8): this module MUST NEVER import from
``parrot.bots``, ``parrot.clients``, agents, or DatasetManager.
"""

from __future__ import annotations

from typing import ClassVar, Literal

from pydantic import BaseModel, ConfigDict, Field

from parrot.outputs.a2ui.models import ChildList, Component, DynamicString

__all__ = ["Card", "Column", "Divider", "List", "Modal", "Row", "TabItem", "Tabs"]


class Row(Component):
    """A layout component that arranges its children horizontally."""

    INSTRUCTIONS: ClassVar[str] = (
        "Row: a layout component that arranges its children horizontally. "
        "Requires `children` (a list of component ids, or a template). To "
        "create a grid, nest Columns within a Row."
    )

    component: Literal["Row"] = "Row"
    children: ChildList
    justify: Literal[
        "center", "end", "spaceAround", "spaceBetween", "spaceEvenly", "start", "stretch"
    ] = "start"
    align: Literal["start", "center", "end", "stretch"] = "stretch"


class Column(Component):
    """A layout component that arranges its children vertically."""

    INSTRUCTIONS: ClassVar[str] = (
        "Column: a layout component that arranges its children vertically. "
        "Requires `children` (a list of component ids, or a template). To "
        "create a grid, nest Rows within a Column."
    )

    component: Literal["Column"] = "Column"
    children: ChildList
    justify: Literal[
        "start", "center", "end", "spaceBetween", "spaceAround", "spaceEvenly", "stretch"
    ] = "start"
    align: Literal["center", "end", "start", "stretch"] = "stretch"


class List(Component):
    """A vertical or horizontal list of items."""

    INSTRUCTIONS: ClassVar[str] = (
        "List: lays out `children` (ids, or a template) vertically or "
        "horizontally via `direction`."
    )

    component: Literal["List"] = "List"
    children: ChildList
    direction: Literal["vertical", "horizontal"] = "vertical"
    align: Literal["start", "center", "end", "stretch"] = "stretch"


class Card(Component):
    """A single-child container with card-like presentation."""

    INSTRUCTIONS: ClassVar[str] = (
        "Card: a single-child container. Requires `child` (one component "
        "id). Wrap multiple elements in a Row/Column first."
    )

    component: Literal["Card"] = "Card"
    child: str = Field(
        description=(
            "The id of the single child component rendered inside the card. "
            "To display multiple elements, wrap them in a Row/Column and pass "
            "that container's id here — never multiple ids or a nonexistent one."
        )
    )


class TabItem(BaseModel):
    """A single tab: a title and its content component id."""

    model_config = ConfigDict(populate_by_name=True, extra="forbid")

    title: DynamicString
    child: str


class Tabs(Component):
    """A tabbed container, each tab pointing at a child component id."""

    INSTRUCTIONS: ClassVar[str] = (
        "Tabs: requires `tabs`, a non-empty array of {title, child} objects "
        "— `child` is the id of the tab's content component."
    )

    component: Literal["Tabs"] = "Tabs"
    tabs: list[TabItem] = Field(min_length=1)


class Modal(Component):
    """A dialog surfaced by a trigger component."""

    INSTRUCTIONS: ClassVar[str] = (
        "Modal: requires `trigger` (the id of the component that opens it, "
        "e.g. a Button) and `content` (the id of the component shown inside)."
    )

    component: Literal["Modal"] = "Modal"
    trigger: str = Field(
        description="The id of the component that opens the modal when interacted with."
    )
    content: str = Field(
        description="The id of the component to be displayed inside the modal."
    )


class Divider(Component):
    """A horizontal or vertical rule."""

    INSTRUCTIONS: ClassVar[str] = (
        "Divider: a horizontal or vertical rule (`axis`, default horizontal)."
    )

    component: Literal["Divider"] = "Divider"
    axis: Literal["horizontal", "vertical"] = "horizontal"
