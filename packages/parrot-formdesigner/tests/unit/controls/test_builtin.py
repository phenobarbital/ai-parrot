"""Tests for _BUILTIN_METADATA entries in controls/builtin.py."""

from __future__ import annotations

from parrot_formdesigner.controls.builtin import _BUILTIN_METADATA
from parrot_formdesigner.core.types import FieldType


def test_rest_metadata_present():
    entry = _BUILTIN_METADATA[FieldType.REST]
    assert entry["category"] == "advanced"
    assert entry["label"] == "REST"
    assert entry["render_hint"] == "upload"
    assert entry["supports_constraints"] is True


def test_rest_metadata_full_shape():
    entry = _BUILTIN_METADATA[FieldType.REST]
    assert entry["icon"] == "rest"
    assert entry["is_container"] is False
    assert "description" in entry
