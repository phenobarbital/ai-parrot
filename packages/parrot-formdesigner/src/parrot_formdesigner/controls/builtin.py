"""Built-in form-control seed.

Importing this module registers one ``FieldControlMetadata`` entry per
``FieldType`` enum value with the form-control registry. Snippet seeds are
sourced from ``tools.field_helpers.get_form_field_schema_snippets()``;
per-type categorization (``category``, ``icon``, ``render_hint``,
``is_container``, ``supports_constraints``) is encoded as a constant in
this module.

This module is meant to be imported once for its side effect — typically by
``parrot_formdesigner.api.__init__`` so the registry is seeded before any
request hits ``GET /api/v1/form-controls``.
"""

from __future__ import annotations

from typing import Any

from ..core.types import FieldType
from ..tools.field_helpers import get_form_field_schema_snippets
from .registry import register_field_control


# ---------------------------------------------------------------------------
# Rule capability buckets (FEAT-234)
# Each constant is a list of string values from the respective enums.
# They are intentionally kept as plain lists (not enum references) so they
# serialise cleanly via FieldControlMetadata.model_dump().
# ---------------------------------------------------------------------------

# Operators applicable to any text-like field
_TEXT_OPERATORS: list[str] = ["eq", "neq", "in", "not_in", "is_empty", "is_not_empty"]
# Operators applicable to numeric fields (superset of text)
_NUMERIC_OPERATORS: list[str] = [
    "eq", "neq", "gt", "lt", "gte", "lte", "in", "not_in", "is_empty", "is_not_empty"
]
# Operators for boolean fields
_BOOLEAN_OPERATORS: list[str] = ["eq", "neq", "is_empty", "is_not_empty"]
# Operators for date/time fields (same as numeric for ordering)
_DATE_OPERATORS: list[str] = ["eq", "neq", "gt", "lt", "gte", "lte", "is_empty", "is_not_empty"]
# Operators for selection fields
_SELECT_OPERATORS: list[str] = ["eq", "neq", "in", "not_in", "is_empty", "is_not_empty"]

# Standard visibility/requirement effects applicable to all non-container fields
_STANDARD_EFFECTS: list[str] = ["show", "hide", "require", "disable"]
# Extended effects that include set/calc/cascade (applicable to simple value fields)
_EXTENDED_EFFECTS: list[str] = [
    "show", "hide", "require", "disable", "set", "calc", "reload_options", "cascade_clear"
]

# Operations for numeric types (arithmetic + comparison helpers)
_NUMERIC_OPERATIONS: list[str] = [
    "add", "subtract", "multiply", "divide", "percent", "copy", "format"
]
# Operations for text types (string manipulation)
_TEXT_OPERATIONS: list[str] = ["copy", "concat", "format"]
# Operations for date types
_DATE_OPERATIONS: list[str] = ["copy", "date_diff", "format"]


