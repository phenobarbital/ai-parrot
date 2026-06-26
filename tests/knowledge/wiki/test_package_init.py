"""Import smoke tests for parrot.knowledge.wiki package init (TASK-1635)."""

import pytest


class TestWikiPackageInit:
    """Verify that all public symbols are importable from parrot.knowledge.wiki."""

    def test_import_toolkit(self):
        """LLMWikiToolkit is importable from the package root."""
        from parrot.knowledge.wiki import LLMWikiToolkit
        assert LLMWikiToolkit is not None

    def test_import_config(self):
        """WikiConfig is importable from the package root."""
        from parrot.knowledge.wiki import WikiConfig
        assert WikiConfig is not None

    def test_import_page_category(self):
        """WikiPageCategory is importable from the package root."""
        from parrot.knowledge.wiki import WikiPageCategory
        assert WikiPageCategory is not None

    def test_import_source_manifest_entry(self):
        """SourceManifestEntry is importable from the package root."""
        from parrot.knowledge.wiki import SourceManifestEntry
        assert SourceManifestEntry is not None

    def test_import_wiki_search_result(self):
        """WikiSearchResult is importable from the package root."""
        from parrot.knowledge.wiki import WikiSearchResult
        assert WikiSearchResult is not None

    def test_import_wiki_lint_report(self):
        """WikiLintReport is importable from the package root."""
        from parrot.knowledge.wiki import WikiLintReport
        assert WikiLintReport is not None

    def test_import_source_collection_manager(self):
        """SourceCollectionManager is importable from the package root."""
        from parrot.knowledge.wiki import SourceCollectionManager
        assert SourceCollectionManager is not None

    def test_import_wiki_bookkeeper(self):
        """WikiBookkeeper is importable from the package root."""
        from parrot.knowledge.wiki import WikiBookkeeper
        assert WikiBookkeeper is not None

    def test_import_wiki_combined_search(self):
        """WikiCombinedSearch is importable from the package root."""
        from parrot.knowledge.wiki import WikiCombinedSearch
        assert WikiCombinedSearch is not None

    def test_import_wiki_ingest_orchestrator(self):
        """WikiIngestOrchestrator is importable from the package root."""
        from parrot.knowledge.wiki import WikiIngestOrchestrator
        assert WikiIngestOrchestrator is not None

    def test_import_ingest_report(self):
        """IngestReport is importable from the package root."""
        from parrot.knowledge.wiki import IngestReport
        assert IngestReport is not None

    def test_all_exports_present(self):
        """Every symbol in __all__ is accessible as an attribute of the module."""
        import parrot.knowledge.wiki as wiki
        for name in wiki.__all__:
            assert hasattr(wiki, name), f"Missing export: {name}"

    def test_all_is_defined(self):
        """__all__ is defined and is a list."""
        import parrot.knowledge.wiki as wiki
        assert hasattr(wiki, "__all__")
        assert isinstance(wiki.__all__, list)

    def test_all_exports_count(self):
        """__all__ contains at least 11 public symbols."""
        import parrot.knowledge.wiki as wiki
        assert len(wiki.__all__) >= 11
