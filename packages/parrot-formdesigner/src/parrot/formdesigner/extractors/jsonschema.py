"""JSON Schema extractor for FormSchema generation.

Converts standard JSON Schema dicts into FormSchema instances.
Supports type mapping, constraint extraction, $ref resolution,
format keywords, enum conversion, and oneOf/anyOf union types.
"""

from __future__ import annotations

import logging
from typing import Any

from ..core.constraints import FieldConstraints
from ..core.options import FieldOption
from ..core.schema import FormField, FormSchema, FormSection
from ..core.types import FieldType

logger = logging.getLogger(__name__)

# JSON Schema type → FieldType mapping
_TYPE_MAP: dict[str, FieldType] = {
    "string": FieldType.TEXT,
    "number": FieldType.NUMBER,
    "integer": FieldType.INTEGER,
    "boolean": FieldType.BOOLEAN,
    "array": FieldType.ARRAY,
    "object": FieldType.GROUP,
}

# JSON Schema format → FieldType override mapping
_FORMAT_MAP: dict[str, FieldType] = {
    "email": FieldType.EMAIL,
    "uri": FieldType.URL,
    "url": FieldType.URL,
    "date": FieldType.DATE,
    "date-time": FieldType.DATETIME,
    "time": FieldType.TIME,
    "password": FieldType.PASSWORD,
    "color": FieldType.COLOR,
    "phone": FieldType.PHONE,
}


