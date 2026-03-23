"""
YAML Parser for Form Definitions.

Provides high-performance YAML parsing using yaml_rs (Rust) with PyYAML fallback.
Converts YAML content into FormDefinition objects for dialog generation.
"""
from pathlib import Path
from typing import Union, Optional, List, Any, Dict
from datetime import datetime, timezone

# Try yaml_rs first (Rust implementation, 5-20x faster)
try:
    from parrot.yaml_rs import loads as yaml_loads
    YAML_RS_AVAILABLE = True
except ImportError:
    try:
        import yaml
        yaml_loads = yaml.safe_load
        YAML_RS_AVAILABLE = False
    except ImportError:
        yaml_loads = None
        YAML_RS_AVAILABLE = False

from .models import (
    FormDefinition,
    FormSection,
    FormField,
    FieldType,
    FieldValidation,
    ValidationRule,
    DialogPreset,
)


class FormParserError(Exception):
    """Exception raised when form parsing fails."""

    def __init__(self, message: str, errors: List[str] = None):
        super().__init__(message)
        self.errors = errors or []


def _parse_validation(val_config: Dict[str, Any]) -> List[FieldValidation]:
    """Parse validation rules from config dictionary."""
    validations = []
    if not isinstance(val_config, dict):
        return validations

    for rule_name, rule_value in val_config.items():
        try:
            rule = ValidationRule(rule_name)
            validations.append(FieldValidation(rule=rule, value=rule_value))
        except ValueError:
            # Unknown validation rule - skip
            pass
    return validations


def _parse_choices(choices: Any) -> Optional[List[Union[str, Dict[str, str]]]]:
    """Parse and normalize choices from config."""
    if not choices or not isinstance(choices, list):
        return None

    normalized = []
    for choice in choices:
        if isinstance(choice, str):
            normalized.append(choice)
        elif isinstance(choice, dict):
            normalized.append(choice)
    return normalized if normalized else None


def _parse_field(field_data: Any) -> Optional[FormField]:
    """Parse a single field definition."""
    if not isinstance(field_data, dict):
        return None

    # Handle both formats:
    # - { name: "field_name", type: "text", ... }
    # - { field_name: { type: "text", ... } }
    if 'name' in field_data and isinstance(field_data.get('name'), str):
        # Explicit name field format: { name: "field_name", type: "text", ... }
        field_name = field_data['name']
        field_config = field_data
    else:
        # Shorthand format: { field_name: { type: "text", ... } }
        field_name = list(field_data.keys())[0]
        field_config = field_data[field_name]
        if isinstance(field_config, str):
            # Simple format: field_name: type
            field_config = {'type': field_config}
        elif field_config is None:
            field_config = {'type': 'text'}
        elif not isinstance(field_config, dict):
            field_config = {'type': 'text'}
        # Ensure name is set as string
        field_config['name'] = str(field_name)

    # Parse validations
    validations = []
    if 'validation' in field_config:
        validations = _parse_validation(field_config['validation'])

    # Parse choices
    choices = _parse_choices(field_config.get('choices'))

    # Determine field type
    field_type_str = field_config.get('type', 'text')
    try:
        field_type = FieldType(field_type_str)
    except ValueError:
        field_type = FieldType.TEXT

    return FormField(
        name=field_config.get('name', field_name),
        field_type=field_type,
        label=field_config.get('label'),
        description=field_config.get('description'),
        placeholder=field_config.get('placeholder'),
        required=field_config.get('required', True),
        default=field_config.get('default'),
        choices=choices,
        validations=validations,
        choices_source=field_config.get('choices_source'),
        visible_when=field_config.get('visible_when'),
    )


def _parse_section(section_data: Dict[str, Any], index: int) -> FormSection:
    """Parse a section definition."""
    fields = []
    for field_data in section_data.get('fields', []):
        field = _parse_field(field_data)
        if field:
            fields.append(field)

    return FormSection(
        name=section_data.get('name', f'section_{index}'),
        title=section_data.get('title'),
        description=section_data.get('description'),
        fields=fields,
        show_progress=section_data.get('show_progress', True),
        allow_skip=section_data.get('allow_skip', False),
    )


