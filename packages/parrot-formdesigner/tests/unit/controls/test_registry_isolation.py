"""FEAT-618 TASK-3912 registry fixture-isolation tests."""

from __future__ import annotations

import importlib
import sys

from parrot_formdesigner.controls.registry import _REGISTRY, get_controls
from parrot_formdesigner.core.types import FieldType


def test_registry_is_fully_seeded_at_module_scope() -> None:
    """Every FieldType has a registered control when no fixture is mid-flight."""
    saved = dict(_REGISTRY)
    try:
        _REGISTRY.clear()
        sys.modules.pop("parrot_formdesigner.controls.builtin", None)
        importlib.import_module("parrot_formdesigner.controls.builtin")

        assert {control.type for control in get_controls()} == {field_type.value for field_type in FieldType}
    finally:
        _REGISTRY.clear()
        _REGISTRY.update(saved)


def test_seed_fixture_restores_prior_contents() -> None:
    """A clear/re-import cycle restores the exact prior registry mapping."""
    saved = dict(_REGISTRY)
    try:
        _REGISTRY.clear()
        sys.modules.pop("parrot_formdesigner.controls.builtin", None)
        importlib.import_module("parrot_formdesigner.controls.builtin")
    finally:
        _REGISTRY.clear()
        _REGISTRY.update(saved)

    assert _REGISTRY == saved
