"""Helper utilities for supported form field definitions.

This module centralizes the accepted ``FieldType`` values and provides
minimal JSON snippets for each field type. These snippets are intended for
form creation/editing flows where agents or UIs need quick reference payloads.
"""

from __future__ import annotations

from copy import deepcopy
from typing import Any

from ..core.types import FieldType


_FIELD_SCHEMA_SNIPPETS: dict[str, dict[str, Any]] = {
    FieldType.TEXT.value: {
        "field_id": "full_name",
        "field_type": "text",
        "label": "Full name",
        "required": True,
    },
    FieldType.TEXT_AREA.value: {
        "field_id": "comments",
        "field_type": "text_area",
        "label": "Comments",
    },
    FieldType.NUMBER.value: {
        "field_id": "amount",
        "field_type": "number",
        "label": "Amount",
        "constraints": {"min_value": 0},
    },
    FieldType.INTEGER.value: {
        "field_id": "quantity",
        "field_type": "integer",
        "label": "Quantity",
        "constraints": {"min_value": 1},
    },
    FieldType.BOOLEAN.value: {
        "field_id": "accepted_terms",
        "field_type": "boolean",
        "label": "I accept terms",
    },
    FieldType.DATE.value: {
        "field_id": "start_date",
        "field_type": "date",
        "label": "Start date",
    },
    FieldType.DATETIME.value: {
        "field_id": "appointment_at",
        "field_type": "datetime",
        "label": "Appointment time",
    },
    FieldType.TIME.value: {
        "field_id": "preferred_time",
        "field_type": "time",
        "label": "Preferred time",
    },
    FieldType.SELECT.value: {
        "field_id": "department",
        "field_type": "select",
        "label": "Department",
        "options": [
            {"value": "sales", "label": "Sales"},
            {"value": "support", "label": "Support"},
        ],
    },
    FieldType.MULTI_SELECT.value: {
        "field_id": "skills",
        "field_type": "multi_select",
        "label": "Skills",
        "options": [
            {"value": "python", "label": "Python"},
            {"value": "sql", "label": "SQL"},
        ],
    },
    FieldType.FILE.value: {
        "field_id": "resume",
        "field_type": "file",
        "label": "Resume",
    },
    FieldType.IMAGE.value: {
        "field_id": "profile_image",
        "field_type": "image",
        "label": "Profile image",
    },
    FieldType.COLOR.value: {
        "field_id": "theme_color",
        "field_type": "color",
        "label": "Theme color",
        "default": "#0ea5e9",
    },
    FieldType.URL.value: {
        "field_id": "portfolio_url",
        "field_type": "url",
        "label": "Portfolio URL",
    },
    FieldType.EMAIL.value: {
        "field_id": "email",
        "field_type": "email",
        "label": "Email",
        "required": True,
    },
    FieldType.PHONE.value: {
        "field_id": "phone_number",
        "field_type": "phone",
        "label": "Phone number",
    },
    FieldType.PASSWORD.value: {
        "field_id": "password",
        "field_type": "password",
        "label": "Password",
        "required": True,
    },
    FieldType.HIDDEN.value: {
        "field_id": "record_id",
        "field_type": "hidden",
        "label": "Record ID",
        "default": "{{record_id}}",
    },
    FieldType.GROUP.value: {
        "field_id": "address",
        "field_type": "group",
        "label": "Address",
        "children": [
            {
                "field_id": "street",
                "field_type": "text",
                "label": "Street",
            },
            {
                "field_id": "city",
                "field_type": "text",
                "label": "City",
            },
        ],
    },
    FieldType.ARRAY.value: {
        "field_id": "items",
        "field_type": "array",
        "label": "Items",
        "item_template": {
            "field_id": "item",
            "field_type": "text",
            "label": "Item",
        },
    },
}


def list_supported_form_field_types() -> list[str]:
    """Return supported field type values for FormField.field_type."""

    return [field_type.value for field_type in FieldType]


def get_form_field_schema_snippets() -> dict[str, dict[str, Any]]:
    """Return example JSON snippets for each supported field type.

    Returns a copy to avoid accidental mutation by callers.
    """

    return deepcopy(_FIELD_SCHEMA_SNIPPETS)
