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
from copy import deepcopy
from typing import Any

from ..core.schema import FormField, FormSchema, FormSubsection, RenderedForm
from ..core.style import StyleSchema
from ..core.types import FieldType, LocalizedString
from .base import AbstractFormRenderer, FallbackRenderer, FieldRenderer

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
    # New field types (FEAT-167)
    # FEAT-448 (TASK-2336): SIGNATURE is a PNG data-URL string, not an object.
    FieldType.SIGNATURE: "string",
    FieldType.DYNAMIC_SELECT: "string",
    FieldType.TRANSFER_LIST: "array",
    FieldType.REMOTE_RESPONSE: "object",
    FieldType.AVAILABILITY: "array",
    FieldType.LOCATION: "string",
    FieldType.TAGS: "array",
    FieldType.NPS: "integer",
    FieldType.LIKERT: "integer",
    FieldType.RANKING: "integer",
    # Phase 3 — FEAT-170
    FieldType.REST: "object",
    # FEAT-300 — formula fields (evaluator is FEAT-301)
    FieldType.FORMULA: "number",
    # FEAT-448 (TASK-2337) — the twelve absorbed types (spec §4). Type
    # follows the value shape each control actually emits, not a native-vs-
    # fallback UI posture (JSON Schema has no rendering concept).
    FieldType.SEARCH: "string",
    FieldType.MASKED: "string",
    FieldType.COLOR_PICKER: "string",
    FieldType.EMOJI: "string",
    FieldType.CRON: "string",
    FieldType.TREE_SELECT: "array",  # single-select scalar via _UNION_SHAPES
    FieldType.SIGNATURE_PAD: "string",
    FieldType.CREDIT_CARD: "object",
    FieldType.IMAGE_DROPZONE: "object",  # array form via _UNION_SHAPES
    FieldType.MULTI_UPLOAD: "array",
    FieldType.AI_CAPTURE: "object",  # genuinely unconstrained via _UNION_SHAPES
    FieldType.PLACE: "object",
}

# FEAT-448 codex F4/F5/F6 — types whose accepted value is a UNION.
#
# `_TYPE_MAP` holds ONE JSON Schema type keyword per FieldType, which cannot
# express "string or array". The first pass papered over that in code comments
# — "object covers the common single-file case", "'object' is the common case,
# not a contract" — while publishing the narrow shape as if it were the
# contract. That is precisely the divergence this feature exists to end: the
# client asserts against this catalog (TASK-2338), so a published shape
# narrower than the validator's means correct submissions are rejected by our
# own contract. A comment does not reach the client.
#
# These fragments REPLACE the shape entirely rather than merging into it.
_UNION_SHAPES: dict[FieldType, dict[str, Any]] = {
    # validators.py accepts list[str] (multi) or a scalar node value (single)
    FieldType.TREE_SELECT: {
        "oneOf": [{"type": "string"}, {"type": "array", "items": {"type": "string"}}],
    },
    # validators.py accepts one {name,type,size,dataUrl} or a list of them
    FieldType.IMAGE_DROPZONE: {
        "oneOf": [
            {"type": "object"},
            {"type": "array", "items": {"type": "object"}},
        ],
    },
    # A third-party API's response. Its shape is explicitly not ours to define
    # (spec §4 Non-Goals), so publish NO constraint — an empty schema, which is
    # JSON Schema for "anything". Publishing `object` rejected server-valid
    # arrays and scalars.
    FieldType.AI_CAPTURE: {},
}


