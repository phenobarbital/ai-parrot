"""JSON Schema renderer for FormSchema.

Renders FormSchema as a structural JSON Schema with custom x- extensions,
suitable for consumption by custom form-builder components (e.g., Svelte).

Output:
- content: structural JSON Schema dict (type=object, properties, required)
- style_output: StyleSchema.model_dump() dict
- content_type: "application/schema+json"
"""

from __future__ import annotations

import logging
from typing import Any

from ..constraints import DependencyRule
from ..options import FieldOption, OptionsSource
from ..schema import FormField, FormSchema, RenderedForm
from ..style import StyleSchema
from ..types import FieldType, LocalizedString
from .base import AbstractFormRenderer

logger = logging.getLogger(__name__)

# FieldType → JSON Schema type mapping
_TYPE_MAP: dict[FieldType, str] = {
    FieldType.TEXT: "string",
    FieldType.TEXT_AREA: "string",
    FieldType.EMAIL: "string",
    FieldType.URL: "string",
    FieldType.PHONE: "string",
    FieldType.PASSWORD: "string",
    FieldType.COLOR: "string",
    FieldType.HIDDEN: "string",
    FieldType.NUMBER: "number",
    FieldType.INTEGER: "integer",
    FieldType.BOOLEAN: "boolean",
    FieldType.DATE: "string",
    FieldType.DATETIME: "string",
    FieldType.TIME: "string",
    FieldType.SELECT: "string",
    FieldType.MULTI_SELECT: "array",
    FieldType.FILE: "string",
    FieldType.IMAGE: "string",
    FieldType.GROUP: "object",
    FieldType.ARRAY: "array",
}

# FieldType → JSON Schema "format" keyword (where applicable)
_FORMAT_MAP: dict[FieldType, str] = {
    FieldType.EMAIL: "email",
    FieldType.URL: "uri",
    FieldType.DATE: "date",
    FieldType.DATETIME: "date-time",
    FieldType.TIME: "time",
}


def _resolve(value: LocalizedString | None, locale: str = "en") -> str:
    """Resolve LocalizedString to plain string.

    Args:
        value: str or locale dict.
        locale: BCP 47 locale tag.

    Returns:
        Resolved string, empty string if None.
    """
    if value is None:
        return ""
    if isinstance(value, str):
        return value
    if locale in value:
        return value[locale]
    lang = locale.split("-")[0]
    if lang in value:
        return value[lang]
    if "en" in value:
        return value["en"]
    return next(iter(value.values()), "")


