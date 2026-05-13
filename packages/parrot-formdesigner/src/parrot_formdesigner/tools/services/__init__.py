"""Form-source services for DatabaseFormTool.

This is **parrot_formdesigner.tools.services** (nested under tools/), NOT the
package-level parrot_formdesigner.services/ (which holds FormRegistry,
storage, cache, etc.). The two paths are distinct Python packages; they only
share the name. New form-source strategies live HERE.

Built-in services register at import time. Custom services can register via:

    from parrot_formdesigner.tools.services import register_form_service
    register_form_service("my_service", MyFormService)

before any DatabaseFormTool invocation that targets that service name.
"""

from .abstract import AbstractFormService
from .registry import (
    register_form_service,
    get_form_service,
    list_form_services,
)
from .networkninja import NetworkninjaFormService

# Built-in registrations (mirrors parrot_formdesigner/controls/builtin.py).
register_form_service("networkninja", NetworkninjaFormService)

__all__ = [
    "AbstractFormService",
    "NetworkninjaFormService",
    "register_form_service",
    "get_form_service",
    "list_form_services",
]
