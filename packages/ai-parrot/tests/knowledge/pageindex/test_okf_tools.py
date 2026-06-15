"""Unit tests for OKF tools module (TASK-1558).

Tests verify:
- find_by_type filters candidates by exact type before ranking.
- list_concepts returns all concepts, optionally filtered by type.
- get_concept returns frontmatter + body for a concept_id.
- get_related returns graph neighbors, filterable by rel type.
- trace_mapping follows multi-hop typed chains.
- cite returns source provenance.
- All tools are decorated with @tool.
- OKFToolkit.get_tools() returns 6 tools.
"""

import pytest
from parrot.knowledge.pageindex.content_store import NodeContentStore
from parrot.knowledge.pageindex.okf.graph import KnowledgeGraph
from parrot.knowledge.pageindex.okf.ontology import ConceptType
from parrot.knowledge.pageindex.okf.tools import OKFToolkit


@pytest.fixture
def enriched_tree():
    """OKF-enriched tree with three typed nodes and edges."""
    return {
        "doc_name": "guide.pdf",
        "structure": [
            {
                "node_id": "0000",
                "concept_id": "safeguards/hipaa-164",
                "type": "Safeguard",
                "title": "HIPAA §164",
                "summary": "Security safeguard requirement",
                "source": {"document": "guide.pdf", "pages": [1, 5]},
                "relates_to": [{"concept": "controls/nist-ir-4", "rel": "maps_to"}],
                "nodes": [],
            },
            {
                "node_id": "0001",
                "concept_id": "controls/nist-ir-4",
                "type": "Control",
                "title": "NIST IR-4",
                "summary": "Incident handling control",
                "source": {"document": "guide.pdf", "pages": [6, 10]},
                "relates_to": [{"concept": "evidence/ir-plan", "rel": "satisfied_by"}],
                "nodes": [],
            },
            {
                "node_id": "0002",
                "concept_id": "evidence/ir-plan",
                "type": "Evidence",
                "title": "IR Plan",
                "summary": "Incident response plan document",
                "source": {"document": "guide.pdf", "pages": [11, 15]},
                "relates_to": [],
                "nodes": [],
            },
        ],
    }


@pytest.fixture
def toolkit(enriched_tree, tmp_path):
    """OKFToolkit with in-memory graph and empty content store."""
    graph = KnowledgeGraph(enriched_tree)
    store = NodeContentStore(tmp_path)
    return OKFToolkit(enriched_tree, graph, store, "test_tree")


class TestOKFToolkitSetup:
    """Tests for OKFToolkit initialization and tool registration."""

    def test_get_tools_returns_six(self, toolkit):
        """OKFToolkit.get_tools() returns exactly 6 tool callables."""
        tools = toolkit.get_tools()
        assert len(tools) == 6

    def test_tools_are_callable(self, toolkit):
        """All tools are callable."""
        for t in toolkit.get_tools():
            assert callable(t)


class TestFindByType:
    """Tests for find_by_type tool."""

    def test_filters_by_type(self, toolkit):
        """Only nodes with matching type are returned."""
        results = toolkit.find_by_type(concept_type=ConceptType.CONTROL, query="")
        assert all(r["type"] == "Control" for r in results)
        assert len(results) == 1
        assert results[0]["concept_id"] == "controls/nist-ir-4"

    def test_returns_empty_for_no_match(self, toolkit):
        """Type with no matching nodes returns empty list."""
        results = toolkit.find_by_type(concept_type=ConceptType.GUIDELINE, query="anything")
        assert results == []

    def test_query_filters_within_type(self, toolkit):
        """Query string filters within the type-filtered candidate set."""
        results = toolkit.find_by_type(concept_type=ConceptType.SAFEGUARD, query="hipaa")
        assert len(results) >= 1
        assert any(r["concept_id"] == "safeguards/hipaa-164" for r in results)

    def test_empty_query_returns_all_of_type(self, toolkit):
        """Empty query returns all nodes of the given type."""
        results = toolkit.find_by_type(concept_type=ConceptType.EVIDENCE, query="")
        assert any(r["concept_id"] == "evidence/ir-plan" for r in results)

    def test_result_has_expected_keys(self, toolkit):
        """Result dicts include concept_id, title, summary, type."""
        results = toolkit.find_by_type(concept_type=ConceptType.CONTROL, query="")
        assert results
        r = results[0]
        assert "concept_id" in r
        assert "title" in r
        assert "summary" in r
        assert "type" in r

    def test_raw_string_type_does_not_crash(self, toolkit):
        """Passing a raw string for concept_type (LLM path) works correctly.

        This is the regression test for the AttributeError that occurred when
        an LLM passed 'Control' as a plain str instead of ConceptType.CONTROL.
        """
        results = toolkit.find_by_type(concept_type="Control", query="")
        assert len(results) == 1
        assert results[0]["concept_id"] == "controls/nist-ir-4"


