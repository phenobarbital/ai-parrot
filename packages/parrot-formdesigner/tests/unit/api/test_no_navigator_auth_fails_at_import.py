"""Verify navigator-auth is a HARD dependency of ``api/routes.py`` (FEAT-152)."""

from __future__ import annotations

import importlib
import sys


def test_missing_navigator_auth_breaks_routes_import(monkeypatch):
    """Stubbing out ``navigator_auth`` causes ``api.routes`` import to fail."""
    # Drop any cached imports that would short-circuit the test, and restore
    # them afterwards so later tests keep the module objects they imported.
    saved = {k: v for k, v in sys.modules.items() if k.startswith("parrot_formdesigner.api")}
    for k in saved:
        sys.modules.pop(k, None)

    # Block navigator_auth at the importer level. Setting modules to None
    # makes Python treat them as not found.
    monkeypatch.setitem(sys.modules, "navigator_auth", None)
    monkeypatch.setitem(sys.modules, "navigator_auth.decorators", None)

    import pytest

    try:
        with pytest.raises((ImportError, ModuleNotFoundError)):
            importlib.import_module("parrot_formdesigner.api.routes")
    finally:
        for k in [k for k in sys.modules if k.startswith("parrot_formdesigner.api")]:
            sys.modules.pop(k, None)
        sys.modules.update(saved)