# Per-type metadata that is NOT part of `_FIELD_SCHEMA_SNIPPETS` and must be
# encoded here. See spec §3 Module 4 for the categorization rationale.
# Keys `supported_operators`, `supported_effects`, `supported_operations` are
# added for FEAT-234 capability advertising.
_BUILTIN_METADATA: dict[FieldType, dict[str, Any]] = {
    FieldType.TEXT: {
        "label": "Text",
        "description": "Single-line text input.",
        "category": "basic",
        "icon": "text",
        "render_hint": "input",
        "supports_constraints": True,
        "is_container": False,
        "supported_operators": _TEXT_OPERATORS,
        "supported_effects": _EXTENDED_EFFECTS,
        "supported_operations": _TEXT_OPERATIONS,
    },
    FieldType.TEXT_AREA: {
        "label": "Text Area",
        "description": "Multi-line text input.",
        "category": "basic",
        "icon": "text-area",
        "render_hint": "input",
        "supports_constraints": True,
        "is_container": False,
        "supported_operators": _TEXT_OPERATORS,
        "supported_effects": _EXTENDED_EFFECTS,
        "supported_operations": _TEXT_OPERATIONS,
    },
    FieldType.NUMBER: {
        "label": "Number",
        "description": "Decimal number input.",
        "category": "basic",
        "icon": "number",
        "render_hint": "input",
        "supports_constraints": True,
        "is_container": False,
        "supported_operators": _NUMERIC_OPERATORS,
        "supported_effects": _EXTENDED_EFFECTS,
        "supported_operations": _NUMERIC_OPERATIONS,
    },
    FieldType.INTEGER: {
        "label": "Integer",
        "description": "Whole number input.",
        "category": "basic",
        "icon": "integer",
        "render_hint": "input",
        "supports_constraints": True,
        "is_container": False,
        "supported_operators": _NUMERIC_OPERATORS,
        "supported_effects": _EXTENDED_EFFECTS,
        "supported_operations": _NUMERIC_OPERATIONS,
    },
    FieldType.BOOLEAN: {
        "label": "Boolean",
        "description": "Yes/No toggle.",
        "category": "basic",
        "icon": "toggle",
        "render_hint": "toggle",
        "supports_constraints": False,
        "is_container": False,
        "supported_operators": _BOOLEAN_OPERATORS,
        "supported_effects": _STANDARD_EFFECTS,
        "supported_operations": ["copy", "set"],
    },
    FieldType.DATE: {
        "label": "Date",
        "description": "Date picker.",
        "category": "basic",
        "icon": "calendar",
        "render_hint": "datetime",
        "supports_constraints": True,
        "is_container": False,
        "supported_operators": _DATE_OPERATORS,
        "supported_effects": _EXTENDED_EFFECTS,
        "supported_operations": _DATE_OPERATIONS,
    },
    FieldType.DATETIME: {
        "label": "Date & Time",
        "description": "Date and time picker.",
        "category": "basic",
        "icon": "calendar-clock",
        "render_hint": "datetime",
        "supports_constraints": True,
        "is_container": False,
        "supported_operators": _DATE_OPERATORS,
        "supported_effects": _EXTENDED_EFFECTS,
        "supported_operations": _DATE_OPERATIONS,
    },
    FieldType.TIME: {
        "label": "Time",
        "description": "Time picker.",
        "category": "basic",
        "icon": "clock",
        "render_hint": "datetime",
        "supports_constraints": True,
        "is_container": False,
        "supported_operators": _DATE_OPERATORS,
        "supported_effects": _EXTENDED_EFFECTS,
        "supported_operations": _DATE_OPERATIONS,
    },
    FieldType.SELECT: {
        "label": "Select",
        "description": "Single-choice dropdown.",
        "category": "selection",
        "icon": "select",
        "render_hint": "select",
        "supports_constraints": True,
        "is_container": False,
        "supported_operators": _SELECT_OPERATORS,
        "supported_effects": _EXTENDED_EFFECTS,
        "supported_operations": ["copy", "lookup", "reload_options"],
    },
    FieldType.MULTI_SELECT: {
        "label": "Multi Select",
        "description": "Multiple-choice picker.",
        "category": "selection",
        "icon": "multiselect",
        "render_hint": "multiselect",
        "supports_constraints": True,
        "is_container": False,
        "supported_operators": _SELECT_OPERATORS,
        "supported_effects": _EXTENDED_EFFECTS,
        "supported_operations": ["copy", "lookup", "aggregate"],
    },
    FieldType.FILE: {
        "label": "File",
        "description": "File upload.",
        "category": "media",
        "icon": "file",
        "render_hint": "upload",
        "supports_constraints": True,
        "is_container": False,
        "supported_operators": ["is_empty", "is_not_empty"],
        "supported_effects": _STANDARD_EFFECTS,
        "supported_operations": [],
    },
    FieldType.IMAGE: {
        "label": "Image",
        "description": "Image upload.",
        "category": "media",
        "icon": "image",
        "render_hint": "upload",
        "supports_constraints": True,
        "is_container": False,
        "supported_operators": ["is_empty", "is_not_empty"],
        "supported_effects": _STANDARD_EFFECTS,
        "supported_operations": [],
    },
    FieldType.COLOR: {
        "label": "Color",
        "description": "Color picker.",
        "category": "advanced",
        "icon": "color",
        "render_hint": "color",
        "supports_constraints": False,
        "is_container": False,
        "supported_operators": ["eq", "neq", "is_empty", "is_not_empty"],
        "supported_effects": _STANDARD_EFFECTS,
        "supported_operations": ["copy"],
    },
    FieldType.URL: {
        "label": "URL",
        "description": "URL input.",
        "category": "basic",
        "icon": "link",
        "render_hint": "input",
        "supports_constraints": True,
        "is_container": False,
        "supported_operators": _TEXT_OPERATORS,
        "supported_effects": _EXTENDED_EFFECTS,
        "supported_operations": _TEXT_OPERATIONS,
    },
    FieldType.EMAIL: {
        "label": "Email",
        "description": "Email-address input.",
        "category": "basic",
        "icon": "mail",
        "render_hint": "input",
        "supports_constraints": True,
        "is_container": False,
        "supported_operators": _TEXT_OPERATORS,
        "supported_effects": _EXTENDED_EFFECTS,
        "supported_operations": _TEXT_OPERATIONS,
    },
    FieldType.PHONE: {
        "label": "Phone",
        "description": "Phone-number input.",
        "category": "basic",
        "icon": "phone",
        "render_hint": "input",
        "supports_constraints": True,
        "is_container": False,
        "supported_operators": _TEXT_OPERATORS,
        "supported_effects": _EXTENDED_EFFECTS,
        "supported_operations": _TEXT_OPERATIONS,
    },
    FieldType.PASSWORD: {
        "label": "Password",
        "description": "Masked password input.",
        "category": "basic",
        "icon": "lock",
        "render_hint": "input",
        "supports_constraints": True,
        "is_container": False,
        "supported_operators": ["is_empty", "is_not_empty"],
        "supported_effects": _STANDARD_EFFECTS,
        "supported_operations": [],
    },
    FieldType.HIDDEN: {
        "label": "Hidden",
        "description": "Hidden field (not visible to the user).",
        "category": "advanced",
        "icon": "hidden",
        "render_hint": "hidden",
        "supports_constraints": False,
        "is_container": False,
        "supported_operators": _TEXT_OPERATORS,
        "supported_effects": _EXTENDED_EFFECTS,
        "supported_operations": ["copy", "set"],
    },
    FieldType.GROUP: {
        "label": "Group",
        "description": "Logical group of fields.",
        "category": "layout",
        "icon": "group",
        "render_hint": "container",
        "supports_constraints": False,
        "is_container": True,
        "supported_operators": [],
        "supported_effects": ["show", "hide"],
        "supported_operations": [],
    },
    FieldType.ARRAY: {
        "label": "Array",
        "description": "Repeating list of fields.",
        "category": "layout",
        "icon": "repeat",
        "render_hint": "repeater",
        "supports_constraints": False,
        "is_container": True,
        "supported_operators": [],
        "supported_effects": ["show", "hide"],
        "supported_operations": [],
    },
    # New field types (FEAT-167)
    FieldType.SIGNATURE: {
        "label": "Signature",
        "description": "Handwritten signature capture.",
        "category": "media",
        "icon": "signature",
        "render_hint": "signature",
        "supports_constraints": False,
        "is_container": False,
        "supported_operators": ["is_empty", "is_not_empty"],
        "supported_effects": _STANDARD_EFFECTS,
        "supported_operations": [],
    },
    FieldType.DYNAMIC_SELECT: {
        "label": "Dynamic Select",
        "description": "Dropdown populated from a remote data source.",
        "category": "selection",
        "icon": "dynamic-select",
        "render_hint": "select",
        "supports_constraints": True,
        "is_container": False,
        "supported_operators": _SELECT_OPERATORS,
        "supported_effects": _EXTENDED_EFFECTS,
        "supported_operations": ["copy", "lookup", "reload_options"],
    },
    FieldType.TRANSFER_LIST: {
        "label": "Transfer List",
        "description": "Dual-list widget to move items between available and selected.",
        "category": "selection",
        "icon": "transfer",
        "render_hint": "transfer-list",
        "supports_constraints": True,
        "is_container": False,
        "supported_operators": _SELECT_OPERATORS,
        "supported_effects": _EXTENDED_EFFECTS,
        "supported_operations": ["copy", "aggregate"],
    },
    FieldType.REMOTE_RESPONSE: {
        "label": "Remote Response",
        "description": "Read-only field showing data fetched from a remote endpoint.",
        "category": "advanced",
        "icon": "remote",
        "render_hint": "display",
        "supports_constraints": False,
        "is_container": False,
        "supported_operators": _TEXT_OPERATORS,
        "supported_effects": _STANDARD_EFFECTS,
        "supported_operations": ["copy"],
    },
    FieldType.AVAILABILITY: {
        "label": "Availability",
        "description": "Date/time range picker for scheduling availability.",
        "category": "advanced",
        "icon": "availability",
        "render_hint": "availability",
        "supports_constraints": False,
        "is_container": False,
        "supported_operators": _DATE_OPERATORS,
        "supported_effects": _STANDARD_EFFECTS,
        "supported_operations": _DATE_OPERATIONS,
    },
    FieldType.LOCATION: {
        "label": "Location",
        "description": "Country or location selector using ISO codes.",
        "category": "selection",
        "icon": "location",
        "render_hint": "select",
        "supports_constraints": False,
        "is_container": False,
        "supported_operators": _SELECT_OPERATORS,
        "supported_effects": _STANDARD_EFFECTS,
        "supported_operations": ["copy"],
    },
    FieldType.TAGS: {
        "label": "Tags",
        "description": "Free-form tag input (comma-separated values).",
        "category": "selection",
        "icon": "tag",
        "render_hint": "tags",
        "supports_constraints": True,
        "is_container": False,
        "supported_operators": _SELECT_OPERATORS,
        "supported_effects": _EXTENDED_EFFECTS,
        "supported_operations": ["copy", "concat"],
    },
    FieldType.NPS: {
        "label": "NPS",
        "description": "Net Promoter Score (0–10 rating scale).",
        "category": "advanced",
        "icon": "nps",
        "render_hint": "rating",
        "supports_constraints": True,
        "is_container": False,
        "supported_operators": _NUMERIC_OPERATORS,
        "supported_effects": _EXTENDED_EFFECTS,
        "supported_operations": _NUMERIC_OPERATIONS,
    },
    FieldType.LIKERT: {
        "label": "Likert Scale",
        "description": "Likert-scale rating field with configurable range.",
        "category": "advanced",
        "icon": "likert",
        "render_hint": "rating",
        "supports_constraints": True,
        "is_container": False,
        "supported_operators": _NUMERIC_OPERATORS,
        "supported_effects": _EXTENDED_EFFECTS,
        "supported_operations": _NUMERIC_OPERATIONS,
    },
    FieldType.RANKING: {
        "label": "Ranking",
        "description": "Numeric ranking field with configurable range.",
        "category": "advanced",
        "icon": "ranking",
        "render_hint": "rating",
        "supports_constraints": True,
        "is_container": False,
        "supported_operators": _NUMERIC_OPERATORS,
        "supported_effects": _EXTENDED_EFFECTS,
        "supported_operations": _NUMERIC_OPERATIONS,
    },
    # Phase 3 — FEAT-170
    FieldType.REST: {
        "label": "REST",
        "description": (
            "Upload content to a REST endpoint or callback; "
            "the API response becomes the field answer."
        ),
        "category": "advanced",
        "icon": "rest",
        "render_hint": "upload",
        "supports_constraints": True,
        "is_container": False,
        "supported_operators": ["is_empty", "is_not_empty"],
        "supported_effects": _STANDARD_EFFECTS,
        "supported_operations": [],
    },
    # Phase 4 — FEAT-224
    FieldType.AUDIO: {
        "label": "Audio",
        "description": "Audio recording input with speech-to-text transcription.",
        "category": "advanced",
        "icon": "microphone",
        "render_hint": "audio-recorder",
        "supports_constraints": False,
        "is_container": False,
        "supported_operators": ["is_empty", "is_not_empty"],
        "supported_effects": _STANDARD_EFFECTS,
        "supported_operations": [],
    },
    # FEAT-300 — formula fields (inert stub; evaluator in FEAT-301)
    FieldType.FORMULA: {
        "label": "Formula",
        "description": (
            "Computed field — result derived from a BEDMAS expression over "
            "other field values. Expression evaluation is FEAT-301. "
            "Renders as a read-only placeholder until the evaluator ships."
        ),
        "category": "advanced",
        "icon": "formula",
        "render_hint": "readonly",
        "supports_constraints": False,
        "is_container": False,
    },
}


def _seed() -> None:
    """Register one entry per ``FieldType`` value with the registry."""

    snippets = get_form_field_schema_snippets()
    for field_type in FieldType:
        meta = _BUILTIN_METADATA[field_type]
        snippet = snippets.get(field_type.value, {})
        register_field_control(
            field_type,
            label=meta["label"],
            description=meta["description"],
            category=meta["category"],
            icon=meta["icon"],
            snippet=snippet,
            render_hint=meta["render_hint"],
            supports_constraints=meta["supports_constraints"],
            is_container=meta["is_container"],
            supported_operators=meta.get("supported_operators", []),
            supported_effects=meta.get("supported_effects", []),
            supported_operations=meta.get("supported_operations", []),
        )


# Side effect on import: seed the registry once.
_seed()
