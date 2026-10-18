"""KB integration tests for JiraToolkit (FEAT-696 M6)."""

from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from parrot_tools.jira_kb import JiraKnowledgeBase
from parrot_tools.jiratoolkit import JiraToolkit


class _FakeJIRA:
    """Accept JiraToolkit construction without connecting to Jira."""

    def __init__(self, *args, **kwargs) -> None:
        """Accept toolkit client constructor parameters."""


def _toolkit(kb: JiraKnowledgeBase) -> JiraToolkit:
    """Build an authenticated-shape toolkit with a supplied KB."""
    with patch("parrot_tools.jiratoolkit.JIRA", _FakeJIRA):
        toolkit = JiraToolkit(
            auth_type="token_auth",
            server_url="https://acme.atlassian.net",
            token="token",
            verify_credentials=False,
            knowledge_base=kb,
        )
    toolkit.jira = MagicMock()
    toolkit._validate_issue_type = AsyncMock(side_effect=lambda project, issue_type: issue_type)
    toolkit._issue_to_dict = MagicMock(return_value={"id": "1", "key": "NAV-1"})
    return toolkit


def _kb() -> JiraKnowledgeBase:
    """Create a KB with fields, limits, and a single project."""
    return JiraKnowledgeBase.model_validate(
        {
            "site": "https://acme.atlassian.net",
            "projects": {"NAV": {"name": "Navigation", "issue_types": {"Story": {"id": "10001"}}}},
            "fields": {"team": "customfield_10001"},
            "limits": {"summary_max_chars": 4, "description_max_chars": 10},
            "components": ["Backend"],
        }
    )


@pytest.mark.asyncio
async def test_kb_resolves_fields_and_enforces_limits_before_create() -> None:
    """Aliased fields are resolved and oversized summaries never reach Jira."""
    toolkit = _toolkit(_kb())

    await toolkit.jira_create_issue(project="NAV", summary="okay", issuetype="Story", fields={"team": "core"})
    assert toolkit.jira.create_issue.call_args.kwargs["fields"]["customfield_10001"] == "core"

    with pytest.raises(ValueError, match="summary"):
        await toolkit.jira_create_issue(project="NAV", summary="oversized", issuetype="Story")
    assert toolkit.jira.create_issue.call_count == 1


@pytest.mark.asyncio
async def test_kb_miss_warns_and_falls_back_to_live_issue_types(caplog) -> None:
    """An unknown KB type keeps the live lookup path and logs stale cache evidence."""
    toolkit = _toolkit(_kb())
    toolkit.jira.project.return_value.issueTypes = [SimpleNamespace(id="10004", name="Bug", description="")]

    fields = await toolkit.jira_get_create_fields("Bug", "NAV")

    toolkit.jira.project.assert_called_once_with("NAV")
    assert fields["issue_type"] == "10004"
    assert "jira KB stale" in caplog.text


def test_site_mismatch_and_invalid_path_leave_kb_unset(tmp_path, caplog) -> None:
    """Invalid or different-site KBs never prevent toolkit construction."""
    mismatch = JiraKnowledgeBase.model_validate({"site": "https://other.atlassian.net"})
    assert _toolkit(mismatch)._kb is None

    bad_path = tmp_path / "missing.yaml"
    with patch("parrot_tools.jiratoolkit.JIRA", _FakeJIRA):
        toolkit = JiraToolkit(
            auth_type="token_auth",
            server_url="https://acme.atlassian.net",
            token="token",
            verify_credentials=False,
            knowledge_base=bad_path,
        )
    assert toolkit._kb is None
    assert "knowledge base" in caplog.text


@pytest.mark.asyncio
async def test_create_issue_with_known_type_performs_no_lookup() -> None:
    """AC7: a KB-known issue type is accepted without any Jira issue-type/project lookup."""
    toolkit = _toolkit(_kb())
    toolkit._validate_issue_type = JiraToolkit._validate_issue_type.__get__(toolkit)  # use the real one

    await toolkit.jira_create_issue(project="NAV", summary="ok", issuetype="story")

    toolkit.jira.project.assert_not_called()
    toolkit.jira.issue_types.assert_not_called()
    assert toolkit.jira.create_issue.call_args.kwargs["fields"]["issuetype"]["name"] == "Story"


@pytest.mark.asyncio
async def test_create_issue_with_unknown_type_goes_live_and_logs_stale(caplog) -> None:
    """AC7: an unknown type in a known project triggers one live lookup and logs the stale KB."""
    toolkit = _toolkit(_kb())
    toolkit._validate_issue_type = JiraToolkit._validate_issue_type.__get__(toolkit)
    toolkit.jira.project.return_value.issueTypes = [SimpleNamespace(id="10004", name="Bug", description="")]

    await toolkit.jira_create_issue(project="NAV", summary="ok", issuetype="Bug")

    toolkit.jira.project.assert_called_once_with("NAV")
    assert "jira KB stale" in caplog.text
    assert toolkit.jira.create_issue.call_args.kwargs["fields"]["issuetype"]["name"] == "Bug"
