"""FEAT-637 TASK-4115 — templates on create / update / comment."""

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from parrot_tools.jiratoolkit import JiraTemplateError, JiraToolkit


class _FakeJIRA:
    def __init__(self, *args, **kwargs) -> None:
        """Accept toolkit constructor arguments without network activity."""


@pytest.fixture(autouse=True)
def _clean_env(monkeypatch) -> None:
    """Prevent environment and navconfig from influencing toolkit construction."""
    for var in (
        "JIRA_INSTANCE",
        "JIRA_AUTH_TYPE",
        "JIRA_TEMPLATES_DIR",
        "JIRA_DEFAULT_LABELS",
        "JIRA_DEFAULT_COMPONENTS",
        "JIRA_DEFAULT_DUE_DATE_OFFSET",
        "JIRA_DEFAULT_ESTIMATE",
    ):
        monkeypatch.delenv(var, raising=False)
    monkeypatch.setattr("parrot_tools.jiratoolkit.nav_config", None, raising=False)


def _make(**kwargs) -> JiraToolkit:
    """Build an authenticated-in-shape toolkit with a mocked Jira client."""
    with patch("parrot_tools.jiratoolkit.JIRA", _FakeJIRA):
        tk = JiraToolkit(
            auth_type="token_auth",
            server_url="https://x.atlassian.net",
            token="t",
            verify_credentials=False,
            **kwargs,
        )
    tk.jira = MagicMock()
    tk._validate_issue_type = AsyncMock(side_effect=lambda project, issue_type: issue_type)
    tk._issue_to_dict = MagicMock(return_value={"id": "1", "key": "NAV-1"})
    return tk


@pytest.mark.asyncio
async def test_no_templates_payload_unchanged() -> None:
    """Create payload remains byte-for-byte identical without templates."""
    tk = _make()

    await tk.jira_create_issue(project="NAV", summary="S", issuetype="Task", description="D")

    tk.jira.create_issue.assert_called_once_with(
        fields={"project": {"key": "NAV"}, "summary": "S", "issuetype": {"name": "Task"}, "description": "D"}
    )


@pytest.mark.asyncio
async def test_create_renders_convention_template() -> None:
    """Create convention templates receive the canonical issue type context."""
    tk = _make(templates={"nav/bug.j2": "h2. Bug\n{{ description }}"})

    await tk.jira_create_issue(project="NAV", summary="S", issuetype="Bug", description="D")

    assert tk.jira.create_issue.call_args.kwargs["fields"]["description"] == "h2. Bug\nD"


@pytest.mark.asyncio
async def test_fields_description_conflict_raises() -> None:
    """Rendered descriptions cannot be silently overwritten by generic fields."""
    tk = _make(templates={"t.j2": "rendered"})

    with pytest.raises(JiraTemplateError, match="conflicts"):
        await tk.jira_create_issue(project="NAV", summary="S", template="t", fields={"description": "override"})
    with pytest.raises(JiraTemplateError, match="conflicts"):
        await tk.jira_update_issue("NAV-1", template="t", fields={"description": "override"})

    tk.jira.create_issue.assert_not_called()
    tk.jira.issue.assert_not_called()


@pytest.mark.asyncio
async def test_fields_description_without_template_passthrough() -> None:
    """Generic description updates remain valid when no template applies."""
    tk = _make()

    await tk.jira_create_issue(project="NAV", summary="S", fields={"description": "override"})
    await tk.jira_update_issue("NAV-1", fields={"description": "override"})

    assert tk.jira.create_issue.call_args.kwargs["fields"]["description"] == "override"
    tk.jira.issue.return_value.update.assert_called_once_with(fields={"description": "override"})


@pytest.mark.asyncio
async def test_update_renders_before_update_fields() -> None:
    """Update writes the rendered description through the standard fields block."""
    tk = _make(templates={"update.j2": "updated {{ description }}"})

    await tk.jira_update_issue("NAV-1", description="D")

    tk.jira.issue.return_value.update.assert_called_once_with(fields={"description": "updated D"})


@pytest.mark.asyncio
async def test_update_ticket_alias_forwards_template_kwargs() -> None:
    """The update-ticket alias passes template kwargs to the write path."""
    tk = _make(templates={"update.j2": "updated {{ summary }}"})

    await tk.jira_update_ticket(issue="NAV-1", summary="S", template="update", template_params={})

    assert tk.jira.issue.return_value.update.call_args.kwargs["fields"]["description"] == "updated S"


@pytest.mark.asyncio
async def test_comment_template_only_body_optional() -> None:
    """A comment can derive its entire body from a convention template."""
    tk = _make(templates={"comment.j2": "(bot) {{ issue }}"})

    await tk.jira_add_comment("NAV-1", body=None)

    tk.jira.add_comment.assert_called_once_with("NAV-1", "(bot) NAV-1", is_internal=False)


@pytest.mark.asyncio
async def test_comment_without_body_or_template_raises() -> None:
    """Blank comment input fails before the Jira transport is called."""
    tk = _make()

    with pytest.raises(ValueError, match="body is required"):
        await tk.jira_add_comment("NAV-1")

    tk.jira.add_comment.assert_not_called()


@pytest.mark.asyncio
async def test_comment_body_wrapped_by_template() -> None:
    """Comment templates receive the supplied body in their context."""
    tk = _make(templates={"comment.j2": "(bot) {{ body }}"})

    await tk.jira_add_comment("NAV-1", body="hello")

    tk.jira.add_comment.assert_called_once_with("NAV-1", "(bot) hello", is_internal=False)


@pytest.mark.asyncio
async def test_missing_variables_no_transport() -> None:
    """Template validation errors occur before create_issue reaches Jira."""
    tk = _make(templates={"t.j2": "{{ missing }}"})

    with pytest.raises(JiraTemplateError, match="missing variables: missing"):
        await tk.jira_create_issue(project="NAV", summary="S", template="t")

    tk.jira.create_issue.assert_not_called()
