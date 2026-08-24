"""JSON Schema extractor for FormSchema generation.

Converts standard JSON Schema dicts into FormSchema instances.
Supports type mapping, constraint extraction, $ref resolution,
format keywords, enum conversion, and oneOf/anyOf union types.
"""

from __future__ import annotations

import logging
from typing import Any

from ..core.constraints import (
    DependencyRule,
    FieldConstraints,
    PostDependency,
)
from ..core.options import FieldOption, OptionsSource
from ..core.relations import EntityRef, RelationSpec
from ..core.resolution import resolve_rule_references
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
    # New field types (FEAT-167)
    "signature": FieldType.SIGNATURE,
    "dynamic-select": FieldType.DYNAMIC_SELECT,
    "dynamic_select": FieldType.DYNAMIC_SELECT,
    "transfer-list": FieldType.TRANSFER_LIST,
    "transfer_list": FieldType.TRANSFER_LIST,
    "remote-response": FieldType.REMOTE_RESPONSE,
    "remote_response": FieldType.REMOTE_RESPONSE,
    "availability": FieldType.AVAILABILITY,
    "location": FieldType.LOCATION,
    "place": FieldType.PLACE,
    "tags": FieldType.TAGS,
    "nps": FieldType.NPS,
    "likert": FieldType.LIKERT,
    "ranking": FieldType.RANKING,
    # Phase 3 — FEAT-170
    "rest": FieldType.REST,
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

        form = FormSchema(
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
        # FEAT-393: mint UIDs (free — model default_factory) and resolve any
        # rule references before returning. JSON Schema itself carries no
        # depends_on/post_depends, but this keeps every extractor's output
        # uniformly resolved before it reaches the registry/storage.
        return resolve_rule_references(form)

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

        # Handle x-parrot-rest extension → FieldType.REST (FEAT-170)
        x_parrot_rest = prop.get("x-parrot-rest")
        if x_parrot_rest and isinstance(x_parrot_rest, dict):
            meta = {"rest": x_parrot_rest}
            label = prop.get("title", name.replace("_", " ").title())
            description = prop.get("description")
            default = prop.get("default")
            constraints = self._extract_constraints(prop)
            return FormField(
                field_id=name,
                field_type=FieldType.REST,
                label=label,
                description=description,
                required=required,
                default=default,
                constraints=constraints if constraints and self._has_constraints(constraints) else None,
                meta=meta,
            )

        field_type = self._map_type(prop)
        label = prop.get("title", name.replace("_", " ").title())
        description = prop.get("description")
        default = prop.get("default")
        constraints = self._extract_constraints(prop)

        # Handle enum → SELECT
        options: list[FieldOption] | None = None
        if "enum" in prop:
            field_type = FieldType.SELECT
            options = [FieldOption(value=str(v), label=str(v)) for v in prop["enum"] if v is not None]

        # Handle x-options-source → OptionsSource (FEAT-167)
        options_source: OptionsSource | None = None
        x_src = prop.get("x-options-source")
        if x_src and isinstance(x_src, dict):
            options_source = OptionsSource(
                source_type=x_src.get("source_type", "endpoint"),
                source_ref=x_src.get("source_ref", ""),
                value_field=x_src.get("value_field", "value"),
                label_field=x_src.get("label_field", "label"),
                cache_ttl_seconds=x_src.get("cache_ttl_seconds"),
                http_method=x_src.get("http_method", "GET"),
                auth_ref=x_src.get("auth_ref"),
            )

        # Handle x-relation → RelationSpec (FEAT-456)
        relation: RelationSpec | None = None
        x_relation = prop.get("x-relation")
        if x_relation and isinstance(x_relation, dict):
            relation = self._parse_relation(x_relation, name)

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
                # FEAT-393: suffix with the parent's name — a bare "item"
                # collides form-wide (walk_fields visits item_template) when
                # a form has more than one ARRAY field.
                item_template = FormField(
                    field_id=f"{name}_item",
                    field_type=item_type,
                    label="Item",
                )

        # Reconstruct depends_on from x-depends-on extension (TASK-1527 round-trip, FEAT-234)
        depends_on: DependencyRule | None = None
        x_depends_on = prop.get("x-depends-on")
        if x_depends_on and isinstance(x_depends_on, dict):
            try:
                depends_on = DependencyRule.model_validate(x_depends_on)
            except Exception:  # noqa: BLE001
                logger.warning("Could not reconstruct depends_on for field '%s'", name)

        # Reconstruct post_depends from x-post-depends extension (TASK-1527 round-trip, FEAT-234)
        post_depends: list[PostDependency] | None = None
        x_post_depends = prop.get("x-post-depends")
        if x_post_depends and isinstance(x_post_depends, list):
            parsed_posts = []
            for pd_data in x_post_depends:
                if isinstance(pd_data, dict):
                    try:
                        parsed_posts.append(PostDependency.model_validate(pd_data))
                    except Exception:  # noqa: BLE001
                        logger.warning("Could not reconstruct a post_depends entry for field '%s'", name)
            post_depends = parsed_posts or None

        return FormField(
            field_id=name,
            field_type=field_type,
            label=label,
            description=description,
            required=required,
            default=default,
            constraints=constraints if constraints and self._has_constraints(constraints) else None,
            options=options,
            options_source=options_source,
            relation=relation,
            children=children if children else None,
            item_template=item_template,
            depends_on=depends_on,
            post_depends=post_depends,
        )

    def _parse_relation(self, x_relation: dict[str, Any], field_id: str) -> RelationSpec:
        """Parse an ``x-relation`` extension dict into a ``RelationSpec``
        (FEAT-456). Mirrors the ``x-options-source`` handling above.

        Args:
            x_relation: The ``x-relation`` dict from the JSON Schema property.
            field_id: The owning field's id, used in error messages.

        Returns:
            The parsed ``RelationSpec``.

        Raises:
            TypeError: If ``x-relation.target`` is not a mapping.
            ValueError: If the block does not parse into a valid
                ``RelationSpec`` — a malformed relation must not silently
                degrade to a plain field.
        """
        raw = dict(x_relation)
        target_raw = raw.pop("target", None)
        if not isinstance(target_raw, dict):
            raise TypeError(f"Field {field_id!r}: x-relation.target must be a mapping " "with 'namespace' and 'entity'")
        try:
            target = EntityRef(**target_raw)
            return RelationSpec(target=target, **raw)
        except Exception as exc:
            raise ValueError(f"Field {field_id!r}: invalid x-relation block: {exc}") from exc

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
        # FEAT-448 codex F1 — `x-field-type` FIRST, before any heuristic.
        # The renderer already stamps every property with it
        # (`renderers/jsonschema.py`), and nothing read it, so a schema could
        # be emitted and not read back: `search` returned as TEXT,
        # `tree_select` as ARRAY, `credit_card` as GROUP. Adding one
        # `_FORMAT_MAP` entry per new type would have fixed today's twelve and
        # been forgotten by the thirteenth; honouring the marker fixes every
        # type at once, including the ones nobody has invented yet.
        declared = prop.get("x-field-type")
        if isinstance(declared, str):
            try:
                return FieldType(declared)
            except ValueError:
                logger.warning(
                    "x-field-type '%s' is not a known FieldType; falling back " "to format/type inference",
                    declared,
                )

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