class JsonSchemaRenderer(AbstractFormRenderer):
    """Renders FormSchema as a structural JSON Schema with x- extensions.

    The output is designed for custom frontend components that need both
    the data schema and form metadata (sections, labels, dependencies).

    Output format:
    - content: JSON Schema dict (type=object, $schema, title, properties, required)
    - style_output: StyleSchema dict (layout, field styles, etc.)
    - content_type: "application/schema+json"

    Extensions used:
    - x-field-type: original FieldType value
    - x-section: section metadata (section_id, title, description)
    - x-depends-on: conditional visibility rule (serialized DependencyRule)
    - x-options-source: dynamic options source configuration
    - x-placeholder: placeholder text
    - x-read-only: read-only flag

    Example:
        renderer = JsonSchemaRenderer()
        result = await renderer.render(form_schema, style_schema)
        schema = result.content       # dict
        style = result.style_output   # dict
    """

    def __init__(self) -> None:
        """Initialize JsonSchemaRenderer."""
        self.logger = logging.getLogger(__name__)

    async def render(
        self,
        form: FormSchema,
        style: StyleSchema | None = None,
        *,
        locale: str = "en",
        prefilled: dict[str, Any] | None = None,
        errors: dict[str, str] | None = None,
    ) -> RenderedForm:
        """Render a FormSchema as a structural JSON Schema.

        Args:
            form: The form schema.
            style: Style configuration. Serialized to style_output.
            locale: Locale for i18n label resolution.
            prefilled: Pre-filled values (included as x-default in properties).
            errors: Field errors (ignored in schema output).

        Returns:
            RenderedForm with JSON Schema dict as content, style dict as
            style_output, and content_type="application/schema+json".
        """
        prefilled = prefilled or {}
        structural = self._build_structural_schema(form, locale, prefilled)
        style_output = style.model_dump() if style else None

        return RenderedForm(
            content=structural,
            content_type="application/schema+json",
            style_output=style_output,
            metadata={"locale": locale, "form_id": form.form_id},
        )

    def _build_structural_schema(
        self,
        form: FormSchema,
        locale: str,
        prefilled: dict[str, Any],
    ) -> dict[str, Any]:
        """Build the top-level JSON Schema object for the form.

        Args:
            form: The form schema.
            locale: Locale for i18n.
            prefilled: Pre-filled values.

        Returns:
            JSON Schema dict with type=object, properties, and required array.
        """
        properties: dict[str, Any] = {}
        required: list[str] = []

        for section in form.sections:
            section_meta = {
                "section_id": section.section_id,
                "title": _resolve(section.title, locale) if section.title else None,
                "description": _resolve(section.description, locale) if section.description else None,
            }

            for field in section.fields:
                prop = self._field_to_property(field, locale, prefilled)
                prop["x-section"] = section_meta

                if section.depends_on:
                    prop["x-section-depends-on"] = section.depends_on

                properties[field.field_id] = prop

                if field.required:
                    required.append(field.field_id)

        schema: dict[str, Any] = {
            "$schema": "http://json-schema.org/draft-07/schema#",
            "type": "object",
            "title": _resolve(form.title, locale) if form.title else form.form_id,
            "properties": properties,
        }
        if form.description:
            schema["description"] = _resolve(form.description, locale)
        if required:
            schema["required"] = required

        return schema

    def _field_to_property(
        self,
        field: FormField,
        locale: str,
        prefilled: dict[str, Any],
    ) -> dict[str, Any]:
        """Convert a FormField to a JSON Schema property dict.

        Args:
            field: FormField to convert.
            locale: Locale for i18n.
            prefilled: Pre-filled values.

        Returns:
            JSON Schema property dict with x- extensions.
        """
        ft = field.field_type
        json_type = _TYPE_MAP.get(ft, "string")

        prop: dict[str, Any] = {
            "type": json_type,
            "x-field-type": ft.value,
        }

        # Title (label)
        label = _resolve(field.label, locale)
        if label:
            prop["title"] = label

        # Description
        if field.description:
            prop["description"] = _resolve(field.description, locale)

        # Format keyword for string types with semantic meaning
        if ft in _FORMAT_MAP:
            prop["format"] = _FORMAT_MAP[ft]

        # Constraints
        if field.constraints:
            c = field.constraints
            if c.min_length is not None:
                prop["minLength"] = c.min_length
            if c.max_length is not None:
                prop["maxLength"] = c.max_length
            if c.min_value is not None:
                prop["minimum"] = c.min_value
            if c.max_value is not None:
                prop["maximum"] = c.max_value
            if c.step is not None:
                prop["multipleOf"] = c.step
            if c.pattern is not None:
                prop["pattern"] = c.pattern
            if c.min_items is not None:
                prop["minItems"] = c.min_items
            if c.max_items is not None:
                prop["maxItems"] = c.max_items

        # Options: enum for SELECT/MULTI_SELECT
        if ft == FieldType.SELECT and field.options:
            prop["enum"] = [opt.value for opt in field.options]
            prop["x-options"] = [
                {
                    "value": opt.value,
                    "label": _resolve(opt.label, locale) if opt.label else opt.value,
                    "disabled": opt.disabled,
                }
                for opt in field.options
            ]
        elif ft == FieldType.MULTI_SELECT and field.options:
            prop["items"] = {
                "type": "string",
                "enum": [opt.value for opt in field.options],
            }
            prop["x-options"] = [
                {
                    "value": opt.value,
                    "label": _resolve(opt.label, locale) if opt.label else opt.value,
                    "disabled": opt.disabled,
                }
                for opt in field.options
            ]

        # Dynamic options source
        if field.options_source:
            prop["x-options-source"] = field.options_source.model_dump()

        # GROUP: nested object with properties
        if ft == FieldType.GROUP and field.children:
            nested_props: dict[str, Any] = {}
            nested_required: list[str] = []
            for child in field.children:
                child_prop = self._field_to_property(child, locale, prefilled)
                nested_props[child.field_id] = child_prop
                if child.required:
                    nested_required.append(child.field_id)
            prop["properties"] = nested_props
            if nested_required:
                prop["required"] = nested_required

        # ARRAY: items from item_template
        if ft == FieldType.ARRAY and field.item_template:
            prop["items"] = self._field_to_property(field.item_template, locale, prefilled)

        # Dependency rule
        if field.depends_on:
            prop["x-depends-on"] = field.depends_on.model_dump()

        # Placeholder
        if field.placeholder:
            prop["x-placeholder"] = _resolve(field.placeholder, locale)

        # Read-only
        if field.read_only:
            prop["readOnly"] = True
            prop["x-read-only"] = True

        # Default / pre-filled value
        if field.field_id in prefilled:
            prop["default"] = prefilled[field.field_id]
        elif field.default is not None:
            prop["default"] = field.default

        return prop

    def _field_type_to_json_type(self, field_type: FieldType) -> str:
        """Map FieldType to JSON Schema type string.

        Args:
            field_type: FieldType enum value.

        Returns:
            JSON Schema type string.
        """
        return _TYPE_MAP.get(field_type, "string")