# FieldType → JSON Schema "format" keyword (where applicable)
_FORMAT_MAP: dict[FieldType, str] = {
    FieldType.EMAIL: "email",
    FieldType.URL: "uri",
    FieldType.DATE: "date",
    FieldType.DATETIME: "date-time",
    FieldType.TIME: "time",
    # New field types (FEAT-167)
    FieldType.SIGNATURE: "signature",
    FieldType.DYNAMIC_SELECT: "dynamic-select",
    FieldType.TRANSFER_LIST: "transfer-list",
    FieldType.REMOTE_RESPONSE: "remote-response",
    FieldType.AVAILABILITY: "availability",
    FieldType.LOCATION: "iso-country",
    FieldType.TAGS: "tags",
    FieldType.NPS: "nps",
    FieldType.LIKERT: "likert",
    FieldType.RANKING: "ranking",
    # Phase 3 — FEAT-170
    FieldType.REST: "rest",
    # FEAT-300 — formula fields
    FieldType.FORMULA: "formula",
    # FEAT-448 (TASK-2337)
    FieldType.SEARCH: "search",
    FieldType.MASKED: "masked",
    FieldType.COLOR_PICKER: "color-picker",
    FieldType.EMOJI: "emoji",
    FieldType.CRON: "cron",
    FieldType.TREE_SELECT: "tree-select",
    FieldType.SIGNATURE_PAD: "signature-pad",
    FieldType.CREDIT_CARD: "credit-card",
    FieldType.IMAGE_DROPZONE: "image-dropzone",
    FieldType.MULTI_UPLOAD: "multi-upload",
    FieldType.AI_CAPTURE: "ai-capture",
    FieldType.PLACE: "place",
}

# FieldType → structural JSON Schema extras (items/properties/required) that
# depend only on the type, never on a specific FormField instance. Shared by
# _field_to_property() (per-field rendering, below) and type_level_value_shape()
# (TASK-2338 — the type-only contract published in the /api/v1/form-controls
# catalog). Keeping exactly one dict here is the point: a ratchet that
# compared the catalog to a second hand-maintained shape list would just be
# the third list that drifts (spec §5.5).
_STRUCTURAL_EXTRAS: dict[FieldType, dict[str, Any]] = {
    # AVAILABILITY — array of slot objects
    FieldType.AVAILABILITY: {
        "items": {
            "type": "object",
            "properties": {
                "start": {"type": "string", "format": "date-time"},
                "end": {"type": "string", "format": "date-time"},
            },
        },
    },
    # TAGS — array of strings
    FieldType.TAGS: {"items": {"type": "string"}},
    # TRANSFER_LIST — array of string values
    FieldType.TRANSFER_LIST: {"items": {"type": "string"}},
    # FEAT-448 (TASK-2337) — TREE_SELECT: array of node values (single
    # selection also yields the node value per spec §4, but the schema
    # declares the multi-select shape as the structural contract).
    FieldType.TREE_SELECT: {"items": {"type": "string"}},
    # FEAT-448 (TASK-2337) — MULTI_UPLOAD: array of REST-like upload
    # envelopes (spec §4). Registered and typed, not further wired — the
    # singular-vs-list mismatch with _validate_rest_field is fieldsync
    # FEAT-514's blocker, not this renderer's.
    FieldType.MULTI_UPLOAD: {
        "items": {
            "type": "object",
            "properties": {
                "answer": {},
                "blob_ref": {"type": ["string", "null"]},
                "display": {"type": "string"},
            },
        },
    },
    # FEAT-448 (TASK-2337) — CREDIT_CARD: server-accepted shape only (spec
    # §4, TASK-2334) — brand/last4/name/expiry. cvv and the full PAN are
    # never part of this contract; the validator rejects them.
    FieldType.CREDIT_CARD: {
        "properties": {
            "brand": {"type": "string"},
            "last4": {"type": "string", "pattern": r"^\d{4}$"},
            "name": {"type": "string"},
            "expiry": {"type": "string"},
        },
        "required": ["brand", "last4", "name", "expiry"],
    },
    # FEAT-448 (TASK-2337) — PLACE: {country, state, city} — country is
    # required and ISO 3166 alpha-2 (mirrors LOCATION's contract); state/city
    # are optional and unconstrained (spec §3).
    FieldType.PLACE: {
        "properties": {
            "country": {"type": "string", "minLength": 2, "maxLength": 2},
            "state": {"type": ["string", "null"]},
            "city": {"type": ["string", "null"]},
        },
        "required": ["country"],
    },
}


