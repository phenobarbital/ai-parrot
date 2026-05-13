"""Form-service registry — name → AbstractFormService subclass.

Mirrors parrot_formdesigner/controls/registry.py:67-113. Module-level dict
preserves registration order for stable iteration.
"""

from __future__ import annotations

import logging

from .abstract import AbstractFormService

logger = logging.getLogger(__name__)

_SERVICE_REGISTRY: dict[str, type[AbstractFormService]] = {}


def register_form_service(
    name: str,
    service_cls: type[AbstractFormService],
) -> None:
    """Register (or overwrite) a form-service class under ``name``.

    Idempotent: re-registering the same name overwrites and logs a warning.

    Args:
        name: Identifier exposed to DatabaseFormInput.service.
        service_cls: AbstractFormService subclass.
    """
    if name in _SERVICE_REGISTRY:
        logger.warning(
            "register_form_service: overwriting existing entry for name=%s",
            name,
        )
    _SERVICE_REGISTRY[name] = service_cls


def get_form_service(name: str) -> type[AbstractFormService]:
    """Resolve a registered form-service class by name.

    Args:
        name: The service name to look up.

    Returns:
        The registered AbstractFormService subclass.

    Raises:
        KeyError: if no service is registered under ``name``.
    """
    try:
        return _SERVICE_REGISTRY[name]
    except KeyError as exc:
        raise KeyError(
            f"Unknown form service '{name}'. "
            f"Registered: {sorted(_SERVICE_REGISTRY)}"
        ) from exc


def list_form_services() -> list[str]:
    """Return registered service names in registration order.

    Returns:
        List of registered service name strings.
    """
    return list(_SERVICE_REGISTRY.keys())
