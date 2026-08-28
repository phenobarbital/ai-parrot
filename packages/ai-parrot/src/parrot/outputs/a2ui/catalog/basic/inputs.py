"""A2UI v1.0 Basic Catalog — input/actionable primitives (TASK-2536).

``Button``, ``TextField``, ``CheckBox``, ``ChoicePicker``, ``Slider``,
``DateTimeInput`` — the six primitives the official schema composes with
``common_types.json#/$defs/Checkable``. Every field, enum, and default is
transcribed from the vendored ``catalog/basic/spec/catalog.json`` (pinned
SHA ``90157ec10f36cf8e192daa71c95d2684af20c756``) — see
``test_basic_primitives.py`` for the anti-drift comparison.

One-way import rule (G8): this module MUST NEVER import from
``parrot.bots``, ``parrot.clients``, agents, or DatasetManager.
"""

from __future__ import annotations

from typing import ClassVar, Literal

from pydantic import BaseModel, ConfigDict, Field

from parrot.outputs.a2ui.models import (
    Action,
    Component,
    DynamicBoolean,
    DynamicNumber,
    DynamicString,
    DynamicStringList,
)

__all__ = ["Button", "CheckBox", "Checkable", "ChoiceOption", "ChoicePicker", "DateTimeInput", "Slider", "TextField"]


class Checkable:
    """Marks a primitive as one the official schema composes with ``Checkable``.

    Purely a documentation/typing marker in this codebase: the wire
    :class:`~parrot.outputs.a2ui.models.Component` already declares
    ``checks: list[CheckRule] | None`` on EVERY component (spec §2 — the
    generic top-level-props envelope). The official schema only actually
    composes ``common_types.json#/$defs/Checkable`` into these six
    primitives; mixing this in documents that fact and mirrors the schema's
    own ``allOf`` composition, without re-declaring the (already-inherited)
    ``checks`` field.
    """


class Button(Checkable, Component):
    """A clickable button dispatching an :class:`Action`."""

    INSTRUCTIONS: ClassVar[str] = (
        "Button: requires `child` (usually a Text id; use an Icon id only if "
        "explicitly icon-only) and `action`. `variant` hints style "
        "(default|primary|borderless, default default)."
    )

    component: Literal["Button"] = "Button"
    child: str = Field(
        description=(
            "The id of the child component. Use a Text component for a "
            "labeled button; only use an Icon for an icon-only button."
        )
    )
    variant: Literal["default", "primary", "borderless"] = "default"
    action: Action


class TextField(Checkable, Component):
    """A single-line or multi-line text input."""

    INSTRUCTIONS: ClassVar[str] = (
        "TextField: requires `label`. `variant` selects the input kind "
        "(longText|number|shortText|obscured, default shortText)."
    )

    component: Literal["TextField"] = "TextField"
    label: DynamicString
    value: DynamicString | None = None
    placeholder: DynamicString | None = None
    variant: Literal["longText", "number", "shortText", "obscured"] = "shortText"


class CheckBox(Checkable, Component):
    """A boolean toggle with a label."""

    INSTRUCTIONS: ClassVar[str] = "CheckBox: requires `label` and `value` (boolean)."

    component: Literal["CheckBox"] = "CheckBox"
    label: DynamicString
    value: DynamicBoolean


class ChoiceOption(BaseModel):
    """A single selectable option for :class:`ChoicePicker`."""

    model_config = ConfigDict(populate_by_name=True, extra="forbid")

    label: DynamicString
    value: str


class ChoicePicker(Checkable, Component):
    """Selects one or more options from a list."""

    INSTRUCTIONS: ClassVar[str] = (
        "ChoicePicker: requires `options` (list of {label, value}) and "
        "`value` (the currently selected value(s), bound to a string array). "
        "`variant` controls single/multi selection (multipleSelection|"
        "mutuallyExclusive, default mutuallyExclusive); `displayStyle` "
        "controls presentation (checkbox|chips, default checkbox)."
    )

    component: Literal["ChoicePicker"] = "ChoicePicker"
    label: DynamicString | None = None
    variant: Literal["multipleSelection", "mutuallyExclusive"] = "mutuallyExclusive"
    options: list[ChoiceOption]
    value: DynamicStringList
    display_style: Literal["checkbox", "chips"] = Field(
        default="checkbox", alias="displayStyle"
    )
    filterable: bool = False


class Slider(Checkable, Component):
    """A numeric range input."""

    INSTRUCTIONS: ClassVar[str] = (
        "Slider: requires `value` and `max`. `min` defaults to 0; `steps` "
        "(if set) snaps to that many discrete divisions."
    )

    component: Literal["Slider"] = "Slider"
    label: DynamicString | None = None
    min: float = 0
    max: float
    value: DynamicNumber
    steps: int | None = Field(default=None, ge=1)


class DateTimeInput(Checkable, Component):
    """A date/time picker."""

    INSTRUCTIONS: ClassVar[str] = (
        "DateTimeInput: requires `value` (ISO 8601 string; empty string if "
        "unset). `enableDate`/`enableTime` control which pickers are shown."
    )

    component: Literal["DateTimeInput"] = "DateTimeInput"
    value: DynamicString
    enable_date: bool = Field(default=False, alias="enableDate")
    enable_time: bool = Field(default=False, alias="enableTime")
    min: DynamicString | None = None
    max: DynamicString | None = None
    label: DynamicString | None = None
