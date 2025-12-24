from dataclasses import dataclass, field
from typing import List, Optional, Dict, Any, Literal, Union
from pathlib import Path
from enum import Enum
from datetime import datetime, timezone
import hashlib

# Use yaml_rs (Rust) for faster parsing with PyYAML fallback
try:
    from parrot.yaml_rs import loads as yaml_loads
    _YAML_RS_AVAILABLE = True
except ImportError:
    try:
        import yaml
        yaml_loads = yaml.safe_load
        _YAML_RS_AVAILABLE = False
    except ImportError:
        yaml_loads = None
        _YAML_RS_AVAILABLE = False

from ...tools.abstract import AbstractTool


class FieldType(str, Enum):
    """Supported form field types."""
    TEXT = "text"
    NUMBER = "number"
    DATE = "date"
    DATETIME = "datetime"
    CHOICE = "choice"
    MULTICHOICE = "multichoice"
    TOGGLE = "toggle"
    EMAIL = "email"
    URL = "url"
    TEXTAREA = "textarea"  # multiline text


class DialogPreset(str, Enum):
    """Pre-built dialog templates."""
    SIMPLE = "simple"           # Single Adaptive Card, all fields
    WIZARD = "wizard"           # Multi-step, one section per step
    WIZARD_WITH_SUMMARY = "wizard_summary"  # Wizard + final confirmation
    CONVERSATIONAL = "conversational"  # One field at a time via prompts


class ValidationRule(str, Enum):
    """Validation rules for form fields."""
    REQUIRED = "required"
    MIN_LENGTH = "min_length"
    MAX_LENGTH = "max_length"
    PATTERN = "pattern"
    MIN_VALUE = "min_value"
    MAX_VALUE = "max_value"
    EMAIL = "email"
    URL = "url"
    CUSTOM = "custom"  # LLM validation


@dataclass
class FieldValidation:
    """Validation rules for a field."""
    rule: ValidationRule
    value: Any = None
    message: Optional[str] = None  # Custom error message


@dataclass
class FormField:
    """Individual form field definition."""
    name: str
    field_type: FieldType
    label: Optional[str] = None
    description: Optional[str] = None
    placeholder: Optional[str] = None
    required: bool = True
    default: Optional[Any] = None
    choices: Optional[List[Union[str, Dict[str, str]]]] = None
    validations: List[FieldValidation] = field(default_factory=list)
    # For dynamic choices (e.g., from database)
    choices_source: Optional[str] = None  # Tool name to fetch choices
    # Conditional visibility
    visible_when: Optional[Dict[str, Any]] = None  # {"field": "role", "equals": "admin"}

    def __post_init__(self):
        if self.label is None:
            self.label = self.name.replace("_", " ").title()

        # Auto-add required validation if needed
        if self.required and not any(v.rule == ValidationRule.REQUIRED for v in self.validations):
            self.validations.insert(0, FieldValidation(ValidationRule.REQUIRED))

    @classmethod
    def from_pydantic_field(cls, name: str, field_info: Any, annotation: type) -> 'FormField':
        """Create FormField from Pydantic field info."""
        import typing
        from enum import Enum as PyEnum

        # Determine field type from annotation
        origin = typing.get_origin(annotation)
        args = typing.get_args(annotation)

        # Handle Optional
        is_optional = origin is Union and type(None) in args
        if is_optional:
            annotation = [a for a in args if a is not type(None)][0]
            origin = typing.get_origin(annotation)
            args = typing.get_args(annotation)

        # Map Python types to FieldType
        type_mapping = {
            str: FieldType.TEXT,
            int: FieldType.NUMBER,
            float: FieldType.NUMBER,
            bool: FieldType.TOGGLE,
        }

        field_type = FieldType.TEXT
        choices = None

        # Check for Literal (choices)
        if origin is Literal:
            field_type = FieldType.CHOICE
            choices = list(args)
        # Check for Enum
        elif isinstance(annotation, type) and issubclass(annotation, PyEnum):
            field_type = FieldType.CHOICE
            choices = [e.value for e in annotation]
        elif annotation in type_mapping:
            field_type = type_mapping[annotation]

        # Extract description and other metadata
        description = ""
        default = None

        if hasattr(field_info, 'description'):
            description = field_info.description or ""
        if hasattr(field_info, 'default') and field_info.default is not None:
            default = field_info.default

        return cls(
            name=name,
            field_type=field_type,
            label=field_info.title if hasattr(field_info, 'title') else None,
            description=description,
            required=not is_optional and default is None,
            default=default,
            choices=choices,
        )


@dataclass
class FormSection:
    """A section of the form (becomes a step in WaterfallDialog)."""
    name: str
    title: Optional[str] = None
    description: Optional[str] = None
    fields: List[FormField] = field(default_factory=list)
    # Section-level settings
    show_progress: bool = True  # Show "Step X of Y"
    allow_skip: bool = False

    def __post_init__(self):
        if self.title is None:
            self.title = self.name.replace("_", " ").title()


