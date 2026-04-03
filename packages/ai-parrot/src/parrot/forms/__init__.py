"""Universal Form Abstraction Layer for AI-Parrot.

This module is a backward-compatible re-export shim. All form functionality
has been moved to the `parrot-formdesigner` package (parrot.formdesigner.*).

Existing imports from parrot.forms continue to work unchanged.
"""

# Re-export everything from parrot.formdesigner for backward compatibility.
# No deprecation warnings per spec decision (non-production feature).
try:
    from parrot.formdesigner import *  # noqa: F401, F403
    from parrot.formdesigner import __all__  # noqa: F401
    # Also expose ValidationResult and FormStorage which are used by consumers
    from parrot.formdesigner.services.validators import ValidationResult  # noqa: F401
    from parrot.formdesigner.services.registry import FormStorage  # noqa: F401
except ImportError:
    # parrot-formdesigner not installed — fall back to local definitions
    from .constraints import (  # noqa: F401
        ConditionOperator,
        DependencyRule,
        FieldCondition,
        FieldConstraints,
    )
    from .options import FieldOption, OptionsSource  # noqa: F401
    from .schema import FormField, FormSchema, FormSection, RenderedForm, SubmitAction  # noqa: F401
    from .style import FieldSizeHint, FieldStyleHint, LayoutType, StyleSchema  # noqa: F401
    from .types import FieldType, LocalizedString  # noqa: F401
    from .validators import FormValidator, ValidationResult  # noqa: F401
    from .extractors.pydantic import PydanticExtractor  # noqa: F401
    from .registry import FormRegistry, FormStorage  # noqa: F401
    from .cache import FormCache  # noqa: F401
    from .storage import PostgresFormStorage  # noqa: F401
    from .tools.request_form import RequestFormTool  # noqa: F401
    from .tools.create_form import CreateFormTool  # noqa: F401
    from .tools.database_form import DatabaseFormTool  # noqa: F401

