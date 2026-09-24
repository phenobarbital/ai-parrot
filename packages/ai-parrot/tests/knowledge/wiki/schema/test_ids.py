"""Tests for schema-plane concept identifiers."""

import pytest

from parrot.knowledge.wiki.schema.ids import normalize_ref, parse_table_id, table_concept_id
from parrot.knowledge.wiki.schema.models import SchemaSourceConfig


def test_roundtrip() -> None:
    """Table ids round-trip through their parser."""
    table_id = table_concept_id("bigquery", "epson", "sales")
    assert table_id == "table:bigquery/epson.sales"
    assert parse_table_id(table_id) == ("bigquery", "epson", "sales")


def test_other_kind_raises() -> None:
    """Non-table ids are rejected."""
    with pytest.raises(ValueError):
        parse_table_id("schema:bigquery/epson")


def test_normalize_bare_form() -> None:
    """The origin-prefixed shorthand becomes a kind-first id."""
    assert normalize_ref("bigquery:epson.sales") == "table:bigquery/epson.sales"


def test_normalize_ambiguous_returns_candidates() -> None:
    """Unqualified refs preserve ambiguity across declared sources."""
    sources = {
        "a": SchemaSourceConfig(alias="a", dialect="postgres", dsn_env="A", allowed_schemas=["public"]),
        "b": SchemaSourceConfig(alias="b", dialect="postgres", dsn_env="B", allowed_schemas=["public"]),
    }
    output = normalize_ref("public.users", sources=sources)
    assert isinstance(output, list)
    assert len(output) == 2


def test_normalize_single_candidate_returns_string() -> None:
    """An unqualified ref collapses only when one source allows its schema."""
    sources = {"a": SchemaSourceConfig(alias="a", dialect="postgres", dsn_env="A", allowed_schemas=["public"])}
    assert normalize_ref("public.users", sources=sources) == "table:a/public.users"


def test_normalize_malformed_raises() -> None:
    """Malformed references are rejected."""
    with pytest.raises(ValueError):
        normalize_ref("not-a-reference")
