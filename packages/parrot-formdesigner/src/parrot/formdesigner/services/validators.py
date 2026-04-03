"""Platform-agnostic form validation for FormSchema.

This module provides FormValidator and ValidationResult for validating
form submission data against FormSchema constraints. The validator is
async-native to support ASYNC_REMOTE and UNIQUE validation callbacks.

Migrated and enhanced from parrot/integrations/msteams/dialogs/validator.py.
"""

import logging
import re
from typing import Any, Callable

from pydantic import BaseModel

from ..core.schema import FormField, FormSchema, FormSection
from ..core.types import FieldType, LocalizedString

logger = logging.getLogger(__name__)

# Standard regex patterns
EMAIL_PATTERN = re.compile(r"^[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}$")
URL_PATTERN = re.compile(r"^https?://[^\s/$.?#].[^\s]*$")
PHONE_PATTERN = re.compile(r"^\+?[\d\s\-().]{7,}$")


def _resolve_localized(value: LocalizedString | None, locale: str = "en") -> str | None:
    """Resolve a LocalizedString to a plain string using the given locale.

    Args:
        value: Either a plain string or a locale-keyed dict.
        locale: BCP 47 locale tag (e.g., "en", "es").

    Returns:
        Resolved string, or None if value is None.
    """
    if value is None:
        return None
    if isinstance(value, str):
        return value
    # Try exact locale match, then language-only match, then "en", then first value
    if locale in value:
        return value[locale]
    lang = locale.split("-")[0]
    if lang in value:
        return value[lang]
    if "en" in value:
        return value["en"]
    return next(iter(value.values()), None)


class ValidationResult(BaseModel):
    """Result of validating a form submission.

    Attributes:
        is_valid: Whether the entire submission passed validation.
        errors: Field-level error messages keyed by field_id.
        sanitized_data: Type-coerced and sanitized form data.
    """

    is_valid: bool
    errors: dict[str, list[str]]
    sanitized_data: dict[str, Any]


