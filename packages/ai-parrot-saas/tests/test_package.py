"""Smoke tests for the ai-parrot-saas package skeleton.

These guard the two structural invariants that are easy to break by accident
and expensive to debug later: the package must import without pulling in the
server stack, and it must not become a contributor to the ``parrot.*``
namespace.
"""
from __future__ import annotations

import importlib
import sys
from pathlib import Path

import pytest


def test_package_imports_and_reports_version() -> None:
    """The package imports and exposes its metadata."""
    import parrot_saas

    assert parrot_saas.__version__
    assert parrot_saas.__title__ == "ai-parrot-saas"


def test_import_does_not_pull_in_heavy_stacks() -> None:
    """Importing ``parrot_saas`` must stay cheap.

    Sub-packages are lazily exported precisely so that reading ``__version__``
    (or importing the domain layer in a unit test) never drags in aiohttp,
    asyncdb or the agent stack. A regression here shows up as multi-second
    test collection and as import cycles at server start-up.
    """
    for module in list(sys.modules):
        if module == "parrot_saas" or module.startswith("parrot_saas."):
            del sys.modules[module]

    importlib.import_module("parrot_saas")

    assert "parrot_saas.tenancy" not in sys.modules
    assert "parrot_saas.handlers" not in sys.modules


def test_lazy_export_resolves() -> None:
    """PEP 562 lazy exports resolve on first attribute access."""
    import parrot_saas

    assert parrot_saas.TenantMode.SHARED.value == "shared"


def test_unknown_attribute_raises_attribute_error() -> None:
    """``__getattr__`` must not mask typos as import errors."""
    import parrot_saas

    with pytest.raises(AttributeError, match="no attribute 'nope'"):
        _ = parrot_saas.nope


def test_package_is_not_a_parrot_namespace_contributor() -> None:
    """The distribution must never ship ``src/parrot/``.

    The ``parrot`` namespace is merged via ``pkgutil.extend_path`` from the
    core package. A fourth contributor re-introduces the import-shadowing the
    root conftest already works around, so this is a hard structural rule
    rather than a style preference.
    """
    src = Path(__file__).resolve().parents[1] / "src"
    assert not (src / "parrot").exists(), (
        "ai-parrot-saas must not contribute to the parrot.* namespace; "
        "its top-level module is parrot_saas"
    )
