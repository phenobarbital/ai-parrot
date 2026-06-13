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
    # New field types (FEAT-167)
    FieldType.SIGNATURE.value: {
        "field_id": "customer_signature",
        "field_type": "signature",
        "label": "Customer Signature",
        "required": True,
    },
    FieldType.DYNAMIC_SELECT.value: {
        "field_id": "country",
        "field_type": "dynamic_select",
        "label": "Country",
        "options_source": {
            "source_type": "endpoint",
            "source_ref": "https://api.example.com/countries",
            "value_field": "code",
            "label_field": "name",
        },
    },
    FieldType.TRANSFER_LIST.value: {
        "field_id": "selected_skills",
        "field_type": "transfer_list",
        "label": "Selected Skills",
        "options": [
            {"value": "python", "label": "Python"},
            {"value": "sql", "label": "SQL"},
            {"value": "ml", "label": "Machine Learning"},
        ],
    },
    FieldType.REMOTE_RESPONSE.value: {
        "field_id": "customer_data",
        "field_type": "remote_response",
        "label": "Customer Data",
        "read_only": True,
        "options_source": {
            "source_type": "endpoint",
            "source_ref": "https://api.example.com/customers/{{customer_id}}",
        },
    },
    FieldType.AVAILABILITY.value: {
        "field_id": "meeting_availability",
        "field_type": "availability",
        "label": "Meeting Availability",
    },
    FieldType.LOCATION.value: {
        "field_id": "country_code",
        "field_type": "location",
        "label": "Country",
        "required": True,
    },
    FieldType.TAGS.value: {
        "field_id": "interests",
        "field_type": "tags",
        "label": "Interests",
        "placeholder": "Add a tag...",
    },
    FieldType.NPS.value: {
        "field_id": "nps_score",
        "field_type": "nps",
        "label": "How likely are you to recommend us?",
        "required": True,
        "constraints": {"scale_min": 0, "scale_max": 10},
    },
    FieldType.LIKERT.value: {
        "field_id": "satisfaction",
        "field_type": "likert",
        "label": "Overall Satisfaction",
        "constraints": {
            "scale_min": 1,
            "scale_max": 5,
            "anchor_labels": {1: "Very Dissatisfied", 5: "Very Satisfied"},
        },
    },
    FieldType.RANKING.value: {
        "field_id": "priority_rank",
        "field_type": "ranking",
        "label": "Priority Rank",
        "constraints": {"scale_min": 1, "scale_max": 5},
    },
    # Phase 3 — FEAT-170
    FieldType.REST.value: {
        "field_id": "planogram_photo",
        "field_type": "rest",
        "label": "Subir foto para planogram compliance",
        "required": True,
        "constraints": {
            "allowed_mime_types": ["image/jpeg", "image/png"],
            "max_file_size_bytes": 10485760,  # 10 MiB
        },
        "meta": {
            "rest": {
                "mode": "callback",
                "callback_ref": "planogram_compliance",
                "response_path": "$.compliance_score",
                "display_template": "Compliance: {{ (answer * 100) | round }}/100",
                "persist_binary": True,
            }
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


def get_dependency_rule_snippets() -> dict[str, Any]:
    """Return skeleton dicts for building ``depends_on`` and ``post_depends`` rules.

    The returned skeletons are minimal but *valid* — each one can be passed
    directly to the corresponding Pydantic model constructor.  They are
    intended for use by LLMs and designer UIs that need a quick-start
    template when adding conditional logic to form fields.

    Returns:
        A dictionary with two top-level keys:

        - ``"depends_on"`` — a skeleton ``DependencyRule`` dict.
        - ``"post_depends"`` — a list containing one skeleton
          ``PostDependency`` dict for each common effect category.

    Example::

        snippets = get_dependency_rule_snippets()
        from parrot_formdesigner.core import DependencyRule
        rule = DependencyRule(**snippets["depends_on"])
    """

    return deepcopy(
        {
            "depends_on": {
                "conditions": [
                    {
                        "field_id": "<source_field_id>",
                        "operator": "eq",
                        "value": "<expected_value>",
                    }
                ],
                "logic": "and",
                "effect": "show",
            },
            "post_depends": [
                # Visibility effect — show/hide a target field
                {
                    "target": "<target_field_id>",
                    "effect": "show",
                    "conditions": [
                        {
                            "field_id": "<source_field_id>",
                            "operator": "eq",
                            "value": "<expected_value>",
                        }
                    ],
                    "logic": "and",
                },
                # Requirement effect — make a target field required
                {
                    "target": "<target_field_id>",
                    "effect": "require",
                    "conditions": [
                        {
                            "field_id": "<source_field_id>",
                            "operator": "neq",
                            "value": "<excluded_value>",
                        }
                    ],
                    "logic": "and",
                },
                # Calculation effect — write a computed value to a target field
                {
                    "target": "<target_field_id>",
                    "effect": "calc",
                    "operation": {
                        "op": "add",
                        "operands": ["<field_a>", "<field_b>"],
                        "target": "<target_field_id>",
                    },
                },
                # Cascade-clear — clear a downstream field when this one changes
                {
                    "target": "<downstream_field_id>",
                    "effect": "cascade_clear",
                },
            ],
        }
    )
