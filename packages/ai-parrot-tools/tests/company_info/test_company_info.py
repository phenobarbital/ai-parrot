"""Tests for FEAT-305 CompanyInfoToolkit extensions.

Covers spec Module 1 (DDG-first search + hit validation), Module 2
(Playwright fetch layer), Module 3 (`scrape_visualvisitor`), and Module 4
(`research_company` first-success aggregate + wiring). All tests run
against recorded HTML fixtures / mocked search+fetch layers; no live
scraping happens in the default run (goal G6). `test_live_smoke` is the
sole exception, gated behind `-m live`.

See: sdd/specs/companyresearch-tool.spec.md §4 (Test Specification).
"""
from __future__ import annotations

from unittest.mock import AsyncMock, patch

import pytest
from ddgs.exceptions import RatelimitException

from parrot_tools.company_info.tool import (
    COMPANY_SOURCES,
    CompanyInfo,
    CompanyInfoToolkit,
    GoogleSearchResult,
)


# ===========================
# Module 1 — Search layer
# ===========================

class TestSearchLayer:
    """`SourceConfig` registry, `_search_company_url`, `_validate_search_hit`."""

    def test_source_configs_complete(self):
        """All 6 sources are registered with a non-empty site/template/keywords."""
        expected = {
            "leadiq", "rocketreach", "explorium", "siccode", "visualvisitor", "zoominfo"
        }
        assert set(COMPANY_SOURCES) == expected
        for name, cfg in COMPANY_SOURCES.items():
            assert cfg.name == name
            assert cfg.site
            assert cfg.search_template
            assert cfg.title_keywords

    def test_validate_hit_exact(self, toolkit):
        """Exact company-name match (case-insensitive) is accepted."""
        keywords = COMPANY_SOURCES["leadiq"].title_keywords
        assert toolkit._validate_search_hit(
            "Acme Corp Company Overview", "https://leadiq.com/c/acme", "Acme Corp", keywords,
            site="leadiq.com"
        ) is True

    def test_validate_hit_fuzzy(self, toolkit):
        """A close (but not exact) name match is accepted via rapidfuzz ratio > 85."""
        keywords = COMPANY_SOURCES["leadiq"].title_keywords
        assert toolkit._validate_search_hit(
            "Acme Corporation Company Overview", "https://leadiq.com/c/acme",
            "Acme Corp", keywords, site="leadiq.com"
        ) is True

    def test_validate_hit_reject(self, toolkit):
        """An unrelated company name is rejected."""
        keywords = COMPANY_SOURCES["leadiq"].title_keywords
        assert toolkit._validate_search_hit(
            "Totally Different Co Company Overview", "https://leadiq.com/c/other",
            "Acme Corp", keywords, site="leadiq.com"
        ) is False

    def test_validate_hit_no_keyword_match(self, toolkit):
        """A title without any of the source's keywords is rejected."""
        keywords = COMPANY_SOURCES["leadiq"].title_keywords
        assert toolkit._validate_search_hit(
            "Acme Corp — Random Unrelated Page Title", "https://leadiq.com/c/acme",
            "Acme Corp", keywords, site="leadiq.com"
        ) is False

    def test_validate_hit_wrong_domain_rejected(self, toolkit):
        """A title/company match on an untrusted host is rejected (SSRF-adjacent guard).

        Regression test for the code-review finding that `_validate_search_hit`
        only checked the title, allowing any host whose title happened to match
        to be accepted and handed to Playwright for navigation.
        """
        keywords = COMPANY_SOURCES["leadiq"].title_keywords
        assert toolkit._validate_search_hit(
            "Acme Corp Company Overview", "https://evil.example.com/c/acme",
            "Acme Corp", keywords, site="leadiq.com"
        ) is False

    def test_validate_hit_subdomain_accepted(self, toolkit):
        """A subdomain of the expected site (e.g. `www.`) is still accepted."""
        keywords = COMPANY_SOURCES["leadiq"].title_keywords
        assert toolkit._validate_search_hit(
            "Acme Corp Company Overview", "https://www.leadiq.com/c/acme",
            "Acme Corp", keywords, site="leadiq.com"
        ) is True

    def test_validate_hit_no_site_skips_domain_check(self, toolkit):
        """Omitting `site` preserves back-compat: no domain check performed."""
        keywords = COMPANY_SOURCES["leadiq"].title_keywords
        assert toolkit._validate_search_hit(
            "Acme Corp Company Overview", "https://anything.example.com/c/acme",
            "Acme Corp", keywords
        ) is True

    async def test_search_ddg_first_google_fallback(self, toolkit):
        """DDG rate-limited -> falls back to `_google_site_search`."""
        toolkit._ddg_search = AsyncMock(side_effect=RatelimitException("rate limited"))
        toolkit._google_site_search = AsyncMock(return_value=GoogleSearchResult(
            query="Acme Corp",
            site="leadiq.com",
            url="https://leadiq.com/c/acme",
            title="Acme Corp Company Overview",
            total_results=1,
        ))

        url = await toolkit._search_company_url("Acme Corp", COMPANY_SOURCES["leadiq"])

        assert url == "https://leadiq.com/c/acme"
        toolkit._google_site_search.assert_called_once()

    async def test_search_ddg_success_no_fallback(self, toolkit):
        """A validated DDG hit is accepted without ever calling Google CSE."""
        toolkit._ddg_search = AsyncMock(return_value=[
            {"title": "Acme Corp Company Overview", "href": "https://leadiq.com/c/acme"}
        ])
        toolkit._google_site_search = AsyncMock()

        url = await toolkit._search_company_url("Acme Corp", COMPANY_SOURCES["leadiq"])

        assert url == "https://leadiq.com/c/acme"
        toolkit._google_site_search.assert_not_called()

    def test_url_suffix_cleanup(self, toolkit):
        """`/employee-directory` and `/email-format` suffixes are stripped."""
        assert toolkit._clean_search_url(
            "https://leadiq.com/c/acme/employee-directory"
        ) == "https://leadiq.com/c/acme"
        assert toolkit._clean_search_url(
            "https://leadiq.com/c/acme/email-format"
        ) == "https://leadiq.com/c/acme"
        assert toolkit._clean_search_url(
            "https://leadiq.com/c/acme"
        ) == "https://leadiq.com/c/acme"


