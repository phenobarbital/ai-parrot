"""Verifies the tools/services sub-package self-registers built-ins at import (TASK-1128)."""

import importlib

import pytest


def test_subpackage_exports_public_api() -> None:
    """Sub-package exposes all required public names."""
    mod = importlib.import_module("parrot_formdesigner.tools.services")
    for name in [
        "AbstractFormService",
        "NetworkninjaFormService",
        "register_form_service",
        "get_form_service",
        "list_form_services",
    ]:
        assert hasattr(mod, name), f"{name} not exported"


def test_networkninja_is_registered_at_import_time() -> None:
    """Importing tools.services auto-registers 'networkninja'."""
    from parrot_formdesigner.tools.services import (
        get_form_service,
        NetworkninjaFormService,
    )
    cls = get_form_service("networkninja")
    assert cls is NetworkninjaFormService


def test_unknown_service_after_import_still_raises() -> None:
    """Unknown service name raises KeyError even after the sub-package is imported."""
    from parrot_formdesigner.tools.services import get_form_service
    with pytest.raises(KeyError):
        get_form_service("definitely-not-registered")
