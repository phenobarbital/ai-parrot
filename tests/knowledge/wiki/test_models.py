"""Unit tests for parrot.knowledge.wiki.models (TASK-1627)."""

import pytest
from parrot.knowledge.wiki.models import (
    WikiPageCategory,
    WikiConfig,
    SourceManifestEntry,
    WikiSearchResult,
    WikiLintReport,
)


class TestWikiPageCategory:
    """Tests for the WikiPageCategory enum."""

    def test_all_categories_exist(self):
        """WikiPageCategory must define exactly 7 members."""
        assert len(WikiPageCategory) == 7

    def test_expected_values(self):
        """All expected string values are present."""
        values = {c.value for c in WikiPageCategory}
        assert values == {
            "summary",
            "entity",
            "concept",
            "comparison",
            "overview",
            "synthesis",
            "answer",
        }

    def test_is_string_enum(self):
        """WikiPageCategory values compare equal to plain strings."""
        assert WikiPageCategory.SUMMARY == "summary"
        assert WikiPageCategory.ANSWER == "answer"


class TestWikiConfig:
    """Tests for WikiConfig model."""

    def test_defaults(self, tmp_path):
        """Default search_weights and page_categories are correct."""
        config = WikiConfig(wiki_name="test", storage_dir=tmp_path)
        assert config.search_weights == {"pageindex": 0.6, "graphindex": 0.4}
        assert len(config.page_categories) == 7

    def test_all_page_categories_included(self, tmp_path):
        """Default page_categories includes all WikiPageCategory members."""
        config = WikiConfig(wiki_name="test", storage_dir=tmp_path)
        category_values = {c.value for c in config.page_categories}
        expected = {c.value for c in WikiPageCategory}
        assert category_values == expected

    def test_custom_weights_valid(self, tmp_path):
        """Custom weights summing to 1.0 are accepted."""
        config = WikiConfig(
            wiki_name="w",
            storage_dir=tmp_path,
            search_weights={"pageindex": 0.7, "graphindex": 0.3},
        )
        assert config.search_weights["pageindex"] == pytest.approx(0.7)

    def test_invalid_weight_out_of_range(self, tmp_path):
        """Weights outside [0, 1] are rejected."""
        with pytest.raises(Exception):
            WikiConfig(
                wiki_name="w",
                storage_dir=tmp_path,
                search_weights={"pageindex": 1.5, "graphindex": -0.5},
            )

    def test_invalid_weights_sum(self, tmp_path):
        """Weights that do not sum to ~1.0 are rejected."""
        with pytest.raises(Exception):
            WikiConfig(
                wiki_name="w",
                storage_dir=tmp_path,
                search_weights={"pageindex": 0.3, "graphindex": 0.3},
            )

    def test_optional_fields_default_none(self, tmp_path):
        """Optional fields default to None."""
        config = WikiConfig(wiki_name="test", storage_dir=tmp_path)
        assert config.source_dir is None
        assert config.lightweight_model is None
        assert config.model is None


class TestSourceManifestEntry:
    """Tests for SourceManifestEntry model."""

    def _make_entry(self, **overrides):
        defaults = {
            "source_id": "src-001",
            "source_uri": "/path/to/doc.md",
            "file_hash": "abc123def456",
            "mtime": 1234567890.0,
            "ingested_at": "2026-01-01T00:00:00Z",
            "pages_generated": ["page-1", "page-2"],
        }
        defaults.update(overrides)
        return SourceManifestEntry(**defaults)

    def test_serialization_round_trip(self):
        """model_dump() and reconstruction produce identical data."""
        entry = self._make_entry()
        data = entry.model_dump()
        assert data["source_id"] == "src-001"
        assert data["file_hash"] == "abc123def456"
        assert data["status"] == "ingested"
        reconstructed = SourceManifestEntry(**data)
        assert reconstructed == entry

    def test_default_status(self):
        """Status defaults to 'ingested'."""
        entry = self._make_entry()
        assert entry.status == "ingested"

    def test_custom_status(self):
        """Custom status is preserved."""
        entry = self._make_entry(status="stale")
        assert entry.status == "stale"

    def test_empty_pages_generated(self):
        """pages_generated may be an empty list."""
        entry = self._make_entry(pages_generated=[])
        assert entry.pages_generated == []

    def test_pages_generated_round_trip(self):
        """pages_generated list is serialised and reconstructed correctly."""
        entry = self._make_entry(pages_generated=["p1", "p2", "p3"])
        data = entry.model_dump()
        assert data["pages_generated"] == ["p1", "p2", "p3"]


class TestWikiSearchResult:
    """Tests for WikiSearchResult model."""

    def _make_result(self, **overrides):
        defaults = {
            "node_id": "node-42",
            "title": "Neural Networks",
            "score": 0.87,
            "source": "pageindex",
            "snippet": "A neural network is a computational model...",
        }
        defaults.update(overrides)
        return WikiSearchResult(**defaults)

    def test_valid_result(self):
        """Basic construction works."""
        r = self._make_result()
        assert r.node_id == "node-42"
        assert r.score == pytest.approx(0.87)

    def test_score_bounds(self):
        """Scores outside [0, 1] are rejected."""
        with pytest.raises(Exception):
            self._make_result(score=1.5)
        with pytest.raises(Exception):
            self._make_result(score=-0.1)

    def test_category_optional(self):
        """category defaults to None."""
        r = self._make_result()
        assert r.category is None

    def test_category_set(self):
        """category accepts WikiPageCategory values."""
        from parrot.knowledge.wiki.models import WikiPageCategory

        r = self._make_result(category=WikiPageCategory.CONCEPT)
        assert r.category == WikiPageCategory.CONCEPT

    def test_snippet_defaults_empty(self):
        """snippet defaults to empty string when omitted."""
        r = WikiSearchResult(
            node_id="n1", title="T", score=0.5, source="graphindex"
        )
        assert r.snippet == ""


class TestWikiLintReport:
    """Tests for WikiLintReport model."""

    def test_defaults(self):
        """All list fields default to empty; total_issues is 0."""
        report = WikiLintReport()
        assert report.orphan_sources == []
        assert report.stale_sources == []
        assert report.uncovered_sources == []
        assert report.cross_ref_issues == []
        assert report.total_issues == 0

    def test_total_issues_computed(self):
        """total_issues is computed from the four issue lists."""
        report = WikiLintReport(
            orphan_sources=["s1", "s2"],
            stale_sources=["s3"],
            uncovered_sources=["s4"],
            cross_ref_issues=[{"from": "p1", "to": "p2"}],
        )
        assert report.total_issues == 5

    def test_okf_report_accepted(self):
        """okf_report accepts arbitrary nested dicts."""
        report = WikiLintReport(
            okf_report={"orphan_nodes": 3, "missing_types": ["X"]},
        )
        assert report.okf_report["orphan_nodes"] == 3
