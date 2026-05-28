"""Tests for ResearchNode envelope-aware caller migration (FEAT-138 TASK-949).

Verifies that _find_existing_issue branches on envelope ``status`` rather
than reading legacy dict keys directly.

Loaded via importlib to avoid the broken Cython chain (parrot.utils.types)
and navigator.utils.file import errors in the test environment.
"""
from __future__ import annotations

import importlib.util
import sys
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

# ---------------------------------------------------------------------------
# Bootstrap: stub all parrot modules that would trigger the broken chain
# before loading research.py directly.
# ---------------------------------------------------------------------------

_WORKTREE = Path(__file__).resolve().parent.parent  # packages/ai-parrot
_RESEARCH_PY = _WORKTREE / "src/parrot/flows/dev_loop/nodes/research.py"

# We need a real module object for the top-level `parrot` package so that
# `from parrot import conf` works with a patchable `conf` attribute.
if "parrot" not in sys.modules:
    _parrot_pkg = MagicMock()
    sys.modules["parrot"] = _parrot_pkg
else:
    _parrot_pkg = sys.modules["parrot"]

_conf_stub = MagicMock()
_parrot_pkg.conf = _conf_stub

# Stub every module that research.py imports (directly or transitively) to
# prevent the broken import chain from running.
_STUBS: dict = {}
for _name in [
    "parrot.conf",
    "parrot.utils",
    "parrot.utils.types",
    "parrot.bots",
    "parrot.bots.base",
    "parrot.bots.flows",
    "parrot.bots.flows.core",
    "parrot.bots.flows.core.node",
    "parrot.clients",
    "parrot.clients.factory",
    "parrot.flows",
    "parrot.flows.dev_loop",
    "parrot.flows.dev_loop.flow",
    "parrot.flows.dev_loop.dispatcher",
    "parrot.flows.dev_loop.models",
    "parrot.interfaces",
    "parrot.interfaces.file",
    "navigator",
    "navigator.utils",
    "navigator.utils.file",
]:
    if _name not in sys.modules:
        _stub = MagicMock()
        sys.modules[_name] = _stub
        _STUBS[_name] = _stub

# Make Node a plain Python class so ResearchNode can inherit from it.
sys.modules["parrot.bots.flows.core.node"].Node = object

# Provide the symbols research.py imports from parrot.flows.dev_loop.models
_models = sys.modules["parrot.flows.dev_loop.models"]
for _sym in ("BugBrief", "ClaudeCodeDispatchProfile", "LogSource",
             "ResearchOutput", "WorkBrief"):
    setattr(_models, _sym, MagicMock)

# LLMFactory just needs to exist
sys.modules["parrot.clients.factory"].LLMFactory = MagicMock()

# Load research.py directly from the worktree file path
_spec = importlib.util.spec_from_file_location(
    "parrot.flows.dev_loop.nodes.research",
    str(_RESEARCH_PY),
)
_research_mod = importlib.util.module_from_spec(_spec)
sys.modules["parrot.flows.dev_loop.nodes.research"] = _research_mod
_spec.loader.exec_module(_research_mod)

ResearchNode = _research_mod.ResearchNode  # type: ignore[attr-defined]


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture
def node():
    """ResearchNode with Jira toolkit and logger fully mocked."""
    n = ResearchNode.__new__(ResearchNode)
    n._jira = AsyncMock()
    n.logger = MagicMock()
    return n


def _make_brief(*, existing_key: str | None = None, summary: str = "Test summary"):
    """Build a simple mock BugBrief."""
    brief = MagicMock()
    brief.existing_issue_key = existing_key
    brief.summary = summary
    return brief


def _conf_patch(project: str | None = "NAV"):
    """Return a context manager that patches conf.config.get for JIRA_PROJECT."""
    return patch.object(_research_mod.conf, "config", create=True,
                        **{"get.return_value": project})


# ---------------------------------------------------------------------------
# existing_issue_key branch
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_existing_issue_ok(node):
    """status='ok' → return the key immediately without searching."""
    node._jira.jira_get_issue.return_value = {
        "status": "ok",
        "data": {"key": "NAV-1", "fields": {"summary": "Test summary"}},
        "query": "NAV-1",
        "message": "",
    }
    brief = _make_brief(existing_key="NAV-1", summary="Test summary")

    with _conf_patch("NAV"):
        result = await node._find_existing_issue(brief)

    assert result == "NAV-1"
    node._jira.jira_get_issue.assert_awaited_once_with("NAV-1")
    # Search should NOT have been called
    node._jira.jira_search_issues.assert_not_awaited()


@pytest.mark.asyncio
async def test_existing_issue_not_found_falls_back(node):
    """status='not_found' logs a warning and falls back to search; empty → None."""
    node._jira.jira_get_issue.return_value = {
        "status": "not_found",
        "data": None,
        "query": "NAV-9",
        "message": "Issue NAV-9 not found.",
    }
    node._jira.jira_search_issues.return_value = {
        "status": "empty",
        "data": {"total": 0, "issues": []},
        "query": "project = NAV ...",
        "message": "",
    }
    brief = _make_brief(existing_key="NAV-9", summary="unique summary")

    with _conf_patch("NAV"):
        result = await node._find_existing_issue(brief)

    assert result is None
    node._jira.jira_get_issue.assert_awaited_once_with("NAV-9")
    node._jira.jira_search_issues.assert_awaited_once()
    # Warning logged for the not_found status
    node.logger.warning.assert_called()


# ---------------------------------------------------------------------------
# summary search branch
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_search_ok_returns_matching_key(node):
    """status='ok' search with exact-match summary → returns key."""
    node._jira.jira_search_issues.return_value = {
        "status": "ok",
        "data": {
            "total": 1,
            "issues": [{"key": "NAV-7", "fields": {"summary": "exact title"}}],
        },
        "query": "project = NAV ...",
        "message": "",
    }
    brief = _make_brief(existing_key=None, summary="exact title")

    with _conf_patch("NAV"):
        result = await node._find_existing_issue(brief)

    assert result == "NAV-7"


@pytest.mark.asyncio
async def test_search_empty_returns_none(node):
    """status='empty' → empty issues list → no exact match → None."""
    node._jira.jira_search_issues.return_value = {
        "status": "empty",
        "data": {"total": 0, "issues": []},
        "query": "...",
        "message": "",
    }
    brief = _make_brief(existing_key=None, summary="anything")

    with _conf_patch("NAV"):
        result = await node._find_existing_issue(brief)

    assert result is None


@pytest.mark.asyncio
async def test_search_error_returns_none(node):
    """status='error' → log warning and return None (no propagation)."""
    node._jira.jira_search_issues.return_value = {
        "status": "error",
        "data": None,
        "query": "...",
        "message": "connection refused",
    }
    brief = _make_brief(existing_key=None, summary="anything")

    with _conf_patch("NAV"):
        result = await node._find_existing_issue(brief)

    assert result is None
    node.logger.warning.assert_called()
    # Check the warning mentions the error detail
    all_calls = " ".join(str(c) for c in node.logger.warning.call_args_list)
    assert "connection refused" in all_calls or "Jira lookup failed" in all_calls


@pytest.mark.asyncio
async def test_no_jira_project_returns_none_without_search(node):
    """Missing JIRA_PROJECT config → skip search entirely, return None."""
    brief = _make_brief(existing_key=None, summary="anything")

    with _conf_patch(None):  # JIRA_PROJECT not configured
        result = await node._find_existing_issue(brief)

    assert result is None
    node._jira.jira_search_issues.assert_not_awaited()