class TestListConcepts:
    """Tests for list_concepts tool."""

    def test_lists_all_without_filter(self, toolkit, enriched_tree):
        """No type filter returns all 3 concepts."""
        results = toolkit.list_concepts()
        assert len(results) == 3

    def test_filters_by_type(self, toolkit):
        """With type filter, only matching concepts returned."""
        results = toolkit.list_concepts(concept_type=ConceptType.CONTROL)
        assert len(results) == 1
        assert results[0]["concept_id"] == "controls/nist-ir-4"

    def test_result_has_expected_keys(self, toolkit):
        """Each result has concept_id, title, summary, type."""
        results = toolkit.list_concepts()
        for r in results:
            assert "concept_id" in r
            assert "title" in r
            assert "type" in r


class TestGetConcept:
    """Tests for get_concept tool."""

    def test_returns_concept(self, toolkit):
        """get_concept returns the concept dict with body."""
        result = toolkit.get_concept("controls/nist-ir-4")
        assert result["concept_id"] == "controls/nist-ir-4"
        assert result["title"] == "NIST IR-4"
        assert "body" in result

    def test_empty_body_when_no_sidecar(self, toolkit):
        """Body is empty string when no sidecar content exists."""
        result = toolkit.get_concept("evidence/ir-plan")
        assert result["body"] == ""

    def test_raises_for_unknown_concept(self, toolkit):
        """KeyError raised for unknown concept_id."""
        with pytest.raises(KeyError, match="nonexistent"):
            toolkit.get_concept("nonexistent")

    def test_body_from_content_store(self, enriched_tree, tmp_path):
        """Body is loaded from content store when sidecar exists."""
        graph = KnowledgeGraph(enriched_tree)
        store = NodeContentStore(tmp_path)
        store.save("tree", "controls--nist-ir-4", "Body text here.")
        tk = OKFToolkit(enriched_tree, graph, store, "tree")
        result = tk.get_concept("controls/nist-ir-4")
        assert "Body text here." in result["body"]


class TestGetRelated:
    """Tests for get_related tool."""

    def test_returns_neighbors(self, toolkit):
        """get_related returns outgoing edges."""
        edges = toolkit.get_related("safeguards/hipaa-164")
        assert any(e["concept"] == "controls/nist-ir-4" for e in edges)

    def test_filters_by_rel(self, toolkit):
        """Rel filter limits returned edges."""
        edges = toolkit.get_related("safeguards/hipaa-164", rel="maps_to")
        assert len(edges) == 1
        assert edges[0]["concept"] == "controls/nist-ir-4"

    def test_empty_for_unknown_concept(self, toolkit):
        """Unknown concept returns empty list."""
        edges = toolkit.get_related("nonexistent")
        assert edges == []

    def test_no_edges_returns_empty(self, toolkit):
        """Concept with no outgoing edges returns empty list."""
        edges = toolkit.get_related("evidence/ir-plan")
        assert edges == []


class TestTraceMapping:
    """Tests for trace_mapping tool."""

    def test_default_chain_follows_compliance_path(self, toolkit):
        """Default chain [maps_to, satisfied_by] follows safeguard→control→evidence."""
        paths = toolkit.trace_mapping("safeguards/hipaa-164")
        assert any("evidence/ir-plan" in path for path in paths)

    def test_custom_chain(self, toolkit):
        """Custom rel_chain is followed."""
        paths = toolkit.trace_mapping("safeguards/hipaa-164", rel_chain=["maps_to"])
        assert any("controls/nist-ir-4" in path for path in paths)

    def test_no_match_returns_empty(self, toolkit):
        """Chain with no matching edges returns empty list."""
        paths = toolkit.trace_mapping("evidence/ir-plan", rel_chain=["maps_to"])
        assert paths == []


class TestCite:
    """Tests for cite tool."""

    def test_returns_provenance(self, toolkit):
        """cite returns source provenance dict."""
        result = toolkit.cite("controls/nist-ir-4")
        assert result["document"] == "guide.pdf"
        assert result["pages"] == [6, 10]
        assert result["concept_id"] == "controls/nist-ir-4"

    def test_raises_for_unknown_concept(self, toolkit):
        """KeyError raised for unknown concept_id."""
        with pytest.raises(KeyError, match="nonexistent"):
            toolkit.cite("nonexistent")

    def test_empty_provenance_when_no_source(self, enriched_tree, tmp_path):
        """Concept without source field returns empty provenance."""
        # Remove source from a node
        enriched_tree["structure"][0].pop("source", None)
        graph = KnowledgeGraph(enriched_tree)
        store = NodeContentStore(tmp_path)
        tk = OKFToolkit(enriched_tree, graph, store, "t")
        result = tk.cite("safeguards/hipaa-164")
        assert result["document"] == ""
        assert result["pages"] is None
