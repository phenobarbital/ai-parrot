"""Descriptor registry tests (FEAT-540 M5)."""

from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest

from parrot.knowledge.wiki.project import WikiProjectConfig
from parrot.knowledge.wiki.transport import (
    WikiOperationContext,
    build_operation_descriptors,
    mounted_operation_names,
)


def _context(**overrides: Any) -> WikiOperationContext:
    """Build a context with no stores or framework objects behind it."""
    values: dict[str, Any] = {
        "store": object(),
        "read_store": object(),
        "root": Path("/nonexistent"),
        "config": WikiProjectConfig(wiki_name="descriptors"),
    }
    values.update(overrides)
    return WikiOperationContext(**values)


def test_descriptors_are_deterministic() -> None:
    """Equivalent configurations produce equal names and schema fingerprints."""
    context = _context(ledger_service=object(), vault_dir=Path("/vault"))

    first = build_operation_descriptors(context)
    second = build_operation_descriptors(context)

    assert [(item.name, item.schema_fingerprint) for item in first] == [
        (item.name, item.schema_fingerprint) for item in second
    ]


def test_descriptors_are_unique_and_accept_a_bundle() -> None:
    """A bundle-like object exposing ``.context`` resolves to the same registry."""
    context = _context(ledger_service=object(), include_bulk_tools=True, vault_dir=Path("/vault"))

    names = [item.name for item in build_operation_descriptors(SimpleNamespace(context=context))]

    assert len(names) == len(set(names))
    assert names == mounted_operation_names(context)


@pytest.mark.parametrize(
    ("overrides", "present", "absent"),
    [
        (
            {},
            {"wiki_query": "core", "wiki_symbol_lookup": "structural", "wiki_decision_why": "decisions"},
            {"ledger_open"},
        ),
        ({"ledger_service": object()}, {"wiki_query": "core", "ledger_open": "ledger"}, {"wiki_schema_lookup"}),
        (
            {"include_bulk_tools": True, "vault_dir": Path("/vault")},
            {"wiki_page_hashes": "bulk", "wiki_ingest_batch": "bulk", "vault_ingest": "vault"},
            {"ledger_open", "wiki_decision_generate"},
        ),
        ({"schema_service": object()}, {"wiki_schema_lookup": "schema"}, {"wiki_page_hashes", "vault_ingest"}),
    ],
)
def test_descriptor_mounts_follow_configured_planes(
    overrides: dict[str, Any],
    present: dict[str, str],
    absent: set[str],
) -> None:
    """Only operations a configuration mounts appear in its descriptor registry."""
    mounts = {item.name: item.mount for item in build_operation_descriptors(_context(**overrides))}

    assert {name: mounts[name] for name in present} == present
    assert not absent & set(mounts)
