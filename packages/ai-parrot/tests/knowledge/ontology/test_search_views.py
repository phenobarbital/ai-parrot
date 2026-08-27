"""Unit tests for declarative ArangoSearch views (FEAT-449 TASK-2493, R15)."""

from __future__ import annotations

from datetime import UTC, datetime

import pytest
from parrot.knowledge.ontology.exceptions import OntologyIntegrityError
from parrot.knowledge.ontology.graph_store import OntologyGraphStore, _merge_link_field
from parrot.knowledge.ontology.merger import OntologyMerger
from parrot.knowledge.ontology.schema import (
    EntityDef,
    MergedOntology,
    OntologyDefinition,
    SearchViewDef,
    SearchViewField,
    SearchViewLink,
    TenantContext,
)


def _entity(collection: str) -> EntityDef:
    return EntityDef(collection=collection, key_field="id")


@pytest.fixture
def merger() -> OntologyMerger:
    return OntologyMerger()


@pytest.fixture
def base_layer() -> OntologyDefinition:
    return OntologyDefinition(
        name="base",
        entities={"Widget": _entity("widgets")},
        search_views={
            "v": SearchViewDef(
                links=[
                    SearchViewLink(
                        entity="Widget",
                        fields=[SearchViewField(path="title", analyzers=["text_en"])],
                    )
                ]
            )
        },
    )


@pytest.fixture
def overlay_layer() -> OntologyDefinition:
    return OntologyDefinition(
        name="overlay",
        entities={},
        search_views={
            "v": SearchViewDef(
                links=[
                    SearchViewLink(
                        entity="Widget",
                        fields=[SearchViewField(path="body", analyzers=["text_es"])],
                    )
                ]
            )
        },
    )


class TestSearchViewDefMergeAndValidation:
    def test_later_layer_wins_wholesale(self, merger, base_layer, overlay_layer):
        merged = merger.merge_definitions([base_layer, overlay_layer])
        assert merged.search_views["v"].links[0].fields[0].path == "body"
        assert merged.search_views["v"].links[0].fields[0].analyzers == ["text_es"]

    def test_unknown_entity_raises_integrity_error(self, merger):
        layer = OntologyDefinition(
            name="bad",
            entities={"Widget": _entity("widgets")},
            search_views={
                "v": SearchViewDef(links=[SearchViewLink(entity="Ghost", fields=[SearchViewField(path="x")])])
            },
        )
        with pytest.raises(OntologyIntegrityError, match="v"):
            merger.merge_definitions([layer])

    def test_two_level_nesting_rejected_at_merge_time(self, merger):
        layer = OntologyDefinition(
            name="bad",
            entities={"Widget": _entity("widgets")},
            search_views={
                "v": SearchViewDef(
                    links=[
                        SearchViewLink(
                            entity="Widget",
                            fields=[SearchViewField(path="a[*].b[*].c")],
                        )
                    ]
                )
            },
        )
        with pytest.raises(OntologyIntegrityError, match="v"):
            merger.merge_definitions([layer])

    def test_yaml_without_search_views_still_parses(self):
        defn = OntologyDefinition(name="no_views", entities={"Widget": _entity("widgets")})
        assert defn.search_views == {}


class TestLinkFieldPathGrammar:
    def test_bare_and_one_level_nesting(self):
        fields: dict = {}
        _merge_link_field(fields, "titulo")
        _merge_link_field(fields, "versions[*].text")
        assert fields == {"titulo": {}, "versions": {"fields": {"text": {}}}}

    def test_two_level_nesting_raises(self):
        with pytest.raises(ValueError):
            _merge_link_field({}, "a[*].b[*].c")

    def test_malformed_bracket_raises(self):
        with pytest.raises(ValueError):
            _merge_link_field({}, "a[bad]")


class FakeConnection:
    def __init__(self, views=None):
        self._views = views or []
        self.created: list[tuple] = []
        self.replaced: list[tuple] = []

    async def views(self):
        return self._views

    async def view(self, name):
        return next(v for v in self._views if v["name"] == name)

    async def create_view(self, *, name, view_type, properties):
        self.created.append((name, properties))

    async def replace_view(self, name, properties):
        self.replaced.append((name, properties))


class RaisingConnection:
    async def views(self):
        raise RuntimeError("server unreachable")


@pytest.fixture
def ctx_with_view() -> TenantContext:
    merged = MergedOntology(
        name="test",
        version="1.0",
        entities={"Widget": _entity("widgets")},
        relations={},
        traversal_patterns={},
        search_views={
            "widgets_view": SearchViewDef(
                links=[
                    SearchViewLink(
                        entity="Widget",
                        fields=[SearchViewField(path="title", analyzers=["text_en"])],
                    )
                ]
            )
        },
        layers=["test"],
        merge_timestamp=datetime.now(UTC),
    )
    return TenantContext(tenant_id="test", arango_db="test_db", pgvector_schema="test", ontology=merged)


class TestEnsureViewsIdempotent:
    async def test_creates_when_absent_and_skips_when_matching(self, ctx_with_view):
        store = OntologyGraphStore(arango_client=object())
        conn = FakeConnection()
        db = type("DB", (), {"_connection": conn})()

        await store._ensure_views(db, ctx_with_view)
        assert len(conn.created) == 1
        assert conn.replaced == []

        name, properties = conn.created[0]
        conn._views = [{"name": name, **properties}]
        await store._ensure_views(db, ctx_with_view)
        assert len(conn.created) == 1
        assert conn.replaced == []

    async def test_replaces_on_drift(self, ctx_with_view):
        store = OntologyGraphStore(arango_client=object())
        conn = FakeConnection(
            views=[{"name": "widgets_view", "links": {"widgets": {"analyzers": ["text_es"], "fields": {}}}}]
        )
        db = type("DB", (), {"_connection": conn})()

        await store._ensure_views(db, ctx_with_view)
        assert conn.created == []
        assert len(conn.replaced) == 1

    async def test_raising_connection_only_logs_warning(self, ctx_with_view):
        store = OntologyGraphStore(arango_client=object())
        db = type("DB", (), {"_connection": RaisingConnection()})()
        await store._ensure_views(db, ctx_with_view)  # must not raise
