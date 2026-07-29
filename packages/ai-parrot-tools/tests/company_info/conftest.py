"""Fixtures for FEAT-305 CompanyInfoToolkit tests.

Provides recorded-HTML fixtures per source plus monkeypatch helpers that
replace the search/fetch layers so tests never touch the network or launch
a real browser (spec goal G6 — fixtures only, no live scraping in CI).
"""
from __future__ import annotations

from pathlib import Path
from typing import Callable, Optional
from unittest.mock import AsyncMock

import pytest
from bs4 import BeautifulSoup as bs

from parrot_tools.company_info.tool import CompanyInfoToolkit

FIXTURES_DIR = Path(__file__).parent / "fixtures"


def pytest_collection_modifyitems(config, items):
    """Skip `live`-marked tests unless explicitly selected via `-m live`.

    Goal G6 requires fixtures-only runs by default (no live scraping in
    CI): `pytest packages/ai-parrot-tools/tests/company_info/ -v` must pass
    without ever touching the network. `test_live_smoke` is the sole
    opt-in exception — pass `-m live` to actually run it.
    """
    markexpr = config.getoption("-m", default="")
    if "live" in markexpr:
        return
    skip_live = pytest.mark.skip(reason="Live test — opt-in only, run with `-m live`")
    for item in items:
        if "live" in item.keywords:
            item.add_marker(skip_live)


def _load_fixture(name: str) -> str:
    """Read a recorded HTML fixture file by name."""
    return (FIXTURES_DIR / name).read_text(encoding="utf-8")


@pytest.fixture
def leadiq_html() -> str:
    """Recorded LeadIQ company profile HTML."""
    return _load_fixture("leadiq.html")


@pytest.fixture
def rocketreach_html() -> str:
    """Recorded RocketReach company profile HTML."""
    return _load_fixture("rocketreach.html")


@pytest.fixture
def explorium_html() -> str:
    """Recorded Explorium.ai company profile HTML."""
    return _load_fixture("explorium.html")


@pytest.fixture
def siccode_html() -> str:
    """Recorded SICCode.com company profile HTML."""
    return _load_fixture("siccode.html")


@pytest.fixture
def visualvisitor_html() -> str:
    """Recorded VisualVisitor company profile HTML."""
    return _load_fixture("visualvisitor.html")


@pytest.fixture
def zoominfo_html() -> str:
    """Recorded ZoomInfo company profile HTML."""
    return _load_fixture("zoominfo.html")


@pytest.fixture
def toolkit() -> CompanyInfoToolkit:
    """A `CompanyInfoToolkit` instance safe to construct in tests.

    Passes dummy Google credentials so construction never depends on
    environment configuration; no network call is made until a Google CSE
    fallback search actually runs `.execute()` (fixture-only tests never
    reach that path unless explicitly exercising the fallback).
    """
    return CompanyInfoToolkit(google_api_key="test-key", google_cse_id="test-cse")


@pytest.fixture
def mock_driver(monkeypatch) -> Callable[[CompanyInfoToolkit, str], AsyncMock]:
    """Patch a toolkit's fetch layer to return fixture HTML, no browser launched.

    Usage::

        def test_x(toolkit, mock_driver, leadiq_html):
            mock_driver(toolkit, leadiq_html)
            result = await toolkit.scrape_leadiq("Acme Corp")

    Returns:
        A callable ``(toolkit, html) -> AsyncMock`` that patches
        `_fetch_page` and `_fetch_page_with_selenium` on the given toolkit
        instance to return `BeautifulSoup(html, "html.parser")`.
    """
    def _patch(tk: CompanyInfoToolkit, html: str) -> AsyncMock:
        soup = bs(html, "html.parser")
        fetch_mock = AsyncMock(return_value=soup)
        monkeypatch.setattr(tk, "_fetch_page", fetch_mock)
        monkeypatch.setattr(tk, "_fetch_page_with_selenium", fetch_mock)
        return fetch_mock

    return _patch


@pytest.fixture
def mock_search(monkeypatch) -> Callable[[CompanyInfoToolkit, Optional[str]], AsyncMock]:
    """Patch a toolkit's search layer to return a canned URL, no network calls.

    Usage::

        def test_x(toolkit, mock_search):
            mock_search(toolkit, "https://leadiq.com/c/acme")
            result = await toolkit.scrape_leadiq("Acme Corp")

    Returns:
        A callable ``(toolkit, url) -> AsyncMock`` that patches
        `_search_company_url` on the given toolkit instance to return
        `url` unconditionally (pass `None` to simulate a search miss).
    """
    def _patch(tk: CompanyInfoToolkit, url: Optional[str]) -> AsyncMock:
        search_mock = AsyncMock(return_value=url)
        monkeypatch.setattr(tk, "_search_company_url", search_mock)
        return search_mock

    return _patch
