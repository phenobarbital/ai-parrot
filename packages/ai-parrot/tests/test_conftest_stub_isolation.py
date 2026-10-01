"""Regression guard: a test module may not keep another module's imports.

FEAT-617 / issue:c3c59277ef77. Two distinct defects in this tree let a stand-in
module outlive the code that installed it, and both are guarded here:

1. ``tests/conftest.py`` installs ~32 lightweight stubs so the tree stays importable
   when an optional third-party package (navigator, asyncdb, querysource, navconfig)
   is missing. The original ``sys.modules.setdefault(name, stub)`` asked "is this
   name already imported?" -- a question about import ORDER, not availability -- so a
   stub pre-empted any module that merely had not been imported yet.
   ``_stub_if_absent`` now defers to ``importlib.util.find_spec``.

2. Eight test modules assign ``sys.modules[...]`` at MODULE scope and never restore,
   e.g. ``tests/integration/test_spatial_transport.py:95-96`` replaces the real
   ``aiohttp``. The ``pytest_collectstart``/``pytest_collectreport`` pair in
   ``conftest.py`` snapshots and restores what each module shadowed.

The tell in both cases is the same: a ``types.ModuleType`` stand-in has no
``__file__``, which surfaced as ``(unknown location)`` in the ImportError. These
tests assert that tell cannot reappear.

This class of bug has now been fixed three times (FEAT-268, then both halves of
FEAT-617). Do not delete this module.
"""
from __future__ import annotations

import importlib
import importlib.util
import sys
import types
from pathlib import Path

import pytest

CONFTEST_PATH = Path(__file__).parent / "conftest.py"

# Modules a test module in this tree has been observed to shadow, which are
# nevertheless genuinely importable. Each was verified to import standalone while
# simultaneously failing inside a full-tree collection -- the signature of the bug.
MUST_NOT_BE_SHADOWED = (
    "aiohttp",
    "aiohttp.web",
    "parrot._imports",
    "parrot.registry",
    "parrot.tools.filemanager",
)


def _load_conftest() -> types.ModuleType:
    """Load tests/conftest.py by path -- a conftest is not importable by name."""
    spec = importlib.util.spec_from_file_location("_feat617_conftest", CONFTEST_PATH)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@pytest.mark.parametrize("name", MUST_NOT_BE_SHADOWED)
def test_real_modules_are_not_shadowed(name: str) -> None:
    """A genuinely importable module must never be left replaced by a stand-in.

    Runs in the live pytest process, so it sees whatever the modules collected
    before it have done to sys.modules. A failure here names the poisoned module.
    """
    module = importlib.import_module(name)
    assert getattr(module, "__file__", None) is not None, (
        f"{name} resolved to a stand-in with no __file__ -- a test module shadowed it "
        f"and did not restore it (see issue:c3c59277ef77). Got {module!r}"
    )
    assert Path(module.__file__).exists(), f"{name}.__file__ does not exist on disk"


def test_stub_if_absent_leaves_a_resolvable_module_alone() -> None:
    """A resolvable module wins: returns False and installs nothing."""
    conftest = _load_conftest()
    # A real, importable stdlib module that this tree never stubs.
    name = "wave"
    sys.modules.pop(name, None)
    try:
        installed = conftest._stub_if_absent(name, types.ModuleType(name))
        assert installed is False
        assert name not in sys.modules or getattr(sys.modules[name], "__file__", None)
    finally:
        sys.modules.pop(name, None)


def test_stub_if_absent_installs_for_a_missing_module() -> None:
    """A genuinely absent module gets the stand-in."""
    conftest = _load_conftest()
    name = "parrot_feat617_definitely_not_a_real_module"
    stub = types.ModuleType(name)
    try:
        assert conftest._stub_if_absent(name, stub) is True
        assert sys.modules[name] is stub
    finally:
        sys.modules.pop(name, None)


def test_stub_if_absent_never_overwrites_an_existing_entry() -> None:
    """A name already in sys.modules is left exactly as it was."""
    conftest = _load_conftest()
    name = "parrot_feat617_sentinel_module"
    sentinel = types.ModuleType(name)
    sys.modules[name] = sentinel
    try:
        assert conftest._stub_if_absent(name, types.ModuleType(name)) is False
        assert sys.modules[name] is sentinel
    finally:
        sys.modules.pop(name, None)


def test_conftest_has_no_executable_setdefault_calls() -> None:
    """The setdefault pattern that caused this bug must not come back.

    Prose and commented-out references are fine; an executable call is not.
    """
    offenders = [
        f"{n}: {line.strip()}"
        for n, line in enumerate(CONFTEST_PATH.read_text().splitlines(), 1)
        if line.lstrip().startswith("sys.modules.setdefault(")
    ]
    assert not offenders, (
        "sys.modules.setdefault() shadows a real module whenever that module has not "
        "been imported yet -- use _stub_if_absent() (or monkeypatch.setitem inside a "
        "fixture) instead. Offenders:\n  " + "\n  ".join(offenders)
    )
