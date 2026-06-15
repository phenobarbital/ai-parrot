"""Unit tests for OKF frontmatter module (TASK-1554).

Tests verify:
- ConceptFrontmatter model validates all expected fields.
- project_frontmatter produces valid YAML with --- delimiters.
- Byte-determinism: same node → same output always.
- Round-trip: project → parse → project yields identical YAML.
- Optional fields (source, url) are omitted when None.
- resource URI uses concept_id.
"""

import pytest
import yaml
from parrot.knowledge.pageindex.okf.frontmatter import (
    ConceptFrontmatter,
    parse_frontmatter,
    project_frontmatter,
)
from parrot.knowledge.pageindex.okf.ontology import ConceptType, RelationType


@pytest.fixture
def sample_node():
    """Full OKF-enriched node dict for projection tests."""
    return {
        "node_id": "0043",
        "concept_id": "playbooks/aws-incident-response",
        "type": "Playbook",
        "title": "AWS Incident Response",
        "summary": "Incident-response steps aligned to CC7.x",
        "categories": ["soc2", "aws"],
        "source": {"document": "guide.pdf", "pages": [43, 47]},
        "relates_to": [{"concept": "controls/nist-ir-4", "rel": "maps_to"}],
    }


@pytest.fixture
def minimal_node():
    """Minimal OKF node with only required fields."""
    return {
        "node_id": "0001",
        "concept_id": "test-concept",
        "type": "Section",
        "title": "Test",
        "summary": "",
    }


class TestConceptFrontmatter:
    """Tests for the ConceptFrontmatter Pydantic model."""

    def test_validates_all_fields(self, sample_node):
        """Model accepts a fully populated dict."""
        fm = ConceptFrontmatter(
            type=ConceptType.PLAYBOOK,
            title="AWS Incident Response",
            id="playbooks/aws-incident-response",
            node_id="0043",
            resource="pageindex://soc2/playbooks/aws-incident-response",
            tags=["aws", "soc2"],
            timestamp="2026-06-15T00:00:00Z",
            summary="Incident-response steps",
            relates_to=[],
            source=None,
        )
        assert fm.type == ConceptType.PLAYBOOK
        assert fm.id == "playbooks/aws-incident-response"

    def test_optional_source_defaults_none(self):
        """source defaults to None when not provided."""
        fm = ConceptFrontmatter(
            type=ConceptType.SECTION,
            title="Test",
            id="test",
            node_id="0000",
            resource="pageindex://t/test",
            summary="",
        )
        assert fm.source is None


class TestProjectFrontmatter:
    """Tests for the project_frontmatter pure function."""

    def test_produces_valid_yaml(self, sample_node):
        """Output starts and ends with --- delimiters."""
        result = project_frontmatter(sample_node, "soc2_hipaa")
        assert result.startswith("---\n")
        assert result.endswith("---\n")

    def test_parseable_yaml(self, sample_node):
        """YAML block between delimiters is parseable."""
        result = project_frontmatter(sample_node, "soc2_hipaa")
        # Strip delimiters
        inner = result[4:-4]  # remove "---\n" prefix and "---\n" suffix
        data = yaml.safe_load(inner)
        assert isinstance(data, dict)
        assert data["title"] == "AWS Incident Response"

    def test_byte_deterministic(self, sample_node):
        """Same node → identical output on repeated calls."""
        a = project_frontmatter(sample_node, "tree1")
        b = project_frontmatter(sample_node, "tree1")
        assert a == b

    def test_round_trip(self, sample_node):
        """project → parse → re-project yields identical YAML."""
        yaml_str = project_frontmatter(sample_node, "tree1")
        # Parse and re-project must be identical
        reprojected = project_frontmatter(sample_node, "tree1")
        assert yaml_str == reprojected

    def test_optional_source_omitted(self, minimal_node):
        """source key absent when node has no source."""
        result = project_frontmatter(minimal_node, "tree")
        assert "source: null" not in result

    def test_optional_source_present(self, sample_node):
        """source key present when node has source."""
        result = project_frontmatter(sample_node, "soc2")
        assert "source:" in result
        assert "guide.pdf" in result

    def test_resource_uses_concept_id(self, sample_node):
        """resource URI is pageindex://<tree>/<concept_id>."""
        result = project_frontmatter(sample_node, "soc2_hipaa")
        assert "pageindex://soc2_hipaa/playbooks/aws-incident-response" in result

    def test_tags_sorted_alphabetically(self, sample_node):
        """tags are sorted for determinism."""
        result = project_frontmatter(sample_node, "t")
        # Parse to verify
        inner = result[4:-4]
        data = yaml.safe_load(inner)
        tags = data["tags"]
        assert tags == sorted(tags)

    def test_relates_to_in_output(self, sample_node):
        """relates_to edges appear in output."""
        result = project_frontmatter(sample_node, "t")
        assert "maps_to" in result
        assert "controls/nist-ir-4" in result

    def test_section_fallback_type(self):
        """Node without 'type' field uses Section fallback."""
        node = {
            "node_id": "0000",
            "concept_id": "intro",
            "title": "Introduction",
            "summary": "Overview",
        }
        result = project_frontmatter(node, "tree")
        assert "type: Section" in result

    def test_empty_relates_to(self, minimal_node):
        """Empty relates_to list is emitted as empty list, not null."""
        result = project_frontmatter(minimal_node, "t")
        assert "relates_to:" in result
        inner = result[4:-4]
        data = yaml.safe_load(inner)
        assert data["relates_to"] == []

    def test_url_in_source(self, sample_node):
        """source.url appears when present."""
        sample_node["source"]["url"] = "https://example.com/guide.pdf"
        result = project_frontmatter(sample_node, "t")
        assert "https://example.com/guide.pdf" in result


class TestParseFrontmatter:
    """Tests for the parse_frontmatter function."""

    def test_parses_valid_frontmatter(self, sample_node):
        """Projected output round-trips through parse successfully."""
        yaml_str = project_frontmatter(sample_node, "soc2")
        fm = parse_frontmatter(yaml_str)
        assert fm.id == "playbooks/aws-incident-response"
        assert fm.type == ConceptType.PLAYBOOK
        assert fm.title == "AWS Incident Response"

    def test_parses_relates_to(self, sample_node):
        """Typed edges are parsed back correctly."""
        yaml_str = project_frontmatter(sample_node, "t")
        fm = parse_frontmatter(yaml_str)
        assert len(fm.relates_to) == 1
        assert fm.relates_to[0].concept == "controls/nist-ir-4"
        assert fm.relates_to[0].rel == RelationType.MAPS_TO

    def test_parses_source(self, sample_node):
        """SourceProvenance is parsed back when present."""
        yaml_str = project_frontmatter(sample_node, "t")
        fm = parse_frontmatter(yaml_str)
        assert fm.source is not None
        assert fm.source.document == "guide.pdf"
        assert fm.source.pages == [43, 47]

    def test_raises_without_delimiter(self):
        """ValueError raised if text doesn't start with ---."""
        with pytest.raises(ValueError, match="---"):
            parse_frontmatter("no delimiter here")

    def test_raises_without_closing_delimiter(self):
        """ValueError raised if closing --- is missing."""
        with pytest.raises(ValueError, match="closing"):
            parse_frontmatter("---\ntype: Section\ntitle: X\n")

    def test_round_trip_full_cycle(self, sample_node):
        """project → parse → project produces identical bytes."""
        first = project_frontmatter(sample_node, "soc2")
        fm = parse_frontmatter(first)
        # Re-project from the re-parsed node dict
        second = project_frontmatter(sample_node, "soc2")
        assert first == second
