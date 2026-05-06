"""Form presentation and layout style models.

This module defines the StyleSchema and related models that control
how a FormSchema is presented visually, independently of the form
data definition.
"""

from enum import Enum
from typing import Any

from pydantic import BaseModel

from .types import LocalizedString


class LayoutType(str, Enum):
    """Available layout modes for form rendering."""

    SINGLE_COLUMN = "single_column"
    TWO_COLUMN = "two_column"
    WIZARD = "wizard"
    ACCORDION = "accordion"
    TABS = "tabs"
    INLINE = "inline"


class FieldSizeHint(str, Enum):
    """Size hints for individual form fields."""

    SMALL = "small"
    MEDIUM = "medium"
    LARGE = "large"
    FULL = "full"


class FieldStyleHint(BaseModel):
    """Per-field style customization hints.

    Attributes:
        size: Size hint controlling how much horizontal space the field occupies.
        order: Override the field's display order within its section.
        css_class: Additional CSS class(es) for HTML5 rendering.
        variant: Renderer-specific variant identifier (e.g., "outlined", "filled").
    """

    size: FieldSizeHint | None = None
    order: int | None = None
    css_class: str | None = None
    variant: str | None = None


class StyleSchema(BaseModel):
    """Presentation style configuration for a form.

    StyleSchema is kept separate from FormSchema to allow the same
    form definition to be rendered differently in different contexts.

    Attributes:
        layout: The overall layout mode.
        field_styles: Per-field style overrides keyed by field_id.
        show_section_numbers: Whether to prefix section titles with numbers.
        submit_label: Label for the submit button.
        cancel_label: Label for the cancel button.
        theme: Renderer-specific theme identifier.
        meta: Arbitrary metadata for renderer-specific extensions.
    """

    layout: LayoutType = LayoutType.SINGLE_COLUMN
    field_styles: dict[str, FieldStyleHint] | None = None
    show_section_numbers: bool = False
    submit_label: LocalizedString = "Submit"
    cancel_label: LocalizedString = "Cancel"
    theme: str | None = None
    meta: dict[str, Any] | None = None


# Alias for backward compatibility
FormStyle = StyleSchema
