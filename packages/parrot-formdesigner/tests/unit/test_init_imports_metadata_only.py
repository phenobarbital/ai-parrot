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

import pytest


# Modules that the metadata-only test must drop from sys.modules to verify
# that ``import parrot_formdesigner`` reloads cleanly without pulling them.
# We use ``monkeypatch.delitem`` (instead of ``sys.modules.pop``) so pytest
# restores the cached modules at teardown — otherwise downstream tests end
# up with two different module instances (and two different module-level
# state dicts like ``controls.registry._REGISTRY``), which causes flaky
# test-isolation failures.
_PF_PREFIXES = ("parrot_formdesigner",)
_HEAVY_DEPS = ("aiohttp", "aiogram", "reportlab", "lxml")


def _clear_pf_modules(monkeypatch: pytest.MonkeyPatch) -> None:
    """Drop ``parrot_formdesigner.*`` + heavy deps from sys.modules.

    Uses ``monkeypatch.delitem`` so the original cached modules are
    restored at fixture teardown — preventing cross-test pollution where
    a later test sees a freshly-loaded ``controls.registry`` module while
    other modules still reference the old one.
    """
    for k in list(sys.modules):
        if k.startswith(_PF_PREFIXES) and k in sys.modules:
            monkeypatch.delitem(sys.modules, k, raising=False)
    for k in _HEAVY_DEPS:
        if k in sys.modules:
            monkeypatch.delitem(sys.modules, k, raising=False)


def test_init_does_not_pull_submodules(monkeypatch):
    """Importing ``parrot_formdesigner`` loads only ``version``."""
    _clear_pf_modules(monkeypatch)

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
    for k in _HEAVY_DEPS:
        assert k not in sys.modules, (
            f"{k} was loaded by parrot_formdesigner top-level"
        )


def test_handlers_import_breaks():
    """``import parrot_formdesigner.handlers`` raises ``ModuleNotFoundError``."""
    sys.modules.pop("parrot_formdesigner.handlers", None)
    with pytest.raises(ModuleNotFoundError):
        importlib.import_module("parrot_formdesigner.handlers")


def test_setup_form_routes_no_longer_exported(monkeypatch):
    """``from parrot_formdesigner import setup_form_routes`` fails."""
    monkeypatch.delitem(sys.modules, "parrot_formdesigner", raising=False)
    pkg = importlib.import_module("parrot_formdesigner")
    assert not hasattr(pkg, "setup_form_routes")


def test_metadata_attributes_exposed(monkeypatch):
    """Top-level still exposes version metadata."""
    monkeypatch.delitem(sys.modules, "parrot_formdesigner", raising=False)
    pkg = importlib.import_module("parrot_formdesigner")
    assert pkg.__version__ == "0.2.0"
    assert pkg.__title__ == "parrot-formdesigner"
    assert hasattr(pkg, "__author__")
    assert hasattr(pkg, "__license__")