# ===========================
# Module 2 — Playwright fetch layer
# ===========================

class TestFetchLayer:
    """`_fetch_page` uses `driver_context(DriverConfig(driver_type="playwright"))`."""

    async def test_fetch_uses_playwright_config(self, toolkit):
        captured = {}

        class _FakeDriverContext:
            def __init__(self, config, session_driver=None):
                captured["config"] = config

            async def __aenter__(self):
                drv = AsyncMock()
                drv.navigate = AsyncMock(return_value=None)
                drv.get_page_source = AsyncMock(return_value="<html><body>ok</body></html>")
                return drv

            async def __aexit__(self, *exc_info):
                return False

        with patch("parrot_tools.company_info.tool.driver_context", _FakeDriverContext):
            soup = await toolkit._fetch_page("https://example.com")

        assert captured["config"].driver_type == "playwright"
        assert soup is not None
        assert soup.body.text == "ok"

    async def test_fetch_page_returns_none_on_failure(self, toolkit):
        """`_fetch_page` never raises; returns None if the driver errors."""
        class _FailingDriverContext:
            def __init__(self, config, session_driver=None):
                pass

            async def __aenter__(self):
                raise RuntimeError("boom")

            async def __aexit__(self, *exc_info):
                return False

        with patch("parrot_tools.company_info.tool.driver_context", _FailingDriverContext):
            soup = await toolkit._fetch_page("https://example.com")

        assert soup is None


# ===========================
# Module 3 — VisualVisitor extractor
# ===========================

class TestVisualVisitor:
    """`scrape_visualvisitor` — the new per-source method (spec Module 3)."""

    async def test_scrape_visualvisitor_fixture(
        self, toolkit, mock_search, mock_driver, visualvisitor_html
    ):
        mock_search(toolkit, "https://visualvisitor.com/c/acme")
        mock_driver(toolkit, visualvisitor_html)

        result = await toolkit.scrape_visualvisitor("Acme Corp")

        assert result.source_platform == "visualvisitor"
        assert result.scrape_status == "success"
        assert result.company_name == "Acme Corp"
        assert result.website == "https://acme.com"
        assert result.naics_code == "453910"
        assert result.sic_code == "5999"

    async def test_scrape_visualvisitor_no_hit(self, toolkit, mock_search):
        """No validated search hit -> `no_data`, never raises."""
        mock_search(toolkit, None)

        result = await toolkit.scrape_visualvisitor("Nonexistent Co")

        assert result.source_platform == "visualvisitor"
        assert result.scrape_status == "no_data"


