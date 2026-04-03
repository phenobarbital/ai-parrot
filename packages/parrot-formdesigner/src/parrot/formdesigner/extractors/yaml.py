"""YAML extractor for FormSchema generation.

Parses YAML form definitions into FormSchema instances. Supports both the
legacy format (used by existing form YAML files) and the new format with
full i18n, constraints, and dependency rules.

Uses yaml_rs (Rust) when available, falls back to PyYAML.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from ..core.constraints import ConditionOperator, DependencyRule, FieldCondition, FieldConstraints
from ..core.options import FieldOption
from ..core.schema import FormField, FormSchema, FormSection, SubmitAction
from ..core.types import FieldType, LocalizedString

# Try yaml_rs first, then PyYAML
try:
    from parrot.yaml_rs import loads as yaml_loads

    _YAML_BACKEND = "yaml_rs"
except ImportError:
    try:
        import yaml

        yaml_loads = yaml.safe_load
        _YAML_BACKEND = "pyyaml"
    except ImportError:
        yaml_loads = None
        _YAML_BACKEND = "none"


# Map legacy FieldType values to new FieldType enum values
_LEGACY_FIELD_TYPE_MAP: dict[str, FieldType] = {
    "text": FieldType.TEXT,
    "textarea": FieldType.TEXT_AREA,
    "text_area": FieldType.TEXT_AREA,
    "number": FieldType.NUMBER,
    "integer": FieldType.INTEGER,
    "boolean": FieldType.BOOLEAN,
    "toggle": FieldType.BOOLEAN,
    "date": FieldType.DATE,
    "datetime": FieldType.DATETIME,
    "time": FieldType.TIME,
    "choice": FieldType.SELECT,
    "select": FieldType.SELECT,
    "multichoice": FieldType.MULTI_SELECT,
    "multi_select": FieldType.MULTI_SELECT,
    "file": FieldType.FILE,
    "image": FieldType.IMAGE,
    "color": FieldType.COLOR,
    "url": FieldType.URL,
    "email": FieldType.EMAIL,
    "phone": FieldType.PHONE,
    "password": FieldType.PASSWORD,
    "hidden": FieldType.HIDDEN,
    "group": FieldType.GROUP,
    "array": FieldType.ARRAY,
}

# Map legacy validation rule names to FieldConstraints attributes
_LEGACY_VALIDATION_MAP = {
    "min_length": "min_length",
    "max_length": "max_length",
    "min_value": "min_value",
    "max_value": "max_value",
    "pattern": "pattern",
    "min_items": "min_items",
    "max_items": "max_items",
}


class YamlExtractor:
    """Parses YAML form definitions into FormSchema instances.

    Supports two YAML formats:

    Legacy format (backward compatible):
        - Fields use ``name`` and ``type`` keys
        - Validation rules use legacy names (min_length, max_length, etc.)
        - FieldType values use old names (choice, multichoice, toggle, textarea)
        - Section-level ``name`` and ``title`` keys

    New format:
        - Fields use ``field_id`` and ``field_type`` keys
        - Constraints use the ``constraints`` block
        - Dependency rules use ``depends_on`` block
        - Labels/titles can be i18n dicts

    Example:
        extractor = YamlExtractor()
        schema = extractor.extract_from_string(yaml_content)
        schema = extractor.extract_from_file("/path/to/form.yaml")
    """

    def extract(self, content: str) -> FormSchema:
        """Parse YAML string content into a FormSchema.

        Alias for extract_from_string for API consistency.

        Args:
            content: YAML string to parse.

        Returns:
            FormSchema representing the parsed YAML.
        """
        return self.extract_from_string(content)

    def extract_from_string(self, content: str) -> FormSchema:
        """Parse YAML string content into a FormSchema.

        Args:
            content: YAML string to parse.

        Returns:
            FormSchema representing the parsed YAML.

        Raises:
            ImportError: If no YAML parser is available.
            ValueError: If the YAML content is invalid or missing required fields.
        """
        if yaml_loads is None:
            raise ImportError(
                "No YAML parser available. Install yaml_rs or PyYAML: pip install pyyaml"
            )
        data = yaml_loads(content)
        if not isinstance(data, dict):
            raise ValueError("YAML content must be a mapping (dict) at the top level")
        return self._parse_schema(data)

    def extract_from_file(self, path: str | Path) -> FormSchema:
        """Load and parse a YAML form definition file.

        Args:
            path: Path to the YAML file.

        Returns:
            FormSchema representing the parsed YAML.

        Raises:
            FileNotFoundError: If the path does not exist.
            ImportError: If no YAML parser is available.
        """
        file_path = Path(path)
        content = file_path.read_text(encoding="utf-8")
        return self.extract_from_string(content)

    def _parse_schema(self, data: dict[str, Any]) -> FormSchema:
        """Parse a dict (from YAML) into a FormSchema.

        Args:
            data: Dict parsed from YAML content.

        Returns:
            FormSchema instance.
        """
        form_id = data.get("form_id", "unnamed_form")
        title = self._parse_localized(data.get("title", form_id))
        description = self._parse_localized(data.get("description")) if "description" in data else None
        version = str(data.get("version", "1.0"))
        cancel_allowed = data.get("cancel_allowed", True)
        meta = data.get("meta") or data.get("metadata")

        # Parse sections
        sections: list[FormSection] = []
        for section_data in data.get("sections", []):
            sections.append(self._parse_section(section_data))

        # Parse submit action
        submit: SubmitAction | None = None
        if "submit" in data and data["submit"]:
            submit = self._parse_submit_action(data["submit"])
        elif "submit_action" in data and data["submit_action"]:
            # Legacy key
            submit = SubmitAction(
                action_type="tool_call",
                action_ref=data["submit_action"],
            )

        return FormSchema(
            form_id=form_id,
            version=version,
            title=title,
            description=description,
            sections=sections,
            submit=submit,
            cancel_allowed=cancel_allowed,
            meta=meta,
        )

    def _parse_section(self, data: dict[str, Any]) -> FormSection:
        """Parse a section dict into a FormSection.

        Supports both legacy (``name``) and new (``section_id``) key formats.

        Args:
            data: Section dict from YAML.

        Returns:
            FormSection instance.
        """
        # Support both legacy "name" and new "section_id"
        section_id = data.get("section_id") or data.get("name", "section")
        title = self._parse_localized(data.get("title"))
        description = self._parse_localized(data.get("description"))
        meta = data.get("meta")

        # Parse depends_on if present
        depends_on = None
        if "depends_on" in data and data["depends_on"]:
            depends_on = self._parse_dependency_rule(data["depends_on"])

        fields: list[FormField] = []
        for field_data in data.get("fields", []):
            parsed = self._parse_field(field_data)
            if parsed is not None:
                fields.append(parsed)

        return FormSection(
            section_id=section_id,
            title=title,
            description=description,
            fields=fields,
            depends_on=depends_on,
            meta=meta,
        )

    def _parse_field(self, data: Any) -> FormField | None:
        """Parse a field dict into a FormField.

        Supports two formats:
        - ``{ name: "field", type: "text", ... }`` (legacy)
        - ``{ field_name: { type: "text", ... } }`` (legacy alternate)
        - ``{ field_id: "field", field_type: "text", ... }`` (new)

        Args:
            data: Field dict from YAML.

        Returns:
            FormField instance, or None if data is invalid.
        """
        if not isinstance(data, dict):
            return None

        # Determine field_id and config
        if "field_id" in data:
            # New format
            field_id = data["field_id"]
            field_config = data
        elif "name" in data:
            # Legacy format with explicit name
            field_id = data["name"]
            field_config = data
        else:
            # Legacy alternate: { field_name: { type: "text", ... } }
            field_id = next(iter(data))
            inner = data[field_id]
            if isinstance(inner, str):
                inner = {"type": inner}
            field_config = dict(inner)
            field_config["name"] = field_id

        # Parse field type
        raw_type = field_config.get("field_type") or field_config.get("type", "text")
        field_type = _LEGACY_FIELD_TYPE_MAP.get(str(raw_type).lower(), FieldType.TEXT)

        # Parse label
        label_raw = field_config.get("label", field_id.replace("_", " ").title())
        label = self._parse_localized(label_raw)

        # Parse description and placeholder
        description = self._parse_localized(field_config.get("description"))
        placeholder = self._parse_localized(field_config.get("placeholder"))

        # Required
        required = field_config.get("required", False)
        default = field_config.get("default")
        read_only = field_config.get("read_only", False)

        # Parse constraints: new-style "constraints" block + legacy "validation" block
        constraints = self._parse_constraints(field_config)

        # Parse options/choices
        options = self._parse_options(field_config)

        # Parse depends_on
        depends_on = None
        if "depends_on" in field_config and field_config["depends_on"]:
            depends_on = self._parse_dependency_rule(field_config["depends_on"])

        # Parse children (GROUP fields)
        children = None
        if "children" in field_config and field_config["children"]:
            children = [
                self._parse_field(child)
                for child in field_config["children"]
                if child is not None
            ]
            children = [c for c in children if c is not None]

        # Parse item_template (ARRAY fields)
        item_template = None
        if "item_template" in field_config and field_config["item_template"]:
            item_template = self._parse_field(field_config["item_template"])

        meta = field_config.get("meta")

        return FormField(
            field_id=field_id,
            field_type=field_type,
            label=label,
            description=description,
            placeholder=placeholder,
            required=required,
            default=default,
            read_only=read_only,
            constraints=constraints if constraints and self._has_constraints(constraints) else None,
            options=options or None,
            depends_on=depends_on,
            children=children or None,
            item_template=item_template,
            meta=meta,
        )

    def _parse_constraints(self, field_config: dict[str, Any]) -> FieldConstraints | None:
        """Parse constraints from both new and legacy formats.

        New format: ``constraints: { min_length: 2, pattern: "..." }``
        Legacy format: ``validation: { min_length: 2, pattern: "..." }``

        Args:
            field_config: Field configuration dict.

        Returns:
            FieldConstraints instance or None.
        """
        kwargs: dict[str, Any] = {}

        # New-style constraints block
        constraints_data = field_config.get("constraints", {}) or {}
        if isinstance(constraints_data, dict):
            for key, value in constraints_data.items():
                if key in (
                    "min_length", "max_length", "min_value", "max_value", "step",
                    "pattern", "pattern_message", "min_items", "max_items",
                    "allowed_mime_types", "max_file_size_bytes",
                ):
                    kwargs[key] = value

        # Legacy validation block
        validation_data = field_config.get("validation", {}) or {}
        if isinstance(validation_data, dict):
            for key, value in validation_data.items():
                if key == "message":
                    continue
                mapped = _LEGACY_VALIDATION_MAP.get(key)
                if mapped and mapped not in kwargs:
                    kwargs[mapped] = value

        if not kwargs:
            return None
        return FieldConstraints(**kwargs)

    def _parse_options(self, field_config: dict[str, Any]) -> list[FieldOption] | None:
        """Parse options from 'options' or legacy 'choices' keys.

        Args:
            field_config: Field configuration dict.

        Returns:
            List of FieldOption or None.
        """
        # New-style: options list
        raw_options = field_config.get("options")
        # Legacy: choices list
        raw_choices = field_config.get("choices")
        source = raw_options or raw_choices
        if not source or not isinstance(source, list):
            return None

        options: list[FieldOption] = []
        for item in source:
            if isinstance(item, str):
                options.append(FieldOption(value=item, label=item))
            elif isinstance(item, dict):
                value = item.get("value", item.get("id", ""))
                label = self._parse_localized(
                    item.get("label") or item.get("title") or value
                )
                desc = self._parse_localized(item.get("description"))
                options.append(FieldOption(
                    value=str(value),
                    label=label,
                    description=desc,
                    disabled=item.get("disabled", False),
                    icon=item.get("icon"),
                ))
        return options if options else None

    def _parse_dependency_rule(self, data: dict[str, Any]) -> DependencyRule | None:
        """Parse a depends_on block into a DependencyRule.

        Args:
            data: Dependency rule dict from YAML.

        Returns:
            DependencyRule instance or None.
        """
        if not isinstance(data, dict):
            return None

        conditions_data = data.get("conditions", [])
        conditions: list[FieldCondition] = []
        for cond in conditions_data:
            if isinstance(cond, dict):
                field_id = cond.get("field_id", "")
                op_str = str(cond.get("operator", "eq")).lower()
                try:
                    operator = ConditionOperator(op_str)
                except ValueError:
                    operator = ConditionOperator.EQ
                value = cond.get("value")
                conditions.append(FieldCondition(
                    field_id=field_id,
                    operator=operator,
                    value=value,
                ))

        if not conditions:
            return None

        logic = data.get("logic", "and")
        effect = data.get("effect", "show")

        return DependencyRule(
            conditions=conditions,
            logic=logic,
            effect=effect,
        )

    def _parse_submit_action(self, data: dict[str, Any]) -> SubmitAction | None:
        """Parse a submit action block.

        Args:
            data: Submit action dict from YAML.

        Returns:
            SubmitAction instance or None.
        """
        if not isinstance(data, dict):
            return None
        action_type = data.get("action_type", "tool_call")
        action_ref = data.get("action_ref", "")
        method = data.get("method", "POST")
        confirm_message = self._parse_localized(data.get("confirm_message"))
        return SubmitAction(
            action_type=action_type,
            action_ref=action_ref,
            method=method,
            confirm_message=confirm_message,
        )

    def _parse_localized(self, value: Any) -> LocalizedString | None:
        """Parse a value as a LocalizedString (str or dict).

        Args:
            value: Raw value from YAML (str, dict, or None).

        Returns:
            LocalizedString or None.
        """
        if value is None:
            return None
        if isinstance(value, str):
            return value
        if isinstance(value, dict):
            return {str(k): str(v) for k, v in value.items()}
        return str(value)

    def _has_constraints(self, constraints: FieldConstraints) -> bool:
        """Check if a FieldConstraints has any non-None values.

        Args:
            constraints: FieldConstraints to check.

        Returns:
            True if any constraint is set.
        """
        return any(v is not None for v in constraints.model_dump().values())


# Alias for API consistency
YAMLExtractor = YamlExtractor
