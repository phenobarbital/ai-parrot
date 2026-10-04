"""Unit tests for linked descriptor models (FEAT-598 M1)."""

from __future__ import annotations

import subprocess
import sys

import pytest
from pydantic import ValidationError

from parrot.outputs.a2ui import CreateSurface
from parrot.outputs.a2ui.linked import (
    Join,
    LinkedDataSource,
    LinkedSources,
    RefreshPolicy,
    TransformRef,
    TransformSpec,
    has_data_sources,
)


def test_linked_models_roundtrip(linked_source: LinkedDataSource) -> None:
    """Descriptors round-trip through their JSON wire representation."""
    payload = linked_source.model_dump(mode="json", by_alias=True)
    assert LinkedDataSource.model_validate(payload) == linked_source
    with pytest.raises(ValidationError):
        LinkedDataSource.model_validate({**payload, "unexpected": True})


def test_refresh_interval_min_30() -> None:
    """Interval refreshes require a minimum thirty-second cadence."""
    with pytest.raises(ValidationError):
        RefreshPolicy(policy="interval", interval_seconds=29)
    assert RefreshPolicy(policy="interval", interval_seconds=30).interval_seconds == 30
    with pytest.raises(ValidationError):
        RefreshPolicy(policy="interval")
    assert RefreshPolicy(policy="manual", interval_seconds=5).interval_seconds == 5


def test_transform_spec_ops_xor_ref() -> None:
    """Transforms have either inline operations or a catalogue reference."""
    with pytest.raises(ValidationError):
        TransformSpec()
    with pytest.raises(ValidationError):
        TransformSpec(ops=[{"op": "select", "columns": ["name"]}], ref=_reference())
    assert TransformSpec(ops=[{"op": "select", "columns": ["name"]}]).ops is not None
    assert TransformSpec(ref=_reference()).ref is not None


def test_ref_name_is_opaque() -> None:
    """Transform references use opaque name-and-version identifiers, not URLs."""
    assert TransformRef(name="group_by_day@1.0.0", integrity="sha384-hash").name == "group_by_day@1.0.0"
    for name in ("https://x/y.js", "a/b@1.0.0", "x@1.0"):
        with pytest.raises(ValidationError):
            TransformRef(name=name, integrity="sha384-hash")


def test_locked_must_be_subset_of_params(linked_source: LinkedDataSource) -> None:
    """Locked parameter names must have a matching parameter declaration."""
    with pytest.raises(ValidationError):
        linked_source.model_copy(update={"locked": ["unknown"]}).model_validate(
            linked_source.model_dump() | {"locked": ["unknown"]}
        )


def test_target_must_be_nonempty_pointer(linked_source: LinkedDataSource) -> None:
    """Descriptor targets are non-empty RFC 6901 JSON pointers."""
    payload = linked_source.model_dump()
    for target in ("", "activity/rows"):
        with pytest.raises(ValidationError):
            LinkedDataSource.model_validate(payload | {"target": target})


def test_linked_sources_key_matches_target_root(linked_source: LinkedDataSource) -> None:
    """Root source keys must match the first target reference token."""
    assert LinkedSources({"activity": linked_source}).root["activity"] == linked_source
    with pytest.raises(ValidationError):
        LinkedSources({"other": linked_source})


def test_join_with_alias_roundtrip() -> None:
    """The reserved ``with`` wire field round-trips through its Python alias."""
    spec = TransformSpec(ops=[{"op": "join", "with": "b", "on": [{"left": "k", "right": "k"}]}])
    assert isinstance(spec.ops[0], Join)
    assert spec.model_dump(by_alias=True)["ops"][0]["with"] == "b"


def test_derive_expr_recursive() -> None:
    """Nested arithmetic expressions parse recursively."""
    spec = TransformSpec(
        ops=[
            {
                "op": "derive",
                "name": "ratio",
                "expr": {"operator": "/", "left": "a", "right": {"operator": "+", "left": "b", "right": 1}},
            }
        ]
    )
    assert spec.model_dump()["ops"][0]["expr"]["right"]["operator"] == "+"


def test_has_data_sources_variants(linked_source: LinkedDataSource) -> None:
    """The extension predicate supports models, bare messages, and wrapped messages."""
    sources = {"activity": linked_source.model_dump(mode="json", by_alias=True)}
    bare = {"surfaceId": "surface", "metadata": {"extensions": {"parrot_data_sources": sources}}}
    model = CreateSurface.model_validate(bare)
    assert has_data_sources(model)
    assert has_data_sources(bare)
    assert has_data_sources({"createSurface": bare})
    assert not has_data_sources({"createSurface": {**bare, "metadata": {"extensions": {"parrot_data_sources": {}}}}})


def test_a2ui_import_is_pandas_free() -> None:
    """Importing the A2UI public package does not load pandas."""
    result = subprocess.run(
        [sys.executable, "-c", "import parrot.outputs.a2ui, sys; assert 'pandas' not in sys.modules"],
        check=False,
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0, result.stderr


def _reference() -> TransformRef:
    """Return a valid opaque transform reference for XOR tests."""
    return TransformRef(name="group_by_day@1.0.0", integrity="sha384-hash")
