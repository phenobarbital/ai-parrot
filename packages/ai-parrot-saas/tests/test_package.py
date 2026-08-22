"""Smoke tests for the ai-parrot-saas package skeleton.

These guard the two structural invariants that are easy to break by accident
and expensive to debug later: the package must import without pulling in the
server stack, and it must not become a contributor to the ``parrot.*``
namespace.
"""
from __future__ import annotations

import os
import subprocess
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

    Measured in a **subprocess**, which is the only honest way to ask what a
    fresh import pulls in. The obvious alternative — deleting every
    ``parrot_saas`` entry from ``sys.modules`` and re-importing — corrupts the
    interpreter for every test that follows: modules imported earlier keep
    references to the old class objects, so a later ``isinstance`` check
    against a re-imported class fails and a ``monkeypatch`` on a re-imported
    ``conf`` silently misses. Both of those actually happened.
    """
    probe = (
        "import sys, parrot_saas;"
        "assert parrot_saas.__version__;"
        "leaked = [m for m in ('parrot_saas.tenancy', 'parrot_saas.handlers',"
        " 'aiohttp', 'asyncdb') if m in sys.modules];"
        "print(','.join(leaked))"
    )
    result = subprocess.run(
        [sys.executable, "-c", probe],
        capture_output=True,
        text=True,
        env={**os.environ, "PYTHONPATH": os.pathsep.join(sys.path)},
        check=False,
    )

    assert result.returncode == 0, result.stderr
    assert result.stdout.strip() == "", (
        f"importing parrot_saas pulled in: {result.stdout.strip()}"
    )


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