def type_level_value_shape(field_type: FieldType) -> dict[str, Any]:
    """Return the type-only JSON Schema value-shape contract for a FieldType.

    FEAT-448 (TASK-2338): this is the single source of truth published in
    the ``GET /api/v1/form-controls`` catalog's ``value_shape`` field
    (``controls/builtin.py``) — a client asserts a submitted value against
    this shape without maintaining its own copy. It reuses exactly the same
    ``_TYPE_MAP`` / ``_FORMAT_MAP`` / ``_STRUCTURAL_EXTRAS`` that
    ``_field_to_property()`` uses for per-field rendering, so there is no
    second list to drift out of sync.

    Unlike ``_field_to_property()``, this is type-level only: it carries no
    per-field data (constraints, options, labels) since the catalog
    describes a *type*, not a specific field instance.

    Args:
        field_type: The FieldType to describe.

    Returns:
        A JSON Schema fragment: at minimum ``{"type": ...}``, plus
        ``"format"`` where applicable, plus any structural extras
        (``items``/``properties``/``required``) for types whose value shape
        is more than a bare scalar.
    """
    if field_type in _UNION_SHAPES:
        # A union cannot be narrowed to one `type` keyword; publish it whole.
        return deepcopy(_UNION_SHAPES[field_type])

    shape: dict[str, Any] = {"type": _TYPE_MAP.get(field_type, "string")}
    if field_type in _FORMAT_MAP:
        shape["format"] = _FORMAT_MAP[field_type]
    if field_type in _STRUCTURAL_EXTRAS:
        shape.update(deepcopy(_STRUCTURAL_EXTRAS[field_type]))
    return shape


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
    - x-depends-on: conditional visibility rule (serialized DependencyRule, including
      any ``operations`` on the rule)
    - x-post-depends: forward effects (serialized list of PostDependency objects,
      present only when ``field.post_depends`` is non-empty)
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
        """Initialize JsonSchemaRenderer with per-type renderer registry."""
        self.logger = logging.getLogger(__name__)
        self._fallback = FallbackRenderer()
        self._registry: dict[FieldType, FieldRenderer] = {}
        self._build_registry()

    def _build_registry(self) -> None:
        """Populate per-type renderer registry for JSON Schema output.

        Each entry wraps the _TYPE_MAP dispatch in an async FieldRenderer-
        compatible callable.
        """

        class _JsonSchemaFieldRenderer:
            """Async FieldRenderer stub for JSON Schema field dispatch."""

            def __init__(self_, renderer: "JsonSchemaRenderer") -> None:
                self_._r = renderer

            async def render(self_, field: FormField, *, locale: str = "en", prefilled: Any = None, error: str | None = None) -> Any:
                return {"type": _TYPE_MAP.get(field.field_type, "string"), "x-field-type": field.field_type.value}

        renderer_inst = _JsonSchemaFieldRenderer(self)
        self._registry = {ft: renderer_inst for ft in FieldType}

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

            for item in section.fields:
                if isinstance(item, FormSubsection):
                    sub_meta = {
                        "subsection_id": item.subsection_id,
                        "title": _resolve(item.title, locale) if item.title else None,
                        "description": _resolve(item.description, locale) if item.description else None,
                    }
                    for field in item.fields:
                        prop = self._field_to_property(field, locale, prefilled)
                        prop["x-section"] = section_meta
                        prop["x-subsection"] = sub_meta
                        if section.depends_on:
                            prop["x-section-depends-on"] = section.depends_on
                        if item.depends_on:
                            prop["x-subsection-depends-on"] = item.depends_on.model_dump()
                        properties[field.field_id] = prop
                        if field.required:
                            required.append(field.field_id)
                else:
                    prop = self._field_to_property(item, locale, prefilled)
                    prop["x-section"] = section_meta

                    if section.depends_on:
                        prop["x-section-depends-on"] = section.depends_on

                    properties[item.field_id] = prop

                    if item.required:
                        required.append(item.field_id)

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

        # NPS / LIKERT / RANKING — add minimum/maximum from scale constraints
        if ft == FieldType.NPS:
            prop["minimum"] = 0
            prop["maximum"] = 10
        elif ft in (FieldType.LIKERT, FieldType.RANKING):
            if field.constraints:
                if field.constraints.scale_min is not None:
                    prop["minimum"] = field.constraints.scale_min
                if field.constraints.scale_max is not None:
                    prop["maximum"] = field.constraints.scale_max
            if "minimum" not in prop:
                prop["minimum"] = 0
            if "maximum" not in prop:
                prop["maximum"] = 5 if ft == FieldType.RANKING else 4

        # Structural extras (items/properties/required) that depend only on
        # the FieldType, not on any per-instance data — see _STRUCTURAL_EXTRAS
        # below. Deep-copied so mutating `prop` never corrupts the shared dict.
        if ft in _STRUCTURAL_EXTRAS:
            prop.update(deepcopy(_STRUCTURAL_EXTRAS[ft]))

        # DYNAMIC_SELECT — options source required; enum not pre-set
        if ft == FieldType.DYNAMIC_SELECT and field.options_source:
            prop["x-options-source"] = field.options_source.model_dump()

        # Relation metadata (FEAT-456) — unconditional on any field_type the
        # TASK-2411 combination validator allowed (not gated on DYNAMIC_SELECT).
        # The ONLY renderer that surfaces this; the other six document it as
        # an intentional no-op.
        if field.relation:
            prop["x-relation"] = field.relation.model_dump(exclude_none=True)

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

        # Pre-dependency rule (serialized including any operations)
        if field.depends_on:
            prop["x-depends-on"] = field.depends_on.model_dump()

        # Forward effects (post-dependencies) — emitted as x-post-depends when present
        if field.post_depends:
            prop["x-post-depends"] = [p.model_dump() for p in field.post_depends]

        # Placeholder
        if field.placeholder:
            prop["x-placeholder"] = _resolve(field.placeholder, locale)

        # Read-only
        if field.read_only:
            prop["readOnly"] = True
            prop["x-read-only"] = True

        # REST — native object schema with x-parrot-rest extension (FEAT-170)
        if ft == FieldType.REST:
            prop["properties"] = {
                "answer": {},  # heterogeneous — any type
                "blob_ref": {"type": ["string", "null"]},
            }
            prop["required"] = ["answer"]
            # Populate x-parrot-rest from meta["rest"]
            rest_meta = (field.meta or {}).get("rest", {})
            # Public additional_args render as siblings on the form; emit a
            # public-only projection plus the full list so the frontend can
            # both render inputs and round-trip the spec.
            all_args = rest_meta.get("additional_args") or []
            public_args = [
                {
                    "name": a.get("name"),
                    "data_type": a.get("data_type", "string"),
                    "required": bool(a.get("required", False)),
                    "label": a.get("label"),
                    "description": a.get("description"),
                    "default": a.get("value"),
                }
                for a in all_args
                if isinstance(a, dict) and a.get("visibility") == "public"
            ]
            prop["x-parrot-rest"] = {
                "mode": rest_meta.get("mode"),
                "response_path": rest_meta.get("response_path"),
                "display_template": rest_meta.get("display_template"),
                # FEAT-421: `{tenant}` is a client-side template placeholder
                # — like the pre-existing `{form_id}`/`{field_id}` — that
                # the consumer substitutes with the real tenant slug before
                # issuing the upload request (see docs/migration/
                # feat-421-forms-tenant-in-url.md).
                "upload_url_template": (
                    "/api/v1/{tenant}/forms/{form_id}/fields/{field_id}/upload"
                ),
                "additional_args": all_args,
                "public_args": public_args,
            }

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
