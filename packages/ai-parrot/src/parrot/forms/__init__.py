"""Universal Form Abstraction Layer for AI-Parrot.

This package provides a platform-agnostic form system with:
- Pydantic-based schema models (FormSchema, FormField, FormSection)
- Field constraints and conditional visibility rules
- Style/layout configuration (StyleSchema)
- Extractors to create FormSchema from Pydantic models, tools, YAML, JSON Schema
- Renderers for Adaptive Cards, HTML5, and JSON Schema output
- Validators for form data validation
- Registry and PostgreSQL storage for form schemas
- Tools for LLM-driven form interaction and creation
"""

from .constraints import (
    ConditionOperator,
    DependencyRule,
    FieldCondition,
    FieldConstraints,
)
from .options import FieldOption, OptionsSource
from .schema import FormField, FormSchema, FormSection, RenderedForm, SubmitAction
from .style import FieldSizeHint, FieldStyleHint, LayoutType, StyleSchema
from .types import FieldType, LocalizedString
from .validators import FormValidator, ValidationResult
from .extractors.pydantic import PydanticExtractor
from .registry import FormRegistry, FormStorage
from .cache import FormCache
from .storage import PostgresFormStorage
from .tools.request_form import RequestFormTool
from .tools.create_form import CreateFormTool

__all__ = [
    # Types
    "LocalizedString",
    "FieldType",
    # Constraints
    "FieldConstraints",
    "ConditionOperator",
    "FieldCondition",
    "DependencyRule",
    # Options
    "FieldOption",
    "OptionsSource",
    # Schema
    "FormField",
    "FormSection",
    "SubmitAction",
    "FormSchema",
    "RenderedForm",
    # Style
    "LayoutType",
    "FieldSizeHint",
    "FieldStyleHint",
    "StyleSchema",
    # Validators
    "FormValidator",
    "ValidationResult",
    # Extractors
    "PydanticExtractor",
    # Registry
    "FormRegistry",
    "FormStorage",
    # Cache
    "FormCache",
    # Storage
    "PostgresFormStorage",
    # Tools
    "RequestFormTool",
    "CreateFormTool",
]
