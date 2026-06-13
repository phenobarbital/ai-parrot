"""Platform-agnostic form validation for FormSchema.

This module provides FormValidator and ValidationResult for validating
form submission data against FormSchema constraints. The validator is
async-native to support ASYNC_REMOTE and UNIQUE validation callbacks.

Migrated and enhanced from parrot/integrations/msteams/dialogs/validator.py.
"""

import logging
import re
from datetime import datetime
from typing import Any, Callable

from pydantic import BaseModel

from ..core.constraints import ConditionOperator, DependencyOperation
from ..core.schema import FormField, FormSchema, FormSection
from ..core.types import FieldType, LocalizedString
from .auth_context import AuthContext
from .remote_response_resolver import RemoteResponseResolver, RemoteResponseSpec

logger = logging.getLogger(__name__)

# pycountry guard — only used for LOCATION validation
try:
    import pycountry as _pycountry
    _HAS_PYCOUNTRY = True
except ImportError:
    _pycountry = None  # type: ignore[assignment]
    _HAS_PYCOUNTRY = False


def _validate_location(value: str) -> bool:
    """Check if value is a valid ISO 3166 alpha-2 country code.

    Args:
        value: Country code string to validate.

    Returns:
        True if valid or pycountry is not installed.
    """
    if not _HAS_PYCOUNTRY:
        return True  # skip validation when pycountry not available
    return _pycountry.countries.get(alpha_2=value.upper()) is not None

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
        auth_context: AuthContext | None = None,
    ) -> ValidationResult:
        """Validate all form submission data against the schema.

        Args:
            form: The FormSchema to validate against.
            data: Submitted form data keyed by field_id.
            locale: Locale for error message resolution.
            auth_context: Optional runtime auth context for REMOTE_RESPONSE fields.

        Returns:
            ValidationResult with field-level errors and sanitized data.
        """
        errors: dict[str, list[str]] = {}
        sanitized: dict[str, Any] = {}

        # Detect circular dependencies first (includes post_depends and operation edges)
        circular_errors = self._detect_circular_dependencies(form)
        if circular_errors:
            errors["__circular__"] = circular_errors
            return ValidationResult(is_valid=False, errors=errors, sanitized_data=sanitized)

        # Rule-integrity pass: validate references, ordering, and operator/type compatibility
        rule_errors = self.validate_rules(form)
        if rule_errors:
            errors["__rules__"] = rule_errors
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
                auth_context=auth_context,
            )
            if field_errors:
                errors[field.field_id] = field_errors
            else:
                # For REMOTE_RESPONSE, use the resolved value stored by the validator
                if field.field_type == FieldType.REMOTE_RESPONSE:
                    resolved = getattr(field, "_resolved_remote_value", None)
                    if resolved is not None:
                        sanitized[field.field_id] = resolved
                elif field.field_type == FieldType.REST:
                    # REST field: the validator mutates the dict in-place (strips status).
                    # Use the submitted dict directly (already coerced by _validate_rest_field).
                    submitted = data.get(field.field_id)
                    if submitted is not None:
                        sanitized[field.field_id] = submitted
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
        auth_context: AuthContext | None = None,
    ) -> list[str]:
        """Validate a single field value against its constraints.

        Args:
            field: The FormField definition.
            value: The submitted value.
            all_data: Full submission data for cross-field validation.
            locale: Locale for error message resolution.
            auth_context: Optional runtime auth context for REMOTE_RESPONSE fields.

        Returns:
            List of error messages (empty list if valid).
        """
        errors: list[str] = []

        # Resolve label for error messages
        label = _resolve_localized(field.label, locale) or field.field_id

        # REMOTE_RESPONSE: resolve via external API before standard validation
        if field.field_type == FieldType.REMOTE_RESPONSE:
            return await self._validate_remote_response(
                field, value, label, auth_context=auth_context
            )

        # REST: validate the submitted {answer, blob_ref, status?} shape
        if field.field_type == FieldType.REST:
            return self._validate_rest_field(field, value, label)

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

        # Phase 2 — new field types (FEAT-167)
        elif ft == FieldType.DYNAMIC_SELECT:
            return str(value).strip()

        elif ft == FieldType.TRANSFER_LIST:
            if isinstance(value, list):
                return [str(v).strip() for v in value]
            elif isinstance(value, str):
                return [v.strip() for v in value.split(",") if v.strip()]
            return [str(value)]

        elif ft == FieldType.TAGS:
            if isinstance(value, list):
                return [str(v).strip() for v in value if str(v).strip()]
            elif isinstance(value, str):
                return [v.strip() for v in value.split(",") if v.strip()]
            return [str(value)]

        elif ft in (FieldType.NPS, FieldType.LIKERT, FieldType.RANKING):
            if isinstance(value, int):
                return value
            try:
                return int(str(value).strip())
            except (ValueError, TypeError):
                raise ValueError(f"'{value}' is not a valid integer")

        elif ft == FieldType.LOCATION:
            return str(value).strip().upper()

        elif ft == FieldType.SIGNATURE:
            if isinstance(value, dict):
                return value
            raise ValueError("Signature must be a dict with 'svg' and 'png' keys")

        elif ft == FieldType.AVAILABILITY:
            if isinstance(value, list):
                return value
            raise ValueError("Availability must be a list of slot dicts")

        # Phase 3 — FEAT-170
        elif ft == FieldType.REST:
            if isinstance(value, dict):
                return value
            raise ValueError("REST field value must be a dict with 'answer' and 'blob_ref' keys")

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

        # Phase 2 — new field types (FEAT-167)
        elif ft == FieldType.SIGNATURE:
            if not isinstance(value, dict):
                errors.append(f"{label} must be a dict with 'svg' and 'png' keys")
            else:
                if "svg" not in value or "png" not in value:
                    errors.append(f"{label} must contain 'svg' and 'png' keys")

        elif ft == FieldType.DYNAMIC_SELECT:
            # Same validation as SELECT — option values checked upstream
            pass

        elif ft == FieldType.TRANSFER_LIST:
            # Same validation as MULTI_SELECT — option values checked upstream
            if not isinstance(value, list):
                errors.append(f"{label} must be a list of strings")

        elif ft == FieldType.AVAILABILITY:
            if not isinstance(value, list):
                errors.append(f"{label} must be a list of availability slots")
            else:
                allow_overlap = (field.meta or {}).get("allow_overlap", False)
                slots = []
                for i, slot in enumerate(value):
                    if not isinstance(slot, dict) or "start" not in slot or "end" not in slot:
                        errors.append(f"{label} slot {i} must have 'start' and 'end' keys")
                        continue
                    try:
                        start = datetime.fromisoformat(str(slot["start"])) if isinstance(slot["start"], str) else slot["start"]
                        end = datetime.fromisoformat(str(slot["end"])) if isinstance(slot["end"], str) else slot["end"]
                        if end <= start:
                            errors.append(f"{label} slot {i}: 'end' must be after 'start'")
                        slots.append((start, end))
                    except (ValueError, TypeError):
                        errors.append(f"{label} slot {i} has invalid datetime format")
                if not allow_overlap and len(slots) > 1:
                    sorted_slots = sorted(slots, key=lambda s: s[0])
                    for j in range(len(sorted_slots) - 1):
                        if sorted_slots[j][1] > sorted_slots[j + 1][0]:
                            errors.append(f"{label} contains overlapping availability slots")
                            break

        elif ft == FieldType.LOCATION:
            if not isinstance(value, str) or len(value) != 2:
                errors.append(f"{label} must be a 2-character ISO 3166 country code")
            elif not _validate_location(value):
                errors.append(f"{label} '{value}' is not a valid ISO 3166 country code")

        elif ft == FieldType.TAGS:
            if not isinstance(value, list):
                errors.append(f"{label} must be a list of strings")

        elif ft == FieldType.NPS:
            if isinstance(value, int):
                c = field.constraints
                scale_min = c.scale_min if c and c.scale_min is not None else 0
                scale_max = c.scale_max if c and c.scale_max is not None else 10
                if not (scale_min <= value <= scale_max):
                    errors.append(f"{label} must be between {scale_min} and {scale_max}")

        elif ft == FieldType.LIKERT:
            if isinstance(value, int):
                c = field.constraints
                if c and c.scale_min is not None and c.scale_max is not None:
                    if not (c.scale_min <= value <= c.scale_max):
                        errors.append(f"{label} must be between {c.scale_min} and {c.scale_max}")
                else:
                    errors.append(f"{label} requires scale_min and scale_max constraints")

        elif ft == FieldType.RANKING:
            if isinstance(value, int):
                c = field.constraints
                scale_max = c.scale_max if c and c.scale_max is not None else 5
                scale_min = c.scale_min if c and c.scale_min is not None else 0
                if not (scale_min <= value <= scale_max):
                    errors.append(f"{label} must be between {scale_min} and {scale_max}")

        return errors

    async def _validate_remote_response(
        self,
        field: FormField,
        value: Any,
        label: str,
        *,
        auth_context: AuthContext | None = None,
    ) -> list[str]:
        """Validate a REMOTE_RESPONSE field by calling the configured external API.

        Parses ``RemoteResponseSpec`` from ``field.meta``, calls
        ``RemoteResponseResolver.resolve()``, and stores the resolved value.
        If ``response_schema`` is set in the spec, the resolved value is checked
        against the required top-level keys (informational — 2xx always succeeds).

        Args:
            field: FormField of type REMOTE_RESPONSE.
            value: Submitted content sent as the API request body.
            label: Resolved label for error messages.
            auth_context: Optional runtime auth context for header injection.

        Returns:
            List of error strings (empty means valid and resolved value stored).
        """
        errors: list[str] = []
        meta = field.meta or {}

        # Extract only known RemoteResponseSpec fields from meta to avoid
        # extra keys that are not part of the spec.
        spec_fields = {
            "endpoint", "http_method", "content_field", "prompt",
            "auth_ref", "timeout_seconds", "response_schema",
        }
        spec_kwargs = {k: v for k, v in meta.items() if k in spec_fields}

        if not spec_kwargs.get("endpoint"):
            errors.append(f"{label}: REMOTE_RESPONSE field must have 'endpoint' in meta")
            return errors

        try:
            spec = RemoteResponseSpec(**spec_kwargs)
        except Exception as exc:
            errors.append(f"{label}: invalid REMOTE_RESPONSE spec in meta: {exc}")
            return errors

        resolver = RemoteResponseResolver()
        result = await resolver.resolve(spec, value, auth_context=auth_context)

        if not result.success:
            errors.append(
                f"{label}: remote response failed"
                + (f": {result.error}" if result.error else "")
            )
            return errors

        # Optional response_schema key presence check (informational only)
        if spec.response_schema and result.value is not None:
            required_keys = spec.response_schema.get("required", [])
            if required_keys and isinstance(result.value, dict):
                missing = [k for k in required_keys if k not in result.value]
                if missing:
                    self.logger.warning(
                        "REMOTE_RESPONSE field '%s': response missing required schema keys: %s",
                        field.field_id,
                        missing,
                    )

        # Store the resolved value back into the field for downstream use
        # (sanitized_data is populated by the caller)
        field._resolved_remote_value = result.value  # type: ignore[attr-defined]

        return errors

    def _validate_rest_field(
        self,
        field: FormField,
        value: Any,
        label: str,
    ) -> list[str]:
        """Validate a REST field submission at form-submit time.

        Enforces the shape ``{answer, blob_ref, status?}``:
        - Rejects non-dict values.
        - Rejects ``status == "in_progress"`` with a structured error.
        - Rejects ``answer is None`` when ``field.required``.
        - Strips ``status`` from the accepted value (callers use the mutated dict).

        Also parses ``field.meta["rest"]`` via ``RestFieldSpec.model_validate``
        so design-time configuration errors surface early.

        Args:
            field: FormField of type REST.
            value: Submitted value (should be a dict).
            label: Resolved field label for error messages.

        Returns:
            List of error strings (empty means valid).
        """
        from pydantic import TypeAdapter

        from parrot_formdesigner.services.rest_field_resolver import RestFieldSpec

        errors: list[str] = []

        # Design-time: parse RestFieldSpec from meta to catch config errors
        meta = field.meta or {}
        rest_meta = meta.get("rest")
        if rest_meta is not None:
            try:
                TypeAdapter(RestFieldSpec).validate_python(rest_meta)
            except Exception as exc:
                errors.append(f"{label}: invalid REST spec in meta['rest']: {exc}")
                return errors

        # Shape check
        if not isinstance(value, dict):
            errors.append(
                f"{label}: REST field value must be a dict with "
                "'answer' and 'blob_ref' keys"
            )
            return errors

        # Reject in-flight uploads
        if value.get("status") == "in_progress":
            errors.append(
                f"field_id={field.field_id} status=in_progress: "
                "cannot submit a field that is still uploading"
            )
            return errors

        # Required check
        if field.required and value.get("answer") is None:
            errors.append(f"{label} is required (answer must not be null)")
            return errors

        # Strip status from the accepted shape so it is not persisted
        value.pop("status", None)

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

        Flattens through subsections and nested GROUP/ARRAY children.

        Args:
            section: FormSection to traverse.

        Returns:
            Flat list of all FormField instances.
        """
        fields: list[FormField] = []
        for field in section.iter_fields():
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

    # ------------------------------------------------------------------
    # Rule-integrity pass (FEAT-234)
    # ------------------------------------------------------------------

    # Field types that support numeric comparison operators and arithmetic ops
    _NUMERIC_FIELD_TYPES: frozenset[FieldType] = frozenset(
        {FieldType.NUMBER, FieldType.INTEGER}
    )
    # Operators that require numeric field types
    _NUMERIC_OPERATORS: frozenset[ConditionOperator] = frozenset(
        {
            ConditionOperator.GT,
            ConditionOperator.LT,
            ConditionOperator.GTE,
            ConditionOperator.LTE,
        }
    )
    # Operation kinds that require numeric operands
    _ARITHMETIC_OPS: frozenset[str] = frozenset(
        {"add", "subtract", "multiply", "divide", "percent"}
    )

    def validate_rules(self, form: FormSchema) -> list[str]:
        """Validate rule integrity for all fields in the form.

        Checks:
        - Every ``field_id`` referenced in ``depends_on.conditions``,
          ``post_depends.conditions``, operation ``operands``, and
          ``post_depends.target`` / operation ``target`` resolves to a real
          field in the form.
        - **Ordering**: ``depends_on`` conditions may only reference fields
          declared *earlier*; ``post_depends.target`` (and set/calc operation
          targets) may only reference fields declared *later*.
        - **Operator/type compatibility** (best-effort): numeric operators
          (``gt/lt/gte/lte``) and arithmetic operations must reference numeric
          field types; unknown field types pass silently.

        Args:
            form: FormSchema to validate.

        Returns:
            List of human-readable error strings (empty when all rules pass).
        """
        errors: list[str] = []

        # Build ordered field list and a fast-lookup dict
        all_fields: list[FormField] = []
        for section in form.sections:
            all_fields.extend(self._collect_fields(section))

        field_map: dict[str, FormField] = {f.field_id: f for f in all_fields}
        field_order: dict[str, int] = {f.field_id: i for i, f in enumerate(all_fields)}

        for field in all_fields:
            fid = field.field_id
            pos = field_order[fid]

            # --- pre-dependency checks ---
            if field.depends_on:
                rule = field.depends_on
                for cond in rule.conditions:
                    ref = cond.field_id
                    if ref not in field_map:
                        errors.append(
                            f"Field '{fid}': depends_on condition references unknown"
                            f" field_id '{ref}'"
                        )
                        continue

                    # Ordering: depends_on must reference earlier fields
                    if field_order.get(ref, -1) >= pos:
                        errors.append(
                            f"Field '{fid}': depends_on condition references field"
                            f" '{ref}' which is declared at the same position or later"
                            f" (pre-dependency must reference earlier fields)"
                        )

                    # Operator/type compatibility
                    ref_field = field_map[ref]
                    if (
                        cond.operator in self._NUMERIC_OPERATORS
                        and ref_field.field_type not in self._NUMERIC_FIELD_TYPES
                    ):
                        errors.append(
                            f"Field '{fid}': depends_on uses numeric operator"
                            f" '{cond.operator.value}' on non-numeric field '{ref}'"
                            f" (type={ref_field.field_type.value!r})"
                        )

                # Operations on the rule
                for op in rule.operations or []:
                    errors.extend(
                        self._validate_operation(op, fid, field_map, field_order, pos)
                    )

            # --- post-dependency checks ---
            for post in field.post_depends or []:
                target = post.target
                if target not in field_map:
                    errors.append(
                        f"Field '{fid}': post_depends targets unknown field_id '{target}'"
                    )
                else:
                    # Ordering: post_depends.target must be declared later
                    if field_order[target] <= pos:
                        errors.append(
                            f"Field '{fid}': post_depends targets field '{target}'"
                            f" which is declared at the same position or earlier"
                            f" (post-dependency must target a later field)"
                        )

                # Conditions on the post-dependency
                for cond in post.conditions or []:
                    ref = cond.field_id
                    if ref not in field_map:
                        errors.append(
                            f"Field '{fid}': post_depends condition references unknown"
                            f" field_id '{ref}'"
                        )
                        continue
                    ref_field = field_map[ref]
                    if (
                        cond.operator in self._NUMERIC_OPERATORS
                        and ref_field.field_type not in self._NUMERIC_FIELD_TYPES
                    ):
                        errors.append(
                            f"Field '{fid}': post_depends condition uses numeric operator"
                            f" '{cond.operator.value}' on non-numeric field '{ref}'"
                            f" (type={ref_field.field_type.value!r})"
                        )

                # Operation on the post-dependency
                if post.operation:
                    errors.extend(
                        self._validate_operation(
                            post.operation, fid, field_map, field_order, pos
                        )
                    )

        return errors

    def _validate_operation(
        self,
        op: DependencyOperation,
        owner_fid: str,
        field_map: dict[str, FormField],
        field_order: dict[str, int],
        owner_pos: int,
    ) -> list[str]:
        """Validate a single DependencyOperation for reference existence and type compatibility.

        Args:
            op: The operation to validate.
            owner_fid: The field_id of the field that owns this operation.
            field_map: Mapping of all field_ids to FormField objects.
            field_order: Mapping of field_id to 0-based declaration order.
            owner_pos: Declaration order of the owning field.

        Returns:
            List of error strings (empty when valid).
        """
        errors: list[str] = []

        # Check operands reference known fields
        for ref in op.operands:
            if ref not in field_map:
                errors.append(
                    f"Field '{owner_fid}': operation '{op.op}' references unknown"
                    f" operand field_id '{ref}'"
                )
                continue
            # Arithmetic ops: operands must be numeric
            if op.op in self._ARITHMETIC_OPS:
                ref_field = field_map[ref]
                if ref_field.field_type not in self._NUMERIC_FIELD_TYPES:
                    errors.append(
                        f"Field '{owner_fid}': arithmetic operation '{op.op}'"
                        f" references non-numeric operand field '{ref}'"
                        f" (type={ref_field.field_type.value!r})"
                    )

        # Check target references a known field
        if op.target not in field_map:
            errors.append(
                f"Field '{owner_fid}': operation '{op.op}' targets unknown"
                f" field_id '{op.target}'"
            )

        return errors

    def check_schema(self, form: FormSchema) -> list[str]:
        """Check a form schema for structural issues without submitted data.

        Detects circular dependency references (including ``post_depends`` and
        operation edges) and validates rule integrity (references, ordering,
        type compatibility).

        Args:
            form: FormSchema to analyze.

        Returns:
            List of human-readable error strings (empty if no issues found).
        """
        return self._detect_circular_dependencies(form) + self.validate_rules(form)

    def _detect_circular_dependencies(self, form: FormSchema) -> list[str]:
        """Detect circular dependency references across depends_on, post_depends, and operations.

        Builds a directed graph where an edge A -> B means field A has a
        dependency on field B.  Edge sources:

        - ``A.depends_on.conditions``: A depends on condition field B.
        - ``A.post_depends[*].target``: A has a forward effect on target B
          (edge: A -> B, for forward-cycle detection).
        - ``A.depends_on.operations[*].operands``: A's operation reads from B.
        - ``A.post_depends[*].operation.operands``: same for post-dep operations.

        Uses DFS cycle detection.

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
        known: set[str] = set(graph.keys())

        for field in all_fields:
            fid = field.field_id

            # Pre-dependency conditions: A -> condition.field_id
            if field.depends_on:
                for condition in field.depends_on.conditions:
                    if condition.field_id in known:
                        graph[fid].add(condition.field_id)
                # Pre-dep operations: A -> operand (and target -> A)
                for op in field.depends_on.operations or []:
                    for operand in op.operands:
                        if operand in known:
                            graph[fid].add(operand)
                    if op.target in known:
                        # target receives from A's operation: target -> A (reverse edge)
                        graph[op.target].add(fid)

            # Post-dependency: A -> target (forward effect)
            for post in field.post_depends or []:
                if post.target in known:
                    graph[fid].add(post.target)
                # Post-dep operation operands: A -> operand
                if post.operation:
                    for operand in post.operation.operands:
                        if operand in known:
                            graph[fid].add(operand)

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