class JsonSchemaExtractor:
    """Converts JSON Schema dicts into FormSchema instances.

    Supports:
    - JSON Schema type mapping (string/number/integer/boolean/array/object)
    - JSON Schema format mapping (email/uri/date/date-time/time)
    - Constraint extraction (minLength, maxLength, minimum, maximum, pattern)
    - $ref and $defs/$definitions resolution
    - enum values as SELECT options
    - required array for field requiredness
    - oneOf/anyOf union types (first non-null type wins)
    - Nested object properties as GROUP fields

    Example:
        extractor = JsonSchemaExtractor()
        schema_dict = MyModel.model_json_schema()
        form = extractor.extract(schema_dict, title="My Form")
    """

    def extract(
        self,
        schema: dict[str, Any],
        *,
        form_id: str | None = None,
        title: str | None = None,
    ) -> FormSchema:
        """Convert a JSON Schema dict into a FormSchema.

        Args:
            schema: JSON Schema dict (OpenAPI-compatible, Pydantic output, etc.).
            form_id: Optional form ID. Defaults to "form".
            title: Optional form title. Defaults to schema title or "Form".

        Returns:
            FormSchema representing the JSON Schema structure.
        """
        resolved_form_id = form_id or "form"
        resolved_title = title or schema.get("title", "Form")

        # Resolve top-level ref if needed
        root_schema = schema
        if "$ref" in schema:
            schema = self._resolve_ref(schema["$ref"], root_schema)

        # Extract fields from top-level properties
        required_set = set(schema.get("required", []))
        properties = schema.get("properties", {})
        fields: list[FormField] = []

        for prop_name, prop_schema in properties.items():
            is_required = prop_name in required_set
            field = self._property_to_field(
                name=prop_name,
                prop=prop_schema,
                required=is_required,
                root_schema=root_schema,
            )
            fields.append(field)

        return FormSchema(
            form_id=resolved_form_id,
            title=resolved_title,
            sections=[
                FormSection(
                    section_id="fields",
                    title=resolved_title,
                    fields=fields,
                )
            ],
        )

    def _resolve_ref(self, ref: str, root_schema: dict[str, Any]) -> dict[str, Any]:
        """Resolve a JSON Schema $ref to the referenced schema dict.

        Supports local refs: ``#/$defs/Name`` and ``#/definitions/Name``.

        Args:
            ref: The $ref string (e.g., "#/$defs/Address").
            root_schema: The root schema for resolving local refs.

        Returns:
            The referenced schema dict.

        Raises:
            ValueError: If the ref cannot be resolved.
        """
        if not ref.startswith("#"):
            logger.warning("External $ref not supported: %s — using empty object", ref)
            return {"type": "object", "properties": {}}

        # Parse path segments after "#/"
        path = ref.lstrip("#/").split("/")
        current: Any = root_schema
        for segment in path:
            if isinstance(current, dict) and segment in current:
                current = current[segment]
            else:
                logger.warning("Could not resolve $ref '%s' — defaulting to TEXT", ref)
                return {"type": "string"}

        if not isinstance(current, dict):
            return {"type": "string"}
        return current

    def _property_to_field(
        self,
        name: str,
        prop: dict[str, Any],
        required: bool,
        root_schema: dict[str, Any],
    ) -> FormField:
        """Convert a single JSON Schema property to a FormField.

        Args:
            name: Property name.
            prop: Property schema dict.
            required: Whether this field is in the parent's required array.
            root_schema: Root schema for $ref resolution.

        Returns:
            FormField instance.
        """
        # Resolve $ref if present
        if "$ref" in prop:
            prop = self._resolve_ref(prop["$ref"], root_schema)

        # Handle oneOf/anyOf — pick first non-null schema
        if "oneOf" in prop or "anyOf" in prop:
            variants = prop.get("oneOf") or prop.get("anyOf") or []
            non_null = [v for v in variants if v.get("type") != "null"]
            prop = non_null[0] if non_null else {"type": "string"}
            if "$ref" in prop:
                prop = self._resolve_ref(prop["$ref"], root_schema)

        field_type = self._map_type(prop)
        label = prop.get("title", name.replace("_", " ").title())
        description = prop.get("description")
        default = prop.get("default")
        constraints = self._extract_constraints(prop)

        # Handle enum → SELECT
        options: list[FieldOption] | None = None
        if "enum" in prop:
            field_type = FieldType.SELECT
            options = [
                FieldOption(value=str(v), label=str(v))
                for v in prop["enum"]
                if v is not None
            ]

        # Handle object → GROUP with children
        children: list[FormField] | None = None
        if field_type == FieldType.GROUP:
            nested_required = set(prop.get("required", []))
            nested_props = prop.get("properties", {})
            children = [
                self._property_to_field(
                    name=child_name,
                    prop=child_prop,
                    required=child_name in nested_required,
                    root_schema=root_schema,
                )
                for child_name, child_prop in nested_props.items()
            ]

        # Handle array → ARRAY with item_template
        item_template: FormField | None = None
        if field_type == FieldType.ARRAY:
            items_schema = prop.get("items")
            if items_schema:
                if "$ref" in items_schema:
                    items_schema = self._resolve_ref(items_schema["$ref"], root_schema)
                item_type = self._map_type(items_schema)
                item_template = FormField(
                    field_id="item",
                    field_type=item_type,
                    label="Item",
                )

        return FormField(
            field_id=name,
            field_type=field_type,
            label=label,
            description=description,
            required=required,
            default=default,
            constraints=constraints if constraints and self._has_constraints(constraints) else None,
            options=options,
            children=children if children else None,
            item_template=item_template,
        )

    def _map_type(self, prop: dict[str, Any]) -> FieldType:
        """Map a JSON Schema property to a FieldType.

        Priority: format keyword > type keyword > default TEXT.

        Args:
            prop: JSON Schema property dict.

        Returns:
            FieldType for this property.
        """
        # Format takes priority (e.g., "string" + "email" format → EMAIL)
        fmt = prop.get("format", "").lower()
        if fmt and fmt in _FORMAT_MAP:
            return _FORMAT_MAP[fmt]

        raw_type = prop.get("type", "string")
        if isinstance(raw_type, list):
            # Handle type arrays (e.g., ["string", "null"]) — pick first non-null
            non_null = [t for t in raw_type if t != "null"]
            raw_type = non_null[0] if non_null else "string"

        field_type = _TYPE_MAP.get(str(raw_type).lower())
        if field_type is None:
            logger.debug("Unknown JSON Schema type '%s' — defaulting to TEXT", raw_type)
            return FieldType.TEXT

        return field_type

    def _extract_constraints(self, prop: dict[str, Any]) -> FieldConstraints:
        """Extract FieldConstraints from a JSON Schema property.

        Maps JSON Schema constraint keywords to FieldConstraints fields.

        Args:
            prop: JSON Schema property dict.

        Returns:
            FieldConstraints instance (may have all None values).
        """
        return FieldConstraints(
            min_length=prop.get("minLength"),
            max_length=prop.get("maxLength"),
            min_value=float(prop["minimum"]) if "minimum" in prop else None,
            max_value=float(prop["maximum"]) if "maximum" in prop else None,
            pattern=prop.get("pattern"),
            min_items=prop.get("minItems"),
            max_items=prop.get("maxItems"),
        )

    def _has_constraints(self, constraints: FieldConstraints) -> bool:
        """Check if a FieldConstraints has any non-None values.

        Args:
            constraints: FieldConstraints to check.

        Returns:
            True if any constraint is set.
        """
        return any(v is not None for v in constraints.model_dump().values())


# Alias for API consistency
JSONSchemaExtractor = JsonSchemaExtractor