def _validate_yaml_data(data: Dict[str, Any]) -> List[str]:
    """Validate parsed YAML data and return list of errors."""
    errors = []

    if not isinstance(data, dict):
        errors.append("YAML content must be a dictionary")
        return errors

    if not data.get('form_id'):
        errors.append("Missing required field: 'form_id'")

    if not data.get('sections'):
        errors.append("Missing required field: 'sections'")
    elif not isinstance(data['sections'], list):
        errors.append("'sections' must be a list")
    elif len(data['sections']) == 0:
        errors.append("'sections' must contain at least one section")

    return errors


def parse_yaml(
    yaml_content: str,
    file_path: str = None,
    strict: bool = False
) -> FormDefinition:
    """
    Parse YAML content into a FormDefinition.

    Uses yaml_rs (Rust implementation) for 5-20x faster parsing,
    with automatic fallback to PyYAML if not available.

    Args:
        yaml_content: YAML string containing form definition
        file_path: Optional file path for error context and cache tracking
        strict: If True, raise on validation warnings (default: False)

    Returns:
        FormDefinition object

    Raises:
        FormParserError: If YAML parsing fails or validation errors occur

    Example:
        >>> yaml_str = '''
        ... form_id: my_form
        ... title: My Form
        ... sections:
        ...   - name: info
        ...     fields:
        ...       - name:
        ...           type: text
        ...           required: true
        ... '''
        >>> form = parse_yaml(yaml_str)
        >>> form.form_id
        'my_form'
    """
    if yaml_loads is None:
        raise FormParserError(
            "No YAML parser available. Install yaml_rs or PyYAML."
        )

    if not yaml_content or not yaml_content.strip():
        raise FormParserError("Empty YAML content provided")

    # Parse YAML
    try:
        data = yaml_loads(yaml_content)
    except Exception as e:
        raise FormParserError(f"YAML parsing failed: {e}") from e

    # Validate
    errors = _validate_yaml_data(data)
    if errors:
        raise FormParserError(
            f"Form validation failed: {', '.join(errors)}",
            errors=errors
        )

    # Parse sections
    sections = []
    for idx, section_data in enumerate(data.get('sections', [])):
        sections.append(_parse_section(section_data, idx))

    # Parse preset
    preset_str = data.get('preset', 'wizard')
    try:
        preset = DialogPreset(preset_str)
    except ValueError:
        preset = DialogPreset.WIZARD

    # Build FormDefinition
    form = FormDefinition(
        form_id=data.get('form_id', 'unnamed_form'),
        title=data.get('title', 'Form'),
        sections=sections,
        preset=preset,
        submit_action=data.get('submit_action'),
        cancel_action=data.get('cancel_action'),
        trigger_phrases=data.get('trigger_phrases', []),
        llm_validation=data.get('llm_validation', False),
        llm_summary=data.get('llm_summary', False),
        version=data.get('version', '1.0'),
        metadata=data.get('metadata', {}),
        _file_path=file_path,
        _loaded_at=datetime.now(timezone.utc),
    )
    form._file_hash = form.compute_hash()

    return form


def parse_yaml_file(file_path: Union[str, Path]) -> FormDefinition:
    """
    Load and parse a FormDefinition from a YAML file.

    Args:
        file_path: Path to the YAML file

    Returns:
        FormDefinition object

    Raises:
        FormParserError: If file reading or parsing fails
        FileNotFoundError: If file does not exist

    Example:
        >>> form = parse_yaml_file('/path/to/employee_onboarding.yaml')
        >>> form.form_id
        'employee_onboarding'
    """
    path = Path(file_path)

    if not path.exists():
        raise FileNotFoundError(f"Form file not found: {file_path}")

    if not path.is_file():
        raise FormParserError(f"Path is not a file: {file_path}")

    try:
        content = path.read_text(encoding='utf-8')
    except Exception as e:
        raise FormParserError(f"Failed to read file {file_path}: {e}") from e

    return parse_yaml(content, file_path=str(path))


def is_yaml_rs_available() -> bool:
    """Check if the fast yaml_rs parser is available."""
    return YAML_RS_AVAILABLE


__all__ = [
    'parse_yaml',
    'parse_yaml_file',
    'FormParserError',
    'is_yaml_rs_available',
]
