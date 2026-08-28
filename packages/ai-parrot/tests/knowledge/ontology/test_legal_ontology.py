"""Merge and shape tests for the legal ontology domain layer (TASK-2370, TASK-2371)."""

import pytest
from parrot.knowledge.ontology.merger import OntologyMerger
from parrot.knowledge.ontology.parser import OntologyParser
from parrot.knowledge.ontology.validators import validate_aql


@pytest.fixture
def merged():
    defaults = OntologyParser.get_defaults_dir()
    return OntologyMerger().merge(
        [
            defaults / "base.ontology.yaml",
            defaults / "domains" / "legal.ontology.yaml",
        ]
    )


class TestLegalOntology:
    def test_entities_present(self, merged):
        for name in ("Norma", "Articulo", "Materia", "SpanSuppression"):
            assert name in merged.entities

    def test_relations_present(self, merged):
        for name in ("modifica", "deroga", "pertenece_a"):
            assert name in merged.relations

    def test_collections(self, merged):
        assert {"norma", "articulo", "materia", "span_suppressions"} <= set(merged.get_entity_collections())
        assert {"modifica", "deroga", "pertenece_a"} <= set(merged.get_edge_collections())

    def test_versions_is_list_type(self, merged):
        props = {k: v for d in merged.entities["Articulo"].properties for k, v in d.items()}
        assert props["versions"].type == "list"

    def test_source_wiring(self, merged):
        assert merged.entities["Norma"].source == "boe"
        assert merged.entities["Articulo"].source == "boe"
        assert not merged.entities["Materia"].source  # static taxonomy — must be skipped
        assert not merged.entities["SpanSuppression"].source  # app-written, no data source

    def test_version_bumped(self):
        """The legal.ontology.yaml LAYER declares version 1.1.

        Note: OntologyMerger hardcodes MergedOntology.version = "1.0" for
        every merge (verified across all three merge entry points —
        merge/merge_definitions/merge_with_overlay in merger.py — none
        derive it from the source layers' own `version` field, and no
        consumer in this package reads merged.version). That field is
        therefore NOT the right place to assert the layer bump; this test
        checks the layer's own declared version via OntologyParser.load
        instead. Deviation from the task's Test Specification noted in
        the Completion Note.
        """
        defaults = OntologyParser.get_defaults_dir()
        layer = OntologyParser.load(defaults / "domains" / "legal.ontology.yaml")
        assert layer.version == "1.1"

    def test_span_suppression_entity(self, merged):
        assert merged.entities["SpanSuppression"].collection == "span_suppressions"


class TestLegalArticulosView:
    def test_search_view_declared(self, merged):
        view = merged.search_views["legal_articulos_view"]
        assert {link.entity for link in view.links} == {"Articulo", "Norma"}

    def test_articulo_link_indexes_versions_text(self, merged):
        view = merged.search_views["legal_articulos_view"]
        articulo_link = next(link for link in view.links if link.entity == "Articulo")
        assert articulo_link.fields[0].path == "versions[*].text"
        assert set(articulo_link.fields[0].analyzers) == {"text_es", "text_en"}

    def test_norma_link_indexes_titulo(self, merged):
        view = merged.search_views["legal_articulos_view"]
        norma_link = next(link for link in view.links if link.entity == "Norma")
        assert norma_link.fields[0].path == "titulo"


class TestSearchArticlesPattern:
    def test_pattern_present(self, merged):
        assert "search_articles" in merged.traversal_patterns

    @pytest.mark.asyncio
    async def test_passes_aql_validation_unchanged(self, merged):
        tpl = merged.traversal_patterns["search_articles"].query_template
        assert await validate_aql(tpl) == tpl

    def test_uses_declared_view_and_bm25(self, merged):
        tpl = merged.traversal_patterns["search_articles"].query_template
        assert "legal_articulos_view" in tpl
        assert "BM25(" in tpl

    def test_temporal_filter_present(self, merged):
        tpl = merged.traversal_patterns["search_articles"].query_template
        assert "v.valid_from <= @as_of" in tpl
        assert "v.valid_to == null OR v.valid_to > @as_of" in tpl

    def test_post_action_none(self, merged):
        assert merged.traversal_patterns["search_articles"].post_action == "none"


class TestArticleInForcePattern:
    def test_pattern_present(self, merged):
        assert "article_in_force" in merged.traversal_patterns

    def test_binds_declared(self, merged):
        tpl = merged.traversal_patterns["article_in_force"].query_template
        assert "@as_of" in tpl
        assert "@articulo_key" in tpl
        assert "@@articulo" in tpl

    @pytest.mark.asyncio
    async def test_passes_aql_validation(self, merged):
        tpl = merged.traversal_patterns["article_in_force"].query_template
        await validate_aql(tpl)  # must not raise

    def test_is_read_only(self, merged):
        tpl = merged.traversal_patterns["article_in_force"].query_template.upper()
        for kw in ("INSERT", "UPDATE", "REMOVE", "REPLACE", "UPSERT"):
            assert kw not in tpl

    def test_post_action_none(self, merged):
        assert merged.traversal_patterns["article_in_force"].post_action == "none"
