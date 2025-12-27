"""
Form Validator for MS Teams Dialogs.

Validates:
- Form data against FormDefinition rules
- Adaptive Card JSON structure
"""
from typing import Dict, List, Any, Optional, Union
from dataclasses import dataclass, field
import re
from ...dialogs.models import (
    FormDefinition,
    FormSection,
    FormField,
    FieldType,
    ValidationRule,
    FieldValidation,
)


@dataclass
class ValidationResult:
    """Result of form validation."""
    is_valid: bool
    errors: Dict[str, str] = field(default_factory=dict)  # field_name -> error_message
    error_list: List[str] = field(default_factory=list)   # flat list for display
    sanitized_data: Dict[str, Any] = field(default_factory=dict)

    def add_error(self, field_name: str, message: str):
        """Add a validation error."""
        self.is_valid = False
        self.errors[field_name] = message
        self.error_list.append(f"{field_name}: {message}")


class FormValidator:
    """
    Validates form submissions against FormDefinition rules.

    Features:
    - Required field validation
    - Type coercion and validation
    - Pattern matching (regex)
    - Min/max value/length checks
    - Custom validation rules
    - Data sanitization
    """

    # Email regex pattern
    EMAIL_PATTERN = r'^[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}$'
    # URL regex pattern
    URL_PATTERN = r'^https?://[^\s/$.?#].[^\s]*$'

    def validate_form_data(
        self,
        data: Dict[str, Any],
        form: FormDefinition,
    ) -> ValidationResult:
        """
        Validate all form data against the form definition.

        Args:
            data: Submitted form data
            form: Form definition with validation rules

        Returns:
            ValidationResult with errors and sanitized data
        """
        result = ValidationResult(is_valid=True, sanitized_data={})

        for section in form.sections:
            section_result = self.validate_section(data, section)

            if not section_result.is_valid:
                result.is_valid = False
                result.errors.update(section_result.errors)
                result.error_list.extend(section_result.error_list)

            result.sanitized_data.update(section_result.sanitized_data)

        return result

    def validate_section(
        self,
        data: Dict[str, Any],
        section: FormSection,
    ) -> ValidationResult:
        """Validate data for a single section."""
        result = ValidationResult(is_valid=True, sanitized_data={})

        for field_def in section.fields:
            field_result = self.validate_field(data, field_def)

            if not field_result.is_valid:
                result.is_valid = False
                result.errors.update(field_result.errors)
                result.error_list.extend(field_result.error_list)

            if field_def.name in field_result.sanitized_data:
                result.sanitized_data[field_def.name] = field_result.sanitized_data[field_def.name]

        return result

    def validate_field(
        self,
        data: Dict[str, Any],
        field_def: FormField,
    ) -> ValidationResult:
        """Validate a single field."""
        result = ValidationResult(is_valid=True, sanitized_data={})

        value = data.get(field_def.name)
        field_name = field_def.label or field_def.name

        # Required check
        if field_def.required:
            if value is None or value == "" or (isinstance(value, str) and not value.strip()):
                result.add_error(field_def.name, f"{field_name} is required")
                return result
        elif value is None or value == "":
            # Not required and empty, skip further validation
            return result

        # Type coercion and validation
        try:
            coerced_value = self._coerce_value(value, field_def)
            result.sanitized_data[field_def.name] = coerced_value
        except ValueError as e:
            result.add_error(field_def.name, str(e))
            return result

        # Apply validation rules
        for validation in field_def.validations:
            error = self._apply_validation_rule(
                coerced_value, validation, field_def
            )
            if error:
                result.add_error(field_def.name, error)

        # Built-in type validations
        type_error = self._validate_field_type(coerced_value, field_def)
        if type_error:
            result.add_error(field_def.name, type_error)

        return result

    def _coerce_value(
        self,
        value: Any,
        field_def: FormField,
    ) -> Any:
        """Coerce value to the appropriate type."""
        if value is None:
            return None

        field_type = field_def.field_type

        # String types
        if field_type in (FieldType.TEXT, FieldType.EMAIL, FieldType.URL, FieldType.TEXTAREA):
            return str(value).strip()

        # Number
        elif field_type == FieldType.NUMBER:
            if isinstance(value, (int, float)):
                return value
            try:
                # Try int first, then float
                str_val = str(value).strip()
                if '.' in str_val:
                    return float(str_val)
                return int(str_val)
            except ValueError:
                raise ValueError(f"'{value}' is not a valid number")

        # Boolean/Toggle
        elif field_type == FieldType.TOGGLE:
            if isinstance(value, bool):
                return value
            return str(value).lower() in ('true', '1', 'yes', 'on')

        # Date
        elif field_type in (FieldType.DATE, FieldType.DATETIME):
            # Keep as string for now, could parse to datetime
            return str(value).strip()

        # Choice
        elif field_type == FieldType.CHOICE:
            return str(value).strip()

        # Multi-choice
        elif field_type == FieldType.MULTICHOICE:
            if isinstance(value, list):
                return [str(v).strip() for v in value]
            elif isinstance(value, str):
                # Adaptive Cards returns comma-separated string
                return [v.strip() for v in value.split(',') if v.strip()]
            return [str(value)]

        return value

    def _apply_validation_rule(
        self,
        value: Any,
        validation: FieldValidation,
        field_def: FormField,
    ) -> Optional[str]:
        """Apply a single validation rule and return error message if failed."""
        rule = validation.rule
        rule_value = validation.value
        custom_message = validation.message
        field_name = field_def.label or field_def.name

        if rule == ValidationRule.REQUIRED:
            # Already handled above
            pass

        elif rule == ValidationRule.MIN_LENGTH:
            if isinstance(value, str) and len(value) < rule_value:
                return custom_message or f"{field_name} must be at least {rule_value} characters"

        elif rule == ValidationRule.MAX_LENGTH:
            if isinstance(value, str) and len(value) > rule_value:
                return custom_message or f"{field_name} must be at most {rule_value} characters"

        elif rule == ValidationRule.PATTERN:
            if isinstance(value, str) and not re.match(rule_value, value):
                return custom_message or f"{field_name} format is invalid"

        elif rule == ValidationRule.MIN_VALUE:
            if isinstance(value, (int, float)) and value < rule_value:
                return custom_message or f"{field_name} must be at least {rule_value}"

        elif rule == ValidationRule.MAX_VALUE:
            if isinstance(value, (int, float)) and value > rule_value:
                return custom_message or f"{field_name} must be at most {rule_value}"

        elif rule == ValidationRule.EMAIL:
            if not re.match(self.EMAIL_PATTERN, str(value)):
                return custom_message or f"{field_name} must be a valid email address"

        elif rule == ValidationRule.URL:
            if not re.match(self.URL_PATTERN, str(value)):
                return custom_message or f"{field_name} must be a valid URL"

        return None

    def _validate_field_type(
        self,
        value: Any,
        field_def: FormField,
    ) -> Optional[str]:
        """Validate value against field type."""
        field_type = field_def.field_type
        field_name = field_def.label or field_def.name

        if field_type == FieldType.EMAIL:
            if not re.match(self.EMAIL_PATTERN, str(value)):
                return f"{field_name} must be a valid email address"

        elif field_type == FieldType.URL:
            if not re.match(self.URL_PATTERN, str(value)):
                return f"{field_name} must be a valid URL"

        elif field_type == FieldType.CHOICE:
            # Validate choice is in allowed values
            if field_def.choices:
                allowed = self._extract_choice_values(field_def.choices)
                if value not in allowed:
                    return f"{field_name} must be one of: {', '.join(allowed)}"

        elif field_type == FieldType.MULTICHOICE:
            if field_def.choices:
                allowed = set(self._extract_choice_values(field_def.choices))
                selected = value if isinstance(value, list) else [value]
                invalid = [v for v in selected if v not in allowed]
                if invalid:
                    return f"{field_name} contains invalid choices: {', '.join(invalid)}"

        return None

    def _extract_choice_values(
        self,
        choices: List[Union[str, Dict[str, str]]],
    ) -> List[str]:
        """Extract value strings from choices list."""
        values = []
        for choice in choices:
            if isinstance(choice, str):
                values.append(choice)
            elif isinstance(choice, dict):
                values.append(choice.get("value", choice.get("title", "")))
        return values

    # =========================================================================
    # Adaptive Card Validation
    # =========================================================================

    def validate_adaptive_card(self, card: Dict[str, Any]) -> bool:
        """
        Validate that an Adaptive Card JSON is valid.

        Checks:
        - Required top-level keys
        - Valid type values
        - Body element structure
        - Action structure

        Args:
            card: Adaptive Card JSON dict

        Returns:
            True if valid, False otherwise
        """
        try:
            # Required keys
            if card.get("type") != "AdaptiveCard":
                return False

            if "version" not in card:
                return False

            if "body" not in card or not isinstance(card["body"], list):
                return False

            # Validate body elements
            for element in card["body"]:
                if not self._validate_card_element(element):
                    return False

            # Validate actions if present
            if "actions" in card:
                if not isinstance(card["actions"], list):
                    return False
                for action in card["actions"]:
                    if not self._validate_card_action(action):
                        return False

            return True

        except Exception:
            return False

    def _validate_card_element(self, element: Dict[str, Any]) -> bool:
        """Validate a single card body element."""
        if not isinstance(element, dict):
            return False

        elem_type = element.get("type")
        if not elem_type:
            return False

        valid_types = {
            "TextBlock", "Image", "Container", "ColumnSet", "Column",
            "FactSet", "ImageSet", "ActionSet",
            "Input.Text", "Input.Number", "Input.Date", "Input.Time",
            "Input.Toggle", "Input.ChoiceSet",
        }

        if elem_type not in valid_types:
            return False

        # Validate nested elements
        if elem_type == "Container":
            items = element.get("items", [])
            for item in items:
                if not self._validate_card_element(item):
                    return False

        elif elem_type == "ColumnSet":
            columns = element.get("columns", [])
            for col in columns:
                if col.get("type") != "Column":
                    return False
                for item in col.get("items", []):
                    if not self._validate_card_element(item):
                        return False

        # Validate Input elements have id
        if elem_type.startswith("Input.") and "id" not in element:
            return False

        # Validate ChoiceSet has choices
        if elem_type == "Input.ChoiceSet":
            choices = element.get("choices", [])
            if not choices:
                return False
            for choice in choices:
                if "title" not in choice or "value" not in choice:
                    return False

        return True

    def _validate_card_action(self, action: Dict[str, Any]) -> bool:
        """Validate a card action."""
        if not isinstance(action, dict):
            return False

        action_type = action.get("type")
        valid_types = {
            "Action.Submit", "Action.OpenUrl", "Action.ShowCard",
            "Action.ToggleVisibility", "Action.Execute",
        }

        if action_type not in valid_types:
            return False

        if action_type == "Action.OpenUrl":
            if "url" not in action:
                return False

        return True

    def sanitize_card(self, card: Dict[str, Any]) -> Dict[str, Any]:
        """
        Sanitize an Adaptive Card to fix common issues.

        Fixes:
        - Adds missing schema/version
        - Removes null values
        - Ensures unique input IDs
        - Fixes choice structures

        Args:
            card: Potentially malformed card

        Returns:
            Sanitized card
        """
        sanitized = dict(card)

        # Ensure required fields
        sanitized.setdefault("type", "AdaptiveCard")
        sanitized.setdefault("$schema", "http://adaptivecards.io/schemas/adaptive-card.json")
        sanitized.setdefault("version", "1.5")
        sanitized.setdefault("body", [])

        # Remove null values recursively
        sanitized = self._remove_nulls(sanitized)

        # Ensure unique IDs
        sanitized = self._ensure_unique_ids(sanitized)

        return sanitized

    def _remove_nulls(self, obj: Any) -> Any:
        """Recursively remove null values from dict/list."""
        if isinstance(obj, dict):
            return {
                k: self._remove_nulls(v)
                for k, v in obj.items()
                if v is not None
            }
        elif isinstance(obj, list):
            return [self._remove_nulls(v) for v in obj if v is not None]
        return obj

    def _ensure_unique_ids(self, card: Dict[str, Any]) -> Dict[str, Any]:
        """Ensure all input elements have unique IDs."""
        seen_ids = set()
        counter = {}

        def process_element(elem):
            if isinstance(elem, dict):
                if "id" in elem:
                    orig_id = elem["id"]
                    if orig_id in seen_ids:
                        # Generate unique ID
                        counter[orig_id] = counter.get(orig_id, 0) + 1
                        elem["id"] = f"{orig_id}_{counter[orig_id]}"
                    seen_ids.add(elem["id"])

                # Recurse into nested elements
                for key in ("items", "columns", "body"):
                    if key in elem and isinstance(elem[key], list):
                        for item in elem[key]:
                            process_element(item)

        for element in card.get("body", []):
            process_element(element)

        return card
