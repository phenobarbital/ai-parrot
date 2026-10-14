"""Ontology contracts and validator dispatch tests (FEAT-540 M8)."""

from typing import cast

import pytest

from parrot.knowledge.ontology.contracts import (
    DynamicQuery,
    GraphDocumentStore,
    create_ontology_graph_store,
    register_ontology_backend,
)
from parrot.knowledge.ontology.exceptions import AQLValidationError, QueryValidationError
from parrot.knowledge.ontology.validators import validate_query


@pytest.mark.asyncio
async def test_unregistered_dialect_fails_closed() -> None:
    """Unsupported query dialects must be rejected before execution."""
    with pytest.raises(QueryValidationError):
        await validate_query("cypher", "MATCH (n) RETURN n")


@pytest.mark.asyncio
async def test_aql_dispatch() -> None:
    """The registered AQL validator preserves safe query text."""
    assert await validate_query("aql", "FOR d IN c RETURN d") == "FOR d IN c RETURN d"


@pytest.mark.asyncio
async def test_aql_mutation_dispatch_is_a_query_validation_error() -> None:
    """AQL-specific rejection remains catchable through the shared base."""
    with pytest.raises(AQLValidationError):
        await validate_query("aql", "REMOVE d IN c")


def test_dynamic_query_defaults_and_custom_backend_registry() -> None:
    """Contracts model binds and registry-created stores remain backend-neutral."""
    query = DynamicQuery(dialect="test", text="QUERY")
    assert query.bind_vars == {}
    assert query.collection_binds == {}

    expected_store = cast(GraphDocumentStore, object())

    def make_store() -> GraphDocumentStore:
        """Return the backend-neutral test double."""
        return expected_store

    register_ontology_backend("test-contracts", make_store)
    assert create_ontology_graph_store("test-contracts") is expected_store
    with pytest.raises(ValueError, match="Unknown ontology graph backend"):
        create_ontology_graph_store("missing-contracts")
