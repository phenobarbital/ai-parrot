"""Tests for JiraToolkit envelope shape (FEAT-138 TASK-948)."""
from unittest.mock import AsyncMock, MagicMock, patch
import pytest

from parrot_tools.jiratoolkit import JiraToolkit, JiraToolEnvelope, AuthorizationRequired


@pytest.fixture
def toolkit():
    """JiraToolkit with the underlying JIRA client fully mocked."""
    with patch("parrot_tools.jiratoolkit.JIRA"):
        tk = JiraToolkit(
            server_url="https://x.atlassian.net",
            auth_type="basic_auth",
            username="u",
            password="p",
        )
    tk.jira = MagicMock()
    return tk


# ---------------------------------------------------------------------------
# jira_get_issue
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_get_issue_ok(toolkit):
    """Successful lookup wraps result in status='ok' envelope."""
    fake = MagicMock()
    toolkit.jira.issue.return_value = fake
    toolkit._issue_to_dict = lambda obj: {"key": "NAV-1", "fields": {"summary": "x"}}

    result = await toolkit.jira_get_issue("NAV-1")
    assert result["status"] == "ok"
    assert result["data"]["key"] == "NAV-1"
    assert result["query"] == "NAV-1"
    assert result["message"] == ""


@pytest.mark.asyncio
async def test_get_issue_not_found(toolkit):
    """HTTP 404 JIRAError becomes status='not_found'."""
    from jira.exceptions import JIRAError
    err = JIRAError(status_code=404, text="Issue Does Not Exist")
    toolkit.jira.issue.side_effect = err

    result = await toolkit.jira_get_issue("ZZZ-9999")
    assert result["status"] == "not_found"
    assert result["data"] is None
    assert "ZZZ-9999" in result["message"]


@pytest.mark.asyncio
async def test_get_issue_runtime_error_returns_envelope(toolkit):
    """Recoverable RuntimeError becomes status='error' envelope."""
    toolkit.jira.issue.side_effect = RuntimeError("connection refused")

    result = await toolkit.jira_get_issue("NAV-1")
    assert result["status"] == "error"
    assert result["data"] is None
    assert "connection refused" in result["message"]


@pytest.mark.asyncio
async def test_get_issue_auth_error_propagates(toolkit):
    """AuthorizationRequired is NOT wrapped — it propagates to the caller."""
    toolkit.jira.issue.side_effect = AuthorizationRequired(
        tool_name="jira", message="login required"
    )

    with pytest.raises(AuthorizationRequired):
        await toolkit.jira_get_issue("NAV-1")


# ---------------------------------------------------------------------------
# jira_search_issues
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_search_issues_empty(toolkit):
    """Zero results → status='empty' with empty issues list."""
    toolkit.jira.enhanced_search_issues.return_value = MagicMock(
        __iter__=lambda self: iter([]),
        nextPageToken=None,
        isLast=True,
    )

    result = await toolkit.jira_search_issues("project = NOPE")
    assert result["status"] == "empty"
    assert result["data"]["issues"] == []
    assert result["data"]["total"] == 0


@pytest.mark.asyncio
async def test_search_issues_ok(toolkit):
    """Non-empty results → status='ok' with issues inside data."""
    fake_issue = MagicMock()
    mock_result_list = MagicMock(
        nextPageToken=None,
        isLast=True,
    )
    mock_result_list.__iter__ = lambda self: iter([fake_issue])
    toolkit.jira.enhanced_search_issues.return_value = mock_result_list
    toolkit._issue_to_dict = lambda obj: {"key": "NAV-1"}

    result = await toolkit.jira_search_issues("project = NAV")
    assert result["status"] == "ok"
    assert len(result["data"]["issues"]) == 1


@pytest.mark.asyncio
async def test_search_issues_error_returns_envelope(toolkit):
    """Unexpected exception in search → status='error'."""
    toolkit.jira.enhanced_search_issues.side_effect = RuntimeError("boom")

    result = await toolkit.jira_search_issues("project = X")
    assert result["status"] == "error"
    assert result["data"] is None
    assert "boom" in result["message"]


# ---------------------------------------------------------------------------
# JiraToolEnvelope is exported
# ---------------------------------------------------------------------------

def test_jiratoolenvelope_is_exported():
    """JiraToolEnvelope must be importable from parrot_tools.jiratoolkit."""
    from parrot_tools.jiratoolkit import JiraToolEnvelope
    assert JiraToolEnvelope is not None
