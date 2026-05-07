"""Hard contract: ``import parrot_formdesigner`` must be metadata-only.

This test guards FEAT-152 §1 Goals: the top-level ``__init__.py`` must NOT
trigger imports of any submodule (``core``, ``api``, ``ui``, ``renderers``,
``controls``, ``tools``, ``extractors``, ``services``, ``handlers``) and must
NOT pull heavy deps (``aiohttp``, ``aiogram``, ``reportlab``, ``lxml``).

Every Wave 2 task MUST keep this test green.
"""

from __future__ import annotations

import importlib
import sys


def test_init_does_not_pull_submodules():
    """Importing ``parrot_formdesigner`` loads only ``version``."""
    # Drop any cached imports that would short-circuit the test.
    for k in list(sys.modules):
        if k.startswith("parrot_formdesigner"):
            sys.modules.pop(k, None)
    for k in ("aiohttp", "aiogram", "reportlab", "lxml"):
        sys.modules.pop(k, None)

    importlib.import_module("parrot_formdesigner")

    forbidden_prefixes = (
        "parrot_formdesigner.api",
        "parrot_formdesigner.ui",
        "parrot_formdesigner.handlers",
        "parrot_formdesigner.renderers",
        "parrot_formdesigner.controls",
        "parrot_formdesigner.tools",
        "parrot_formdesigner.extractors",
        "parrot_formdesigner.services",
        "parrot_formdesigner.core",
    )
    loaded = [k for k in sys.modules if k.startswith(forbidden_prefixes)]
    assert loaded == [], (
        f"parrot_formdesigner top-level pulled in: {loaded}"
    )

    # Heavy deps must not be pulled in transitively
    for k in ("aiohttp", "aiogram", "reportlab", "lxml"):
        assert k not in sys.modules, (
            f"{k} was loaded by parrot_formdesigner top-level"
        )


def test_handlers_import_breaks():
    """``import parrot_formdesigner.handlers`` raises ``ModuleNotFoundError``."""
    sys.modules.pop("parrot_formdesigner.handlers", None)
    import pytest

    with pytest.raises(ModuleNotFoundError):
        importlib.import_module("parrot_formdesigner.handlers")


def test_setup_form_routes_no_longer_exported():
    """``from parrot_formdesigner import setup_form_routes`` fails."""
    sys.modules.pop("parrot_formdesigner", None)
    pkg = importlib.import_module("parrot_formdesigner")
    assert not hasattr(pkg, "setup_form_routes")


def test_metadata_attributes_exposed():
    """Top-level still exposes version metadata."""
    sys.modules.pop("parrot_formdesigner", None)
    pkg = importlib.import_module("parrot_formdesigner")
    assert pkg.__version__ == "0.2.0"
    assert pkg.__title__ == "parrot-formdesigner"
    assert hasattr(pkg, "__author__")
    assert hasattr(pkg, "__license__")
