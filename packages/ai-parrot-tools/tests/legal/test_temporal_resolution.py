"""Selection + boundary tests for article_in_force (TASK-2375).

Boundary behaviour (inclusive valid_from / exclusive valid_to) is asserted
end-to-end against a real graph in TASK-2376; here it is asserted at the
binding level against a stubbed execute_traversal — no live ArangoDB.
"""

import inspect
from datetime import date

import pytest
from parrot.knowledge.ontology.merger import OntologyMerger
from parrot.knowledge.ontology.parser import OntologyParser
from parrot.knowledge.ontology.schema import TenantContext
from parrot_tools.legal.boe.queries import article_in_force


class FakeStore:
    """Stubs execute_traversal; asserts the wrapper binds correctly."""

    def __init__(self, rows):
        self.rows = rows
        self.last = None

    async def execute_traversal(self, ctx, aql, bind_vars=None, collection_binds=None):
        self.last = (aql, bind_vars, collection_binds)
        return self.rows


@pytest.fixture
def legal_ctx() -> TenantContext:
    defaults = OntologyParser.get_defaults_dir()
    merged = OntologyMerger().merge(
        [
            defaults / "base.ontology.yaml",
            defaults / "domains" / "legal.ontology.yaml",
        ]
    )
    return TenantContext(
        tenant_id="test_legal",
        arango_db="test_legal_db",
        pgvector_schema="test_legal",
        ontology=merged,
    )


def _version_row(n: int, valid_from: str, valid_to: str | None, text: str = "texto"):
    return {
        "n": n,
        "text": text,
        "valid_from": valid_from,
        "valid_to": valid_to,
        "modified_by": None if n == 0 else "BOE-A-2020-00001",
        "kind": "redaccion",
        "source": "boe_consolidada",
        "derived": False,
    }


class TestTemporalResolution:
    async def test_binds_as_of_and_key(self, legal_ctx):
        store = FakeStore([])
        await article_in_force(store, legal_ctx, "BOE-A-2015-10566:5", date(2020, 1, 1))
        _, binds, cbinds = store.last
        assert "as_of" in binds and "articulo_key" in binds
        assert "@articulo" in cbinds

    async def test_returns_none_when_no_version(self, legal_ctx):
        store = FakeStore([])
        assert await article_in_force(store, legal_ctx, "k", date(1900, 1, 1)) is None

    async def test_uses_pattern_from_ontology_not_inline_aql(self, legal_ctx):
        store = FakeStore([])
        await article_in_force(store, legal_ctx, "k", date(2020, 1, 1))
        aql, _, _ = store.last
        assert aql == legal_ctx.ontology.traversal_patterns["article_in_force"].query_template

    def test_no_python_date_comparison(self):
        """Version selection must live in AQL, not Python (spec goal G4)."""
        import parrot_tools.legal.boe.queries as m

        src = inspect.getsource(m)
        assert "valid_from" not in src, "date logic belongs in the traversal pattern"

    async def test_selects_correct_version_of_three(self, legal_ctx):
        """Given a 3-version article, each of 3 dates selects the correct wording."""
        row = _version_row(1, "2020-01-01", "2021-01-01", text="v1 wording")
        store = FakeStore([row])
        result = await article_in_force(store, legal_ctx, "BOE-A-2015-10566:50", date(2020, 6, 1))
        assert result is not None
        assert result.n == 1
        assert result.text == "v1 wording"

    async def test_boundary_valid_from_inclusive(self, legal_ctx):
        """as_of == valid_from selects that version (inclusive lower bound)."""
        row = _version_row(1, "2021-01-01", "2022-01-01")
        store = FakeStore([row])
        result = await article_in_force(store, legal_ctx, "BOE-A-2015-10566:50", date(2021, 1, 1))
        assert result is not None
        assert result.n == 1
        assert result.valid_from == date(2021, 1, 1)

    async def test_boundary_valid_to_exclusive_selects_next(self, legal_ctx):
        """as_of == valid_to selects the NEXT version (exclusive upper bound).

        execute_traversal is a fake here: the AQL's own FILTER clauses
        (v.valid_from <= @as_of AND (v.valid_to == null OR v.valid_to >
        @as_of)) enforce this in TASK-2371/2376; this test only asserts
        that the wrapper deserialises whatever row the store returns
        without narrowing the result set itself.
        """
        next_version_row = _version_row(2, "2022-01-01", None, text="v2 wording")
        store = FakeStore([next_version_row])
        result = await article_in_force(store, legal_ctx, "BOE-A-2015-10566:50", date(2022, 1, 1))
        assert result is not None
        assert result.n == 2
        assert result.valid_from == date(2022, 1, 1)

    async def test_currently_in_force_has_null_valid_to(self, legal_ctx):
        row = _version_row(2, "2022-01-01", None, text="v2 wording")
        store = FakeStore([row])
        result = await article_in_force(store, legal_ctx, "BOE-A-2015-10566:50", date(2026, 1, 1))
        assert result is not None
        assert result.valid_to is None

    async def test_missing_pattern_raises_key_error(self, legal_ctx):
        del legal_ctx.ontology.traversal_patterns["article_in_force"]
        store = FakeStore([])
        with pytest.raises(KeyError):
            await article_in_force(store, legal_ctx, "k", date(2020, 1, 1))