@dataclass
class FormDefinition:
    """Complete form definition."""
    form_id: str
    title: str
    sections: List[FormSection]

    # Dialog behavior
    preset: DialogPreset = DialogPreset.WIZARD

    # Actions
    submit_action: Optional[str] = None  # Tool name or callback identifier
    cancel_action: Optional[str] = None

    # Trigger phrases for auto-detection
    trigger_phrases: List[str] = field(default_factory=list)

    # LLM integration
    llm_validation: bool = False  # Use LLM to validate responses
    llm_summary: bool = False     # Generate summary before submit

    # Metadata
    version: str = "1.0"
    metadata: Dict[str, Any] = field(default_factory=dict)

    # Cache control
    _file_path: Optional[str] = field(default=None, repr=False)
    _file_hash: Optional[str] = field(default=None, repr=False)
    _loaded_at: Optional[datetime] = field(default=None, repr=False)

    def compute_hash(self) -> str:
        """Compute hash for cache invalidation."""
        content = f"{self.form_id}{self.version}{len(self.sections)}"
        for section in self.sections:
            content += f"{section.name}{len(section.fields)}"
        return hashlib.md5(content.encode()).hexdigest()

    @classmethod
    def from_yaml(cls, yaml_content: str, file_path: str = None) -> 'FormDefinition':
        """Parse YAML content into FormDefinition."""
        if yaml_loads is None:
            raise ImportError("No YAML parser available. Install yaml_rs or PyYAML.")
        data = yaml_loads(yaml_content)
        return cls._from_dict(data, file_path)

    @classmethod
    def from_yaml_file(cls, file_path: str) -> 'FormDefinition':
        """Load FormDefinition from YAML file."""
        path = Path(file_path)
        content = path.read_text(encoding='utf-8')
        return cls.from_yaml(content, str(path))

    @classmethod
    def _from_dict(cls, data: Dict[str, Any], file_path: str = None) -> 'FormDefinition':
        """Convert dictionary to FormDefinition."""
        sections = []

        for section_data in data.get('sections', []):
            fields = []

            for field_data in section_data.get('fields', []):
                # Handle both formats:
                # - { name: "field_name", type: "text", ... }
                # - { field_name: { type: "text", ... } }
                if isinstance(field_data, dict):
                    if 'name' in field_data:
                        field_name = field_data['name']
                        field_config = field_data
                    else:
                        field_name = list(field_data.keys())[0]
                        field_config = field_data[field_name]
                        if isinstance(field_config, str):
                            # Simple format: field_name: type
                            field_config = {'type': field_config}
                        field_config['name'] = field_name
                else:
                    continue

                # Parse validations
                validations = []
                if 'validation' in field_config:
                    val_config = field_config['validation']
                    if isinstance(val_config, dict):
                        # Check for separate 'message' key at validation level
                        default_message = val_config.get('message')
                        for rule_name, rule_value in val_config.items():
                            if rule_name == 'message':
                                continue  # Skip, this is just the message
                            try:
                                rule = ValidationRule(rule_name)
                                # Use default_message if rule_value isn't a dict with its own message
                                validations.append(FieldValidation(
                                    rule=rule, 
                                    value=rule_value,
                                    message=default_message,
                                ))
                            except ValueError:
                                pass  # Unknown validation rule

                # Parse choices
                choices = field_config.get('choices')
                if choices and isinstance(choices, list):
                    # Normalize choices to list of dicts or strings
                    normalized = []
                    for c in choices:
                        if isinstance(c, str):
                            normalized.append(c)
                        elif isinstance(c, dict):
                            normalized.append(c)
                    choices = normalized

                fields.append(FormField(
                    name=field_config.get('name', field_name),
                    field_type=FieldType(field_config.get('type', 'text')),
                    label=field_config.get('label'),
                    description=field_config.get('description'),
                    placeholder=field_config.get('placeholder'),
                    required=field_config.get('required', True),
                    default=field_config.get('default'),
                    choices=choices,
                    validations=validations,
                    choices_source=field_config.get('choices_source'),
                    visible_when=field_config.get('visible_when'),
                ))

            sections.append(FormSection(
                name=section_data.get('name', f'section_{len(sections)}'),
                title=section_data.get('title'),
                description=section_data.get('description'),
                fields=fields,
                show_progress=section_data.get('show_progress', True),
                allow_skip=section_data.get('allow_skip', False),
            ))

        form = cls(
            form_id=data.get('form_id', 'unnamed_form'),
            title=data.get('title', 'Form'),
            sections=sections,
            preset=DialogPreset(data.get('preset', 'wizard')),
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

    @classmethod
    def from_tool_schema(cls, tool: 'AbstractTool') -> 'FormDefinition':
        """Generate FormDefinition from a tool's args_schema."""
        if not hasattr(tool, 'args_schema') or tool.args_schema is None:
            raise ValueError(f"Tool {tool.name} has no args_schema")

        schema_class = tool.args_schema

        # Get Pydantic model fields
        if hasattr(schema_class, 'model_fields'):
            # Pydantic v2
            model_fields = schema_class.model_fields
            annotations = schema_class.__annotations__
        else:
            # Pydantic v1
            model_fields = schema_class.__fields__
            annotations = schema_class.__annotations__

        fields = []
        for name, field_info in model_fields.items():
            annotation = annotations.get(name, str)
            fields.append(FormField.from_pydantic_field(name, field_info, annotation))

        return cls(
            form_id=f"{tool.name}_form",
            title=f"Configure: {tool.name}",
            sections=[FormSection(
                name="parameters",
                title=tool.description or f"{tool.name} Parameters",
                fields=fields,
            )],
            preset=DialogPreset.SIMPLE if len(fields) <= 5 else DialogPreset.WIZARD,
            submit_action=tool.name,
        )
