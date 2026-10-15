"""Descriptor registry tests (FEAT-540 M5)."""

from __future__ import annotations

from types import SimpleNamespace

import pytest
from pydantic import BaseModel

from parrot.knowledge.wiki.transport import build_operation_descriptors


class _Input(BaseModel):
    """Minimal stable input schema used by registry test doubles."""

    query: str = ""


class _Tool:
    """Configured wiki-tool stand-in exposing the registry contract."""

    args_schema = _Input

    def __init__(self, name: str) -> None:
        """Initialize a tool with the supplied operation name."""
        self.name = name
        self.description = f"Description for {name}"


def _bundle(*names: str, vault_names: tuple[str, ...] = ()) -> SimpleNamespace:
    """Build a minimal configured bundle without opening a wiki store."""
    return SimpleNamespace(tools=[_Tool(name) for name in names], vault_tools=[_Tool(name) for name in vault_names])


def test_descriptors_are_deterministic() -> None:
    """Equivalent mounted tools produce equal names and schema fingerprints."""
    bundle = _bundle("wiki_query", "wiki_symbol_lookup", "ledger_open", vault_names=("vault_ingest",))

    first = build_operation_descriptors(bundle)
    second = build_operation_descriptors(bundle)

    assert [(item.name, item.schema_fingerprint) for item in first] == [
        (item.name, item.schema_fingerprint) for item in second
    ]


def test_duplicate_operation_names_are_rejected() -> None:
    """The registry refuses an ambiguous operation name."""
    with pytest.raises(ValueError, match="Duplicate wiki operation name: wiki_query"):
        build_operation_descriptors(_bundle("wiki_query", "wiki_query"))


@pytest.mark.parametrize(
    ("bundle", "expected_mounts"),
    [
        (
            _bundle("wiki_query", "wiki_symbol_lookup", "wiki_decision_why"),
            {"wiki_query": "core", "wiki_symbol_lookup": "structural", "wiki_decision_why": "decisions"},
        ),
        (
            _bundle("wiki_query", "ledger_open", "wiki_schema_lookup"),
            {"wiki_query": "core", "ledger_open": "ledger", "wiki_schema_lookup": "schema"},
        ),
        (
            _bundle("wiki_query", "wiki_page_hashes", "wiki_ingest_batch", vault_names=("vault_ingest",)),
            {
                "wiki_query": "core",
                "wiki_page_hashes": "bulk",
                "wiki_ingest_batch": "bulk",
                "vault_ingest": "vault",
            },
        ),
    ],
)
def test_descriptor_mounts_follow_configured_planes(
    bundle: SimpleNamespace,
    expected_mounts: dict[str, str],
) -> None:
    """Only tools assembled for a configuration appear in its descriptor registry."""
    descriptors = build_operation_descriptors(bundle)

    assert {item.name: item.mount for item in descriptors} == expected_mounts
