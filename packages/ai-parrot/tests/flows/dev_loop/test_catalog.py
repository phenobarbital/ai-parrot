"""Tests for the promoted dev-loop LLM backend catalog (FEAT-388, Module 1).

Guards two things: the ``examples/dev_loop/llm_catalog.py`` shim stays a
pure re-export of :mod:`parrot.flows.dev_loop.catalog` (same objects, not
just equal values), and the catalog data itself stays internally
consistent (unique backend ids).
"""

from __future__ import annotations

import importlib
import sys
from pathlib import Path

import pytest

PUBLIC_NAMES = [
    "BACKENDS",
    "JUDGE_BACKENDS",
    "ADVERSARIAL_BACKEND",
    "PRIMARY_REVIEW_BACKENDS",
    "BackendInfo",
    "get_backend",
    "backends_for_role",
    "effective_default_model",
    "default_judge_panel_payload",
    "catalog_payload",
]


@pytest.fixture
def shim():
    """Import the ``examples/dev_loop/llm_catalog`` shim by sys.path.

    Mirrors how ``examples/dev_loop/server.py`` imports it today
    (sys.path-based, not a package import).
    """
    examples_dev_loop = str(
        Path(__file__).resolve().parents[5] / "examples" / "dev_loop"
    )
    inserted = examples_dev_loop not in sys.path
    if inserted:
        sys.path.insert(0, examples_dev_loop)
    try:
        # Ensure a fresh import even if a prior test session cached it.
        sys.modules.pop("llm_catalog", None)
        module = importlib.import_module("llm_catalog")
        yield module
    finally:
        sys.modules.pop("llm_catalog", None)
        if inserted:
            sys.path.remove(examples_dev_loop)


def test_shim_reexports_identical_objects(shim):
    """Every public name on the shim is the exact same object as the catalog's."""
    from parrot.flows.dev_loop import catalog

    for name in PUBLIC_NAMES:
        assert getattr(shim, name) is getattr(catalog, name), (
            f"{name} on the shim is not identical to parrot.flows.dev_loop.catalog.{name}"
        )


def test_backends_have_unique_ids():
    from parrot.flows.dev_loop import catalog

    ids = [b.id for b in catalog.BACKENDS]
    assert len(ids) == len(set(ids))


def test_get_backend_returns_none_for_unknown():
    from parrot.flows.dev_loop import catalog

    assert catalog.get_backend("does-not-exist") is None


def test_backends_for_role_development_includes_all_backends():
    from parrot.flows.dev_loop import catalog

    development_ids = {b.id for b in catalog.backends_for_role("development")}
    all_ids = {b.id for b in catalog.BACKENDS}
    assert development_ids == all_ids