# ===========================
# Modules 3/4 — existing extractors still parse fixture HTML
# ===========================

class TestEachSourceFixture:
    """Existing 5 extractors still parse their fixture HTML after the wiring change."""

    async def test_zoominfo_fixture(self, toolkit, mock_search, mock_driver, zoominfo_html):
        mock_search(toolkit, "https://zoominfo.com/c/acme")
        mock_driver(toolkit, zoominfo_html)

        result = await toolkit.scrape_zoominfo("Acme Corp")

        assert result.source_platform == "zoominfo"
        assert result.scrape_status == "success"
        assert result.company_name == "Acme Corp"
        toolkit._search_company_url.assert_awaited_once()

    async def test_zoominfo_forwards_custom_user_agent(
        self, toolkit, mock_search, mock_driver, zoominfo_html
    ):
        """ZoomInfo keeps the constructor's headless-hardening custom UA
        override (spec Module 2), forwarded explicitly on each fetch.

        Regression test for the code-review finding that `_fetch_page`'s
        `custom_user_agent` parameter was defined but never actually passed
        by any `scrape_*` call site.
        """
        toolkit._driver_config = toolkit._driver_config.merge(
            {"custom_user_agent": "Mozilla/5.0 (custom-hardened-ua)"}
        )
        mock_search(toolkit, "https://zoominfo.com/c/acme")
        fetch_mock = mock_driver(toolkit, zoominfo_html)

        await toolkit.scrape_zoominfo("Acme Corp")

        fetch_mock.assert_awaited_once_with(
            "https://zoominfo.com/c/acme",
            custom_user_agent="Mozilla/5.0 (custom-hardened-ua)"
        )

    async def test_explorium_fixture(self, toolkit, mock_search, mock_driver, explorium_html):
        mock_search(toolkit, "https://explorium.ai/c/acme")
        mock_driver(toolkit, explorium_html)

        result = await toolkit.scrape_explorium("Acme Corp")

        assert result.source_platform == "explorium"
        assert result.scrape_status == "success"
        assert result.company_name == "Acme Corp"

    async def test_leadiq_fixture(self, toolkit, mock_search, mock_driver, leadiq_html):
        mock_search(toolkit, "https://leadiq.com/c/acme")
        mock_driver(toolkit, leadiq_html)

        result = await toolkit.scrape_leadiq("Acme Corp")

        assert result.source_platform == "leadiq"
        assert result.scrape_status == "success"
        assert result.company_name == "Acme Corp"

    async def test_rocketreach_fixture(self, toolkit, mock_search, mock_driver, rocketreach_html):
        mock_search(toolkit, "https://rocketreach.co/acme")
        mock_driver(toolkit, rocketreach_html)

        result = await toolkit.scrape_rocketreach("Acme Corp")

        assert result.source_platform == "rocketreach"
        assert result.scrape_status == "success"

    async def test_siccode_fixture(self, toolkit, mock_search, mock_driver, siccode_html):
        mock_search(toolkit, "https://siccode.com/c/acme")
        mock_driver(toolkit, siccode_html)

        result = await toolkit.scrape_siccode("Acme Corp")

        assert result.source_platform == "siccode"
        assert result.scrape_status == "success"
        assert result.company_name == "Acme Corp"


# ===========================
# Module 4 — research_company aggregate
# ===========================

