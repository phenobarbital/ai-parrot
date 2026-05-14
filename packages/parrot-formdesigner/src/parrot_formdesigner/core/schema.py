"""Core form schema data models.

This module defines the canonical Pydantic models for form structure:
FormField, FormSubsection, FormSection, SubmitAction, FormSchema, and
RenderedForm.  These models are the foundation of the entire forms
abstraction layer.
"""

from __future__ import annotations

from collections.abc import Iterator
from datetime import datetime
from typing import Any, Literal, Union

from pydantic import BaseModel, ConfigDict

from .auth import AuthConfig
from .constraints import DependencyRule, FieldConstraints
from .options import FieldOption, OptionsSource
from .types import FieldType, LocalizedString


class FormField(BaseModel):
    """A single field within a form section.

    FormField is self-referential: GROUP fields can have children,
    and ARRAY fields can have an item_template defining the repeated element.

    Attributes:
        field_id: Unique identifier for this field within the form.
        field_type: The type of input control to render.
        label: Human-readable label shown to the user.
        description: Optional extended description or help text.
        placeholder: Optional placeholder text shown when the field is empty.
        required: Whether this field must be filled before submission.
        default: Default value for the field.
        read_only: Whether the field is displayed but cannot be edited.
        constraints: Validation constraints applied to this field.
        options: Static list of options for select/multi-select fields.
        options_source: Dynamic options source configuration.
        depends_on: Dependency rule controlling conditional visibility.
        children: Child fields for GROUP type fields.
        item_template: Template for items in ARRAY type fields.
        meta: Arbitrary metadata for renderer-specific extensions.
    """

    model_config = ConfigDict(extra="forbid")

    field_id: str
    field_type: FieldType
    label: LocalizedString
    description: LocalizedString | None = None
    placeholder: LocalizedString | None = None
    required: bool = False
    default: Any = None
    read_only: bool = False
    constraints: FieldConstraints | None = None
    options: list[FieldOption] | None = None
    options_source: OptionsSource | None = None
    depends_on: DependencyRule | None = None
    children: list[FormField] | None = None
    item_template: FormField | None = None
    meta: dict[str, Any] | None = None


# Required for self-referential model resolution
FormField.model_rebuild()


class FormSubsection(BaseModel):
    """A visual sub-grouping of fields within a section.

    Subsections provide an additional level of organization below sections.
    They co-exist alongside ``FormField`` items in ``FormSection.fields``,
    giving renderers a grouping boundary (header, divider, container) without
    creating a full section (which would affect wizard steps, accordion
    panels, etc.).

    Attributes:
        subsection_id: Unique identifier for this subsection within the form.
        title: Optional title displayed as a subsection header.
        description: Optional description shown under the subsection title.
        fields: List of fields in this subsection.
        depends_on: Dependency rule controlling conditional visibility.
        meta: Arbitrary metadata for renderer-specific extensions.
    """

    model_config = ConfigDict(extra="forbid")

    subsection_id: str
    title: LocalizedString | None = None
    description: LocalizedString | None = None
    fields: list[FormField]
    depends_on: DependencyRule | None = None
    meta: dict[str, Any] | None = None


SectionItem = Union[FormField, FormSubsection]


class FormSection(BaseModel):
    """A logical grouping of fields within a form.

    Sections can be used to organize fields visually and in wizard-style forms
    each section becomes a separate step.

    The ``fields`` list may contain both ``FormField`` and ``FormSubsection``
    items in any order.  Use :meth:`iter_fields` to iterate over all
    ``FormField`` instances (flattening through subsections).

    Attributes:
        section_id: Unique identifier for this section.
        title: Optional title displayed as a section header.
        description: Optional description shown under the section title.
        fields: Ordered list of fields and subsections in this section.
        depends_on: Dependency rule controlling conditional section visibility.
        meta: Arbitrary metadata for renderer-specific extensions.
    """

    section_id: str
    title: LocalizedString | None = None
    description: LocalizedString | None = None
    fields: list[SectionItem]
    depends_on: DependencyRule | None = None
    meta: dict[str, Any] | None = None

    def iter_fields(self) -> Iterator[FormField]:
        """Yield every ``FormField``, flattening through subsections."""
        for item in self.fields:
            if isinstance(item, FormSubsection):
                yield from item.fields
            else:
                yield item


class SubmitAction(BaseModel):
    """Defines what happens when a form is submitted.

    Attributes:
        action_type: How the submission is handled.
        action_ref: Reference to the handler (tool name, URL, event name, callback ID).
        method: HTTP method for endpoint submissions.
        confirm_message: Optional confirmation message shown before submission.
    """

    action_type: Literal["tool_call", "endpoint", "event", "callback"]
    action_ref: str
    method: str = "POST"
    confirm_message: LocalizedString | None = None
    auth: AuthConfig | None = None


class FormSchema(BaseModel):
    """The canonical representation of a complete form.

    FormSchema is the central data model of the forms abstraction layer.
    It is platform-agnostic and can be rendered to Adaptive Cards, HTML5,
    JSON Schema, or any other format via the renderer system.

    Attributes:
        form_id: Unique identifier for this form.
        version: Schema version string.
        title: Human-readable form title.
        description: Optional description of the form's purpose.
        sections: Ordered list of form sections.
        submit: Optional submission action configuration.
        cancel_allowed: Whether the user can cancel/dismiss the form.
        meta: Arbitrary metadata for renderer-specific extensions.
        created_at: Optional creation timestamp (UTC). Populated by storage
            backends when forms are loaded from persistence; ``None`` for
            ad-hoc forms registered in memory.
        tenant: Optional tenant slug. When set, persistence backends use it
            to resolve the Postgres schema where the form is stored
            (e.g. ``"epson"`` → ``epson.form_schemas``). ``None`` falls
            back to the storage's default schema.
    """

    form_id: str
    version: str = "1.0"
    title: LocalizedString
    description: LocalizedString | None = None
    sections: list[FormSection]
    submit: SubmitAction | None = None
    cancel_allowed: bool = True
    meta: dict[str, Any] | None = None
    created_at: datetime | None = None
    tenant: str | None = None


class RenderWarning(BaseModel):
    """Warning emitted when a renderer uses degraded fallback for a field type.

    Attributes:
        field_id: The ID of the field that triggered the fallback.
        field_type: The FieldType.value string (e.g. "signature").
        renderer: The renderer name ("html5" | "adaptive_card" | "pdf" |
                  "xforms" | "jsonschema" | "telegram").
        reason: Human-readable explanation (e.g. "unsupported in PDF — rendered as placeholder").
    """

    field_id: str
    field_type: str
    renderer: str
    reason: str


class RenderedForm(BaseModel):
    """Output of a form renderer.

    Attributes:
        content: The rendered form content (varies by renderer).
        content_type: MIME type or format identifier for the content.
        style_output: Optional style-related output from the renderer.
        metadata: Renderer-specific metadata about the rendering process.
        warnings: Degraded-rendering warnings. Empty list when all fields
            rendered natively. One entry per (field_id, renderer) pair that
            used FallbackRenderer.
    """

    content: Any
    content_type: str
    style_output: Any | None = None
    metadata: dict[str, Any] | None = None
    warnings: list[RenderWarning] = []
