"""Unit tests for JiraToolkit parity tools (FEAT-696 M1)."""

from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from parrot_tools.jira_kb import JiraKnowledgeBase
from parrot_tools.jiratoolkit import JiraToolkit


class _FakeJIRA:
    """Accept JiraToolkit construction without a network request."""

    def __init__(self, *args, **kwargs) -> None:
        """Store no state because tests replace the client after construction."""


def _toolkit(*, knowledge_base=None, **kwargs) -> JiraToolkit:
    """Build a toolkit using a mocked synchronous Jira client."""
    with patch("parrot_tools.jiratoolkit.JIRA", _FakeJIRA):
        toolkit = JiraToolkit(
            auth_type="token_auth",
            server_url="https://acme.atlassian.net",
            token="token",
            verify_credentials=False,
            knowledge_base=knowledge_base,
            **kwargs,
        )
    toolkit.jira = MagicMock()
    toolkit._issue_to_dict = MagicMock(return_value={"id": "1", "body": "updated"})
    return toolkit


@pytest.mark.asyncio
async def test_link_tools_call_jira_with_expected_arguments() -> None:
    """Link creation and link type lookup delegate to their jira client methods."""
    toolkit = _toolkit()
    toolkit.jira.issue_link_types.return_value = [
        SimpleNamespace(id="10", name="Blocks", inward="is blocked by", outward="blocks")
    ]

    result = await toolkit.jira_create_issue_link("NAV-1", "NAV-2", "Blocks", "context")
    types = await toolkit.jira_get_link_types()

    assert result["ok"] is True
    toolkit.jira.create_issue_link.assert_called_once_with("Blocks", "NAV-1", "NAV-2", comment="context")
    assert types == [{"id": "10", "name": "Blocks", "inward": "is blocked by", "outward": "blocks"}]


def test_parity_methods_are_registered_tools() -> None:
    """All M1 methods appear in the toolkit's generated tool collection."""
    toolkit = _toolkit()
    names = {tool.name for tool in toolkit.get_tools()}
    assert {
        "jira_create_issue_link",
        "jira_get_link_types",
        "jira_get_create_fields",
        "jira_edit_comment",
        "jira_get_accessible_resources",
    } <= names


@pytest.mark.asyncio
async def test_create_fields_uses_kb_issue_type_id() -> None:
    """Known KB issue types avoid a live issue-type lookup before field metadata."""
    kb = JiraKnowledgeBase.model_validate(
        {"site": "https://acme.atlassian.net", "projects": {"NAV": {"name": "Nav", "issue_types": {"Story": {"id": "10001"}}}}}
    )
    toolkit = _toolkit(knowledge_base=kb)
    toolkit.jira.project_issue_fields.return_value = [SimpleNamespace(raw={"id": "summary", "required": True})]

    result = await toolkit.jira_get_create_fields("Story", "NAV")

    toolkit.jira.project_issue_fields.assert_called_once_with("NAV", "10001")
    toolkit.jira.project.assert_not_called()
    assert result["fields"] == [{"id": "summary", "required": True}]
    assert result["source"] == "kb"


@pytest.mark.asyncio
async def test_edit_comment_renders_template_then_updates_comment() -> None:
    """Comment edits reuse the established comment template renderer."""
    toolkit = _toolkit(templates={"comment.j2": "note: {{ body }}"})
    comment = MagicMock()
    toolkit.jira.comment.return_value = comment

    result = await toolkit.jira_edit_comment("NAV-1", "42", body="hello")

    toolkit.jira.comment.assert_called_once_with("NAV-1", "42")
    comment.update.assert_called_once_with(body="note: hello")
    assert result["ok"] is True


@pytest.mark.asyncio
async def test_accessible_resources_static_kb_and_tenant_failure() -> None:
    """Static clients use the KB and tenant lookup failures are non-fatal."""
    kb = JiraKnowledgeBase.model_validate(
        {"site": "https://acme.atlassian.net", "cloud_id": "cloud-1"}
    )
    kb_toolkit = _toolkit(knowledge_base=kb)
    assert await kb_toolkit.jira_get_accessible_resources() == {
        "cloud_id": "cloud-1",
        "site_url": "https://acme.atlassian.net",
        "sites": [{"id": "cloud-1", "url": "https://acme.atlassian.net"}],
        "source": "kb",
    }

    toolkit = _toolkit()
    toolkit.jira._session.get.side_effect = RuntimeError("tenant endpoint unavailable")
    result = await toolkit.jira_get_accessible_resources()
    assert result["source"] == "unavailable"
    assert result["cloud_id"] is None


@pytest.mark.asyncio
async def test_accessible_resources_oauth_uses_helper() -> None:
    """Bearer-auth clients delegate cloud discovery to the OAuth helper."""
    toolkit = _toolkit()
    toolkit.jira._options = {"headers": {"Authorization": "Bearer access-token"}}
    sites = [{"id": "cloud-1", "url": "https://acme.atlassian.net"}]
    with patch("parrot_tools.jiratoolkit.fetch_accessible_resources", new=AsyncMock(return_value=sites)) as helper:
        result = await toolkit.jira_get_accessible_resources()

    helper.assert_awaited_once()
    assert result == {
        "cloud_id": "cloud-1",
        "site_url": "https://acme.atlassian.net",
        "sites": sites,
        "source": "oauth2_3lo",
    }
