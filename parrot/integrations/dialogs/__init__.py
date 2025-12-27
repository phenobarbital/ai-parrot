"""
Form Dialogs Module.

Provides shared form definition models and utilities for
MS Teams and Telegram dialog integrations.
"""
from .models import (
    FormDefinition,
    FormSection,
    FormField,
    FieldType,
    FieldValidation,
    ValidationRule,
    DialogPreset,
)
from .parser import (
    parse_yaml,
    parse_yaml_file,
    FormParserError,
    is_yaml_rs_available,
)
from .registry import (
    FormRegistry,
    get_registry,
    register_form,
    get_form,
)
from .cache import (
    FormDefinitionCache,
    CacheEntry,
)

__all__ = [
    # Models
    'FormDefinition',
    'FormSection',
    'FormField',
    'FieldType',
    'FieldValidation',
    'ValidationRule',
    'DialogPreset',
    # Parser
    'parse_yaml',
    'parse_yaml_file',
    'FormParserError',
    'is_yaml_rs_available',
    # Registry
    'FormRegistry',
    'get_registry',
    'register_form',
    'get_form',
    # Cache
    'FormDefinitionCache',
    'CacheEntry',
]