class FormValidator:
    """Platform-agnostic validator for FormSchema data.

    Validates form submission data against FormSchema constraints,
    including required checks, type coercion, regex patterns, numeric
    bounds, cross-field rules, and circular dependency detection.

    All validation methods are async to support ASYNC_REMOTE and UNIQUE
    validation callbacks specified via FormField.meta.

    Example:
        validator = FormValidator()
        result = await validator.validate(form_schema, submitted_data)
        if not result.is_valid:
            print(result.errors)
    """

    def __init__(self) -> None:
        """Initialize FormValidator."""
        self.logger = logging.getLogger(__name__)

    async def validate(
        self,
        form: FormSchema,
        data: dict[str, Any],
        *,
        locale: str = "en",
    ) -> ValidationResult:
        """Validate all form submission data against the schema.

        Args:
            form: The FormSchema to validate against.
            data: Submitted form data keyed by field_id.
            locale: Locale for error message resolution.

        Returns:
            ValidationResult with field-level errors and sanitized data.
        """
        errors: dict[str, list[str]] = {}
        sanitized: dict[str, Any] = {}

        # Detect circular dependencies first
        circular_errors = self._detect_circular_dependencies(form)
        if circular_errors:
            errors["__circular__"] = circular_errors
            return ValidationResult(is_valid=False, errors=errors, sanitized_data=sanitized)

        # Collect all fields from all sections
        all_fields: list[FormField] = []
        for section in form.sections:
            all_fields.extend(self._collect_fields(section))

        # Validate each field
        for field in all_fields:
            field_errors = await self.validate_field(
                field,
                data.get(field.field_id),
                all_data=data,
                locale=locale,
            )
            if field_errors:
                errors[field.field_id] = field_errors
            else:
                coerced = self._coerce_value(data.get(field.field_id), field)
                if coerced is not None:
                    sanitized[field.field_id] = coerced

        return ValidationResult(
            is_valid=len(errors) == 0,
            errors=errors,
            sanitized_data=sanitized,
        )

    async def validate_field(
        self,
        field: FormField,
        value: Any,
        *,
        all_data: dict[str, Any] | None = None,
        locale: str = "en",
    ) -> list[str]:
        """Validate a single field value against its constraints.

        Args:
            field: The FormField definition.
            value: The submitted value.
            all_data: Full submission data for cross-field validation.
            locale: Locale for error message resolution.

        Returns:
            List of error messages (empty list if valid).
        """
        errors: list[str] = []

        # Resolve label for error messages
        label = _resolve_localized(field.label, locale) or field.field_id

        # Required check
        is_empty = value is None or (isinstance(value, str) and not value.strip())
        if field.required and is_empty:
            errors.append(f"{label} is required")
            return errors

        # If not required and empty, skip further validation
        if is_empty:
            return errors

        # Type coercion
        try:
            coerced = self._coerce_value(value, field)
        except (ValueError, TypeError) as exc:
            errors.append(str(exc))
            return errors

        # Apply FieldConstraints
        if field.constraints:
            c = field.constraints
            if c.min_length is not None and isinstance(coerced, str):
                if len(coerced) < c.min_length:
                    errors.append(f"{label} must be at least {c.min_length} characters")
            if c.max_length is not None and isinstance(coerced, str):
                if len(coerced) > c.max_length:
                    errors.append(f"{label} must be at most {c.max_length} characters")
            if c.min_value is not None and isinstance(coerced, (int, float)):
                if coerced < c.min_value:
                    errors.append(f"{label} must be at least {c.min_value}")
            if c.max_value is not None and isinstance(coerced, (int, float)):
                if coerced > c.max_value:
                    errors.append(f"{label} must be at most {c.max_value}")
            if c.pattern is not None and isinstance(coerced, str):
                if not re.fullmatch(c.pattern, str(coerced)):
                    msg = _resolve_localized(c.pattern_message, locale)
                    errors.append(msg or f"{label} format is invalid")
            if c.min_items is not None and isinstance(coerced, list):
                if len(coerced) < c.min_items:
                    errors.append(f"{label} must have at least {c.min_items} items")
            if c.max_items is not None and isinstance(coerced, list):
                if len(coerced) > c.max_items:
                    errors.append(f"{label} must have at most {c.max_items} items")
            if c.allowed_mime_types and field.field_type in (FieldType.FILE, FieldType.IMAGE):
                mime = all_data.get(f"{field.field_id}__mime") if all_data else None
                if mime and mime not in c.allowed_mime_types:
                    errors.append(f"{label} must be one of: {', '.join(c.allowed_mime_types)}")

        # Built-in type validation
        type_errors = self._validate_by_type(coerced, field, label)
        errors.extend(type_errors)

        # SELECT/MULTI_SELECT option validation
        if field.options and field.field_type == FieldType.SELECT:
            allowed = {opt.value for opt in field.options}
            if str(coerced) not in allowed:
                errors.append(f"{label} must be one of: {', '.join(allowed)}")
        elif field.options and field.field_type == FieldType.MULTI_SELECT:
            allowed = {opt.value for opt in field.options}
            selected = coerced if isinstance(coerced, list) else [str(coerced)]
            invalid = [v for v in selected if v not in allowed]
            if invalid:
                errors.append(f"{label} contains invalid choices: {', '.join(invalid)}")

        # Cross-field validation via meta
        if field.meta and all_data:
            cross_errors = await self._run_cross_field_validation(
                field, coerced, all_data, label, locale
            )
            errors.extend(cross_errors)

        # Async remote validation via meta
        if field.meta and "async_validator" in field.meta:
            remote_errors = await self._run_async_validator(
                field, coerced, all_data, label, locale
            )
            errors.extend(remote_errors)

        return errors

    def _coerce_value(self, value: Any, field: FormField) -> Any:
        """Coerce a value to the appropriate Python type for the field.

        Args:
            value: Raw submitted value.
            field: FormField definition.

        Returns:
            Coerced value.

        Raises:
            ValueError: If the value cannot be coerced.
        """
        if value is None:
            return None

        ft = field.field_type

        if ft in (
            FieldType.TEXT,
            FieldType.TEXT_AREA,
            FieldType.EMAIL,
            FieldType.URL,
            FieldType.PHONE,
            FieldType.PASSWORD,
            FieldType.COLOR,
            FieldType.HIDDEN,
            FieldType.SELECT,
        ):
            return str(value).strip()

        elif ft in (FieldType.NUMBER, FieldType.INTEGER):
            if isinstance(value, (int, float)):
                return int(value) if ft == FieldType.INTEGER else value
            try:
                s = str(value).strip()
                return int(s) if ft == FieldType.INTEGER else float(s)
            except (ValueError, TypeError):
                raise ValueError(f"'{value}' is not a valid number")

        elif ft == FieldType.BOOLEAN:
            if isinstance(value, bool):
                return value
            return str(value).lower() in ("true", "1", "yes", "on")

        elif ft in (FieldType.DATE, FieldType.DATETIME, FieldType.TIME):
            return str(value).strip()

        elif ft == FieldType.MULTI_SELECT:
            if isinstance(value, list):
                return [str(v).strip() for v in value]
            elif isinstance(value, str):
                return [v.strip() for v in value.split(",") if v.strip()]
            return [str(value)]

        elif ft == FieldType.ARRAY:
            if isinstance(value, list):
                return value
            return [value]

        return value

    def _validate_by_type(
        self,
        value: Any,
        field: FormField,
        label: str,
    ) -> list[str]:
        """Apply built-in type-specific validation rules.

        Args:
            value: Coerced value.
            field: FormField definition.
            label: Resolved field label for error messages.

        Returns:
            List of error messages.
        """
        errors: list[str] = []
        ft = field.field_type

        if ft == FieldType.EMAIL and isinstance(value, str):
            if not EMAIL_PATTERN.match(value):
                errors.append(f"{label} must be a valid email address")

        elif ft == FieldType.URL and isinstance(value, str):
            if not URL_PATTERN.match(value):
                errors.append(f"{label} must be a valid URL")

        elif ft == FieldType.PHONE and isinstance(value, str):
            if not PHONE_PATTERN.match(value):
                errors.append(f"{label} must be a valid phone number")

        return errors

    async def _run_cross_field_validation(
        self,
        field: FormField,
        value: Any,
        all_data: dict[str, Any],
        label: str,
        locale: str,
    ) -> list[str]:
        """Run cross-field validation defined in field.meta['cross_field_validators'].

        Each validator is a callable(value, all_data) -> str | None.
        Returns error message on failure, None on success.

        Args:
            field: FormField definition.
            value: Coerced field value.
            all_data: Full submission data.
            label: Resolved label for error messages.
            locale: Locale for messages.

        Returns:
            List of error messages.
        """
        errors: list[str] = []
        validators: list[Callable] = field.meta.get("cross_field_validators", [])
        for validator_fn in validators:
            try:
                import asyncio
                if asyncio.iscoroutinefunction(validator_fn):
                    result = await validator_fn(value, all_data)
                else:
                    result = validator_fn(value, all_data)
                if result:
                    errors.append(result)
            except Exception as exc:
                self.logger.warning("Cross-field validator error for %s: %s", field.field_id, exc)
                errors.append(f"{label} validation failed: {exc}")
        return errors

    async def _run_async_validator(
        self,
        field: FormField,
        value: Any,
        all_data: dict[str, Any] | None,
        label: str,
        locale: str,
    ) -> list[str]:
        """Run async remote validator defined in field.meta['async_validator'].

        The validator is a callable(value) -> str | None.

        Args:
            field: FormField definition.
            value: Coerced field value.
            all_data: Full submission data (for context).
            label: Resolved label for error messages.
            locale: Locale for messages.

        Returns:
            List of error messages.
        """
        errors: list[str] = []
        validator_fn = field.meta.get("async_validator")
        if validator_fn is None:
            return errors
        try:
            import asyncio
            if asyncio.iscoroutinefunction(validator_fn):
                result = await validator_fn(value)
            else:
                result = validator_fn(value)
            if result:
                errors.append(result)
        except Exception as exc:
            self.logger.warning("Async validator error for %s: %s", field.field_id, exc)
            errors.append(f"{label} remote validation failed: {exc}")
        return errors

    def _collect_fields(self, section: FormSection) -> list[FormField]:
        """Recursively collect all fields from a section, including children.

        Args:
            section: FormSection to traverse.

        Returns:
            Flat list of all FormField instances.
        """
        fields: list[FormField] = []
        for field in section.fields:
            fields.append(field)
            fields.extend(self._collect_nested_fields(field))
        return fields

    def _collect_nested_fields(self, field: FormField) -> list[FormField]:
        """Recursively collect child fields of a GROUP or ARRAY field.

        Args:
            field: FormField to traverse.

        Returns:
            Flat list of nested FormField instances.
        """
        nested: list[FormField] = []
        if field.children:
            for child in field.children:
                nested.append(child)
                nested.extend(self._collect_nested_fields(child))
        return nested

    def check_schema(self, form: FormSchema) -> list[str]:
        """Check a form schema for structural issues without submitted data.

        Currently detects circular dependency references in ``depends_on`` rules.
        This is the public API for structural validation; callers should prefer
        this method over ``_detect_circular_dependencies``.

        Args:
            form: FormSchema to analyze.

        Returns:
            List of human-readable error strings (empty if no issues found).
        """
        return self._detect_circular_dependencies(form)

    def _detect_circular_dependencies(self, form: FormSchema) -> list[str]:
        """Detect circular dependency references in FormField.depends_on rules.

        Builds a directed graph where an edge A -> B means field A depends on
        field B (i.e., A.depends_on references B). Uses DFS cycle detection.

        Args:
            form: FormSchema to analyze.

        Returns:
            List of error messages describing detected cycles.
        """
        # Build field map and dependency graph
        all_fields: list[FormField] = []
        for section in form.sections:
            all_fields.extend(self._collect_fields(section))

        # Build adjacency list: field_id -> set of referenced field_ids
        graph: dict[str, set[str]] = {f.field_id: set() for f in all_fields}
        for field in all_fields:
            if field.depends_on:
                for condition in field.depends_on.conditions:
                    if condition.field_id in graph:
                        graph[field.field_id].add(condition.field_id)

        # DFS cycle detection
        UNVISITED, VISITING, VISITED = 0, 1, 2
        state: dict[str, int] = {fid: UNVISITED for fid in graph}
        cycles: list[str] = []

        def dfs(node: str, path: list[str]) -> None:
            state[node] = VISITING
            path.append(node)
            for neighbor in graph.get(node, set()):
                if state.get(neighbor) == VISITING:
                    # Found a cycle
                    cycle_start = path.index(neighbor)
                    cycle = path[cycle_start:] + [neighbor]
                    cycles.append(
                        f"Circular dependency detected: {' -> '.join(cycle)}"
                    )
                elif state.get(neighbor) == UNVISITED:
                    dfs(neighbor, path)
            path.pop()
            state[node] = VISITED

        for field_id in list(graph.keys()):
            if state[field_id] == UNVISITED:
                dfs(field_id, [])

        return cycles
