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
        for name in ("Norma", "Articulo", "Materia"):
            assert name in merged.entities

    def test_relations_present(self, merged):
        for name in ("modifica", "deroga", "pertenece_a"):
            assert name in merged.relations

    def test_collections(self, merged):
        assert {"norma", "articulo", "materia"} <= set(merged.get_entity_collections())
        assert {"modifica", "deroga", "pertenece_a"} <= set(merged.get_edge_collections())

    def test_versions_is_list_type(self, merged):
        props = {k: v for d in merged.entities["Articulo"].properties for k, v in d.items()}
        assert props["versions"].type == "list"

    def test_source_wiring(self, merged):
        assert merged.entities["Norma"].source == "boe"
        assert merged.entities["Articulo"].source == "boe"
        assert not merged.entities["Materia"].source  # static taxonomy — must be skipped


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
