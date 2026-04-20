"""Unit tests for parrot.registry.routing.ontology_signal (TASK-789)."""
import pytest
import warnings
from parrot.registry.routing import OntologyPreAnnotator


class FakeSyncResolver:
    def resolve_intent(self, query):
        class _Dec:
            action = "graph_query"
            pattern = "supplier-warehouse"
            aql = None
            suggested_post_action = None

        return _Dec()


class FakeAsyncResolver:
    async def resolve_intent(self, query):
        return {"action": "vector_only", "pattern": None}


class FakeSyncResolve:
    """Uses .resolve() instead of .resolve_intent()."""

    def resolve(self, query):
        return {"action": "graph_query", "pattern": "p1"}


class BoomResolver:
    def resolve_intent(self, query):
        raise RuntimeError("bad")


class NoMethodResolver:
    pass


@pytest.mark.asyncio
async def test_no_resolver_empty():
    ann = OntologyPreAnnotator(None)
    assert await ann.annotate("anything") == {}


@pytest.mark.asyncio
async def test_sync_resolver_normalizes():
    ann = OntologyPreAnnotator(FakeSyncResolver())
    out = await ann.annotate("supplier warehouse")
    assert out["action"] == "graph_query"
    assert out["pattern"] == "supplier-warehouse"


@pytest.mark.asyncio
async def test_async_resolver():
    ann = OntologyPreAnnotator(FakeAsyncResolver())
    out = await ann.annotate("similar")
    assert out["action"] == "vector_only"


@pytest.mark.asyncio
async def test_resolver_exception_returns_empty(caplog):
    ann = OntologyPreAnnotator(BoomResolver())
    result = await ann.annotate("x")
    assert result == {}


@pytest.mark.asyncio
async def test_no_method_resolver_returns_empty():
    ann = OntologyPreAnnotator(NoMethodResolver())
    result = await ann.annotate("x")
    assert result == {}


@pytest.mark.asyncio
async def test_resolve_fallback():
    """Resolver with .resolve() but no .resolve_intent() still works."""
    ann = OntologyPreAnnotator(FakeSyncResolve())
    out = await ann.annotate("q")
    assert out["action"] == "graph_query"


def test_init_does_not_leak_deprecation():
    with warnings.catch_warnings(record=True) as w:
        warnings.simplefilter("always")
        OntologyPreAnnotator(None)
    assert not any(issubclass(rec.category, DeprecationWarning) for rec in w)


@pytest.mark.asyncio
async def test_dict_result_returned_as_is():
    class DictResolver:
        def resolve_intent(self, query):
            return {"action": "vector_only", "entities": ["product", "supplier"]}

    ann = OntologyPreAnnotator(DictResolver())
    out = await ann.annotate("x")
    assert out["action"] == "vector_only"
    assert out["entities"] == ["product", "supplier"]
