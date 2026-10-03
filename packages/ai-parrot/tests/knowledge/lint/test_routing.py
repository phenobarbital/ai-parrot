"""Tests for lint finding routing (FEAT-625)."""

from __future__ import annotations

import sys
import types
from typing import Any

import pytest

if "parrot.utils.types" not in sys.modules:
    _utils_types_stub = types.ModuleType("parrot.utils.types")
    _utils_types_stub.SafeDict = dict
    _utils_types_stub.cPrint = lambda *args, **kwargs: None
    sys.modules["parrot.utils.types"] = _utils_types_stub

from parrot.knowledge.lint.models import Finding, LintOptions, LintReport  # noqa: E402
from parrot.knowledge.lint.routing import FindingRouter  # noqa: E402
from parrot.knowledge.wiki.store import WikiPageRecord  # noqa: E402


class FakeLedger:
    """In-memory ledger fake retaining the public ready/open contract."""

    def __init__(self) -> None:
        """Initialize an empty issue collection."""
        self.issues: list[dict[str, Any]] = []

    async def ready_work(self) -> list[dict[str, Any]]:
        """Return the open issues used by router deduplication."""
        return list(self.issues)

    async def open_issue(self, **kwargs: Any) -> str:
        """Record an open issue and return a test-only identifier."""
        self.issues.append(dict(kwargs))
        return f"issue:{len(self.issues)}"


class FakeStore:
    """Minimal mutable page store for note routing tests."""

    def __init__(self, pages: dict[str, dict[str, Any]] | None = None) -> None:
        """Initialize page rows keyed by their concept IDs."""
        self.pages = pages or {}

    async def get_page(self, concept_id: str, include_body: bool = True) -> dict[str, Any] | None:
        """Return a stored page row, if present."""
        return self.pages.get(concept_id)

    async def upsert_pages(self, pages: list[WikiPageRecord]) -> int:
        """Persist test records in their dictionary representation."""
        for page in pages:
            self.pages[page.concept_id] = page.model_dump()
        return len(pages)


def _finding(fingerprint: str, *, subject: str = "page:one", rule_id: str = "broken-link") -> Finding:
    """Build a representative unfixable warning finding."""
    return Finding(
        rule_id=rule_id,
        severity="warning",
        subjects=[subject],
        message="Broken reference",
        fingerprint=fingerprint,
    )


@pytest.mark.asyncio
async def test_ledger_dedup() -> None:
    """A repeated run opens no duplicate ledger issue."""
    ledger = FakeLedger()
    router = FindingRouter(FakeStore(), ledger=ledger)  # type: ignore[arg-type]
    report = LintReport(findings=[_finding("first")])

    first = await router.route(report, LintOptions(notes=False))
    second = await router.route(report, LintOptions(notes=False))

    assert first["ledger_opened"] == 1
    assert second["ledger_opened"] == 0
    assert second["ledger_deduped"] == 1
    assert len(ledger.issues) == 1
    assert ledger.issues[0]["body"].endswith("<!-- lint-fp:first -->")


@pytest.mark.asyncio
async def test_ledger_cap_aggregates() -> None:
    """Findings beyond the per-rule cap are combined into one issue."""
    ledger = FakeLedger()
    router = FindingRouter(FakeStore(), ledger=ledger)  # type: ignore[arg-type]
    report = LintReport(findings=[_finding("one"), _finding("two"), _finding("three")])

    counts = await router.route(report, LintOptions(notes=False, ledger_cap_per_rule=1))

    assert counts["ledger_opened"] == 2
    assert len(ledger.issues) == 2
    assert "2 aggregated findings" in ledger.issues[1]["title"]
    assert "Broken reference" in ledger.issues[1]["body"]


@pytest.mark.asyncio
async def test_notes_once() -> None:
    """A fingerprinted lint note is appended only once per page."""
    store = FakeStore(
        {
            "page:one": {
                "concept_id": "page:one",
                "title": "One",
                "category": "concept",
                "summary": "",
                "body": "Original body",
                "origin": "ingest",
            }
        }
    )
    router = FindingRouter(store)  # type: ignore[arg-type]
    report = LintReport(findings=[_finding("noted")])

    first = await router.route(report, LintOptions(ledger=False))
    second = await router.route(report, LintOptions(ledger=False))

    assert first["notes_added"] == 1
    assert second["notes_added"] == 0
    assert store.pages["page:one"]["body"].count("<!-- lint-fp:noted -->") == 1
