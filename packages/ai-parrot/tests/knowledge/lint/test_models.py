"""Unit tests for lint engine data models and lazy context (FEAT-625)."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest

from parrot.knowledge.lint.context import LintContext
from parrot.knowledge.lint.models import Finding, LintOptions
from parrot.knowledge.lint.rule import make_fingerprint
from parrot.knowledge.wiki.file_store import InMemoryWikiStore


def test_fingerprint_stable() -> None:
    """Fingerprints are independent of subject ordering."""
    assert make_fingerprint("r", ["b", "a"]) == make_fingerprint("r", ["a", "b"])


def test_options_defaults() -> None:
    """Lint options retain their specified defaults."""
    options = LintOptions()
    assert options.fix is False
    assert options.llm_max_pairs == 50
    assert options.fail_on == "error"


def test_public_lazy_exports() -> None:
    """The public module resolves core names without importing the runner."""
    from parrot.knowledge.lint import Finding as PublicFinding
    from parrot.knowledge.lint import LintContext as PublicLintContext

    assert PublicFinding is Finding
    assert PublicLintContext is LintContext


def test_finding_defaults() -> None:
    """Finding collection fields receive independent empty defaults."""
    finding = Finding(rule_id="r", severity="warning", message="m", fingerprint="f")
    assert finding.subjects == []
    assert finding.data == {}


@pytest.mark.asyncio
async def test_context_caches(tmp_path: Path) -> None:
    """Pages are loaded once until the context cache is invalidated."""
    store = InMemoryWikiStore(tmp_path)
    context = LintContext(store)
    calls = 0
    original_dump_pages = store.dump_pages

    async def dump_pages_spy() -> list[dict[str, Any]]:
        nonlocal calls
        calls += 1
        return await original_dump_pages()

    store.dump_pages = dump_pages_spy  # type: ignore[method-assign]

    assert await context.pages() == []
    assert await context.pages() == []
    assert calls == 1

    context.invalidate()
    assert await context.pages() == []
    assert calls == 2
