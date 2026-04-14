"""Tests for Package Init & Deprecation — TASK-054."""
import warnings


class TestDeprecation:
    def test_webscraping_tool_emits_warning(self):
        """Instantiating WebScrapingTool emits DeprecationWarning."""
        from parrot.tools.scraping.tool import WebScrapingTool

        with warnings.catch_warnings(record=True) as w:
            warnings.simplefilter("always")
            try:
                WebScrapingTool()
            except Exception:
                # Constructor may fail due to missing deps in test env;
                # we only care about the warning being emitted.
                pass
            deprecations = [
                x for x in w if issubclass(x.category, DeprecationWarning)
            ]
            assert len(deprecations) >= 1
            assert "WebScrapingToolkit" in str(deprecations[0].message)

    def test_toolkit_importable_from_package(self):
        """WebScrapingToolkit is importable from the scraping package."""
        from parrot.tools.scraping import WebScrapingToolkit

        assert WebScrapingToolkit is not None

    def test_legacy_import_still_works(self):
        """WebScrapingTool import from package still works."""
        from parrot.tools.scraping import WebScrapingTool

        assert WebScrapingTool is not None

    def test_all_new_exports(self):
        """All new models are exported from the scraping package."""
        from parrot.tools.scraping import (
            WebScrapingToolkit,
            DriverConfig,
            PlanSummary,
            PlanSaveResult,
            ScrapingPlan,
            PlanRegistry,
        )

        assert WebScrapingToolkit is not None
        assert DriverConfig is not None
        assert PlanSummary is not None
        assert PlanSaveResult is not None
        assert ScrapingPlan is not None
        assert PlanRegistry is not None

    def test_all_legacy_exports(self):
        """Legacy exports still present in __all__."""
        from parrot.tools.scraping import __all__

        assert "WebScrapingTool" in __all__
        assert "WebScrapingToolArgs" in __all__
        assert "ScrapingResult" in __all__

    def test_all_new_exports_in_all(self):
        """New exports are listed in __all__."""
        from parrot.tools.scraping import __all__

        for name in (
            "WebScrapingToolkit",
            "DriverConfig",
            "PlanSummary",
            "PlanSaveResult",
        ):
            assert name in __all__, f"{name} not in __all__"