class TestResearchCompany:
    """`research_company` — first-success priority loop (spec Module 4)."""

    async def test_research_company_first_success(self, toolkit):
        toolkit.scrape_leadiq = AsyncMock(
            return_value=CompanyInfo(scrape_status="no_data", source_platform="leadiq")
        )
        toolkit.scrape_rocketreach = AsyncMock(
            return_value=CompanyInfo(
                scrape_status="success", source_platform="rocketreach", company_name="Acme"
            )
        )
        toolkit.scrape_explorium = AsyncMock(
            return_value=CompanyInfo(scrape_status="success", source_platform="explorium")
        )

        result = await toolkit.research_company("Acme Corp")

        assert result.source_platform == "rocketreach"
        assert result.scrape_status == "success"
        toolkit.scrape_leadiq.assert_awaited_once()
        toolkit.scrape_rocketreach.assert_awaited_once()
        toolkit.scrape_explorium.assert_not_called()

    async def test_research_company_sources_param(self, toolkit):
        toolkit.scrape_leadiq = AsyncMock(
            return_value=CompanyInfo(scrape_status="success", source_platform="leadiq")
        )
        toolkit.scrape_rocketreach = AsyncMock()

        # Explicit subset/order respected: only "leadiq" is tried.
        result = await toolkit.research_company("Acme Corp", sources=["leadiq"])
        assert result.source_platform == "leadiq"
        toolkit.scrape_rocketreach.assert_not_called()

        # Unknown source name -> clean error, no raise.
        result2 = await toolkit.research_company("Acme Corp", sources=["not-a-real-source"])
        assert result2.scrape_status == "error"
        assert "not-a-real-source" in result2.error_message

    async def test_research_company_empty_sources_tries_nothing(self, toolkit):
        """`sources=[]` is a deliberate "try nothing" request, distinct from
        `sources=None` (which uses the full default priority order).

        Regression test for the code-review finding that `sources or
        DEFAULT_SOURCE_PRIORITY` silently treated an explicit empty list the
        same as unset, due to Python's falsy-empty-list semantics.
        """
        toolkit.scrape_leadiq = AsyncMock()
        toolkit.scrape_rocketreach = AsyncMock()

        result = await toolkit.research_company("Acme Corp", sources=[])

        assert result.scrape_status == "no_data"
        toolkit.scrape_leadiq.assert_not_called()
        toolkit.scrape_rocketreach.assert_not_called()

    async def test_research_company_all_fail(self, toolkit):
        for name in COMPANY_SOURCES:
            setattr(
                toolkit,
                f"scrape_{name}",
                AsyncMock(return_value=CompanyInfo(scrape_status="no_data", source_platform=name)),
            )

        result = await toolkit.research_company("Nonexistent Co")

        assert result.scrape_status == "no_data"
        for name in COMPANY_SOURCES:
            assert name in result.error_message

    async def test_research_company_never_raises_on_source_exception(self, toolkit):
        """A `scrape_*` method raising unexpectedly must not escape `research_company`."""
        toolkit.scrape_leadiq = AsyncMock(side_effect=RuntimeError("boom"))
        for name in ["rocketreach", "explorium", "siccode", "visualvisitor", "zoominfo"]:
            setattr(
                toolkit,
                f"scrape_{name}",
                AsyncMock(return_value=CompanyInfo(scrape_status="no_data", source_platform=name)),
            )

        result = await toolkit.research_company("Acme Corp")

        assert result.scrape_status == "no_data"
        assert "leadiq" in result.error_message


# ===========================
# Integration — tool exposure
# ===========================

class TestToolkitExposure:
    """`get_tools()` exposes `research_company` + `scrape_visualvisitor`; back-compat intact."""

    def test_toolkit_tools_exposed(self, toolkit):
        tool_names = {t.name for t in toolkit.get_tools()}

        assert "research_company" in tool_names
        assert "scrape_visualvisitor" in tool_names
        for name in [
            "scrape_zoominfo", "scrape_explorium", "scrape_leadiq",
            "scrape_rocketreach", "scrape_siccode", "scrape_all_sources",
        ]:
            assert name in tool_names

    def test_construction_back_compat(self):
        """Legacy ctor kwargs still construct without error."""
        CompanyInfoToolkit(google_api_key="k", google_cse_id="c")
        CompanyInfoToolkit(
            google_api_key="k", google_cse_id="c",
            browser="chrome", use_undetected=True,
        )

    def test_construction_browser_undetected_warns(self, caplog):
        """`browser='undetected'` has no Playwright equivalent and must warn.

        Regression test for the code-review finding that this documented
        legacy value silently degraded every `_fetch_page` call to a 100%
        failure mode with no deprecation warning (unlike `use_undetected=True`,
        which already warned).
        """
        with caplog.at_level("WARNING"):
            CompanyInfoToolkit(
                google_api_key="k", google_cse_id="c", browser="undetected",
            )
        assert any(
            "browser='undetected'" in record.message for record in caplog.records
        )

    @pytest.mark.live
    async def test_live_smoke(self):
        """One real `research_company()` run for manual selector validation.

        Opt-in only (`-m live`); skipped by default so CI never scrapes
        live sites. Requires network access; treat failures as informative
        signal for selector drift, not as a CI-blocking assertion.
        """
        toolkit = CompanyInfoToolkit()
        result = await toolkit.research_company("PetSmart")
        assert result.scrape_status in {"success", "no_data"}
