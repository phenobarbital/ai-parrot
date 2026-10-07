"""FEAT-637 TASK-4114 — Jira template render-helper behaviour."""

import logging
from unittest.mock import patch

import pytest

from parrot_tools.jiratoolkit import (
    _MAX_JIRA_TEXT_CHARS,
    _TRUNCATION_MARKER,
    JiraTemplateError,
    JiraTemplateNotFound,
    JiraToolkit,
)


class _FakeJIRA:
    """Minimal JIRA replacement used during toolkit construction."""

    def __init__(self, *args, **kwargs) -> None:
        """Accept the toolkit's constructor arguments without network activity."""


@pytest.fixture(autouse=True)
def _clean_env(monkeypatch) -> None:
    """Prevent environment and navconfig from influencing toolkit construction."""
    for var in ("JIRA_INSTANCE", "JIRA_AUTH_TYPE", "JIRA_TEMPLATES_DIR"):
        monkeypatch.delenv(var, raising=False)
    monkeypatch.setattr("parrot_tools.jiratoolkit.nav_config", None, raising=False)


def _make(**kwargs) -> JiraToolkit:
    """Build an authenticated-in-shape toolkit without a network client."""
    with patch("parrot_tools.jiratoolkit.JIRA", _FakeJIRA):
        return JiraToolkit(
            auth_type="token_auth",
            server_url="https://x.atlassian.net",
            token="t",
            verify_credentials=False,
            **kwargs,
        )


@pytest.mark.asyncio
async def test_no_engine_passthrough() -> None:
    """No configured engine preserves raw text byte-for-byte."""
    tk = _make()

    out = await tk._render_jira_text(
        "create", text="raw", template=None, template_params=None, call_fields={}, project="NAV", issuetype="Bug"
    )

    assert out == "raw"


@pytest.mark.asyncio
@pytest.mark.parametrize("template", ["nav/bug", "nav/bug.j2"])
async def test_explicit_template_with_and_without_suffix(template: str) -> None:
    """Explicit template lookup accepts the optional Jinja suffix."""
    tk = _make(templates={"nav/bug.j2": "{{ summary }}"})

    out = await tk._render_jira_text(
        "create",
        text=None,
        template=template,
        template_params=None,
        call_fields={"summary": "Rendered"},
        project="NAV",
        issuetype="Bug",
    )

    assert out == "Rendered"


@pytest.mark.asyncio
async def test_explicit_template_missing_raises_not_found() -> None:
    """An unknown explicit template reports the dedicated exception."""
    tk = _make(templates={"known.j2": "known"})

    with pytest.raises(JiraTemplateNotFound):
        await tk._render_jira_text(
            "create", text=None, template="missing", template_params=None, call_fields={}, project="NAV"
        )


@pytest.mark.asyncio
async def test_explicit_template_without_engine_raises() -> None:
    """An explicit template cannot be fulfilled without configured templates."""
    tk = _make()

    with pytest.raises(JiraTemplateError, match="no Jira templates are configured"):
        await tk._render_jira_text(
            "create", text="raw", template="bug", template_params=None, call_fields={}, project="NAV"
        )


@pytest.mark.parametrize("name", ["../x", "/etc/x", "a\\b"])
def test_name_traversal_rejected(name: str) -> None:
    """Traversal-shaped explicit names are rejected before loader access."""
    with pytest.raises(JiraTemplateError):
        JiraToolkit._validate_template_name(name)


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("templates", "expected"),
    [
        ({"nav/bug.j2": "issue type"}, "issue type"),
        ({"nav/_default.j2": "project default"}, "project default"),
        ({"_default.j2": "global default"}, "global default"),
    ],
)
async def test_convention_create_order(templates: dict[str, str], expected: str) -> None:
    """Create convention selects the first matching lower-cased candidate."""
    tk = _make(templates=templates)

    out = await tk._render_jira_text(
        "create", text="raw", template=None, template_params=None, call_fields={}, project="NAV", issuetype="BUG"
    )

    assert out == expected


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("kind", "templates", "expected"),
    [
        ("comment", {"comment.j2": "comment"}, "comment"),
        ("comment", {"nav/comment.j2": "project comment"}, "project comment"),
        ("update", {"update.j2": "update"}, "update"),
        ("update", {"nav/update.j2": "project update"}, "project update"),
    ],
)
async def test_convention_comment_and_update_kinds(kind: str, templates: dict[str, str], expected: str) -> None:
    """Comment and update convention lookups prefer project-local templates."""
    tk = _make(templates=templates)

    out = await tk._render_jira_text(
        kind, text="raw", template=None, template_params=None, call_fields={}, project="NAV"
    )

    assert out == expected


@pytest.mark.asyncio
async def test_no_candidate_passthrough() -> None:
    """No convention match preserves the supplied raw text."""
    tk = _make(templates={"unrelated.j2": "unrelated"})

    out = await tk._render_jira_text(
        "create", text="raw", template=None, template_params=None, call_fields={}, project="NAV", issuetype="Bug"
    )

    assert out == "raw"


@pytest.mark.asyncio
async def test_context_params_win() -> None:
    """Caller template parameters override frozen call fields."""
    tk = _make(templates={"t.j2": "{{ summary }} {{ priority }}"})

    out = await tk._render_jira_text(
        "create",
        text=None,
        template="t",
        template_params={"summary": "override"},
        call_fields={"summary": "call field", "priority": "high"},
        project="NAV",
    )

    assert out == "override high"


@pytest.mark.asyncio
async def test_missing_variables_named() -> None:
    """Strict pre-render validation names every missing variable in sorted order."""
    tk = _make(templates={"t.j2": "{{ b }} {{ a }} {{ present }}"})

    with pytest.raises(JiraTemplateError, match=r"missing variables: a, b"):
        await tk._render_jira_text(
            "create", text=None, template="t", template_params=None, call_fields={"present": "yes"}, project="NAV"
        )


@pytest.mark.asyncio
async def test_empty_render_raises() -> None:
    """Whitespace-only template output is rejected."""
    tk = _make(templates={"t.j2": "  \n\t"})

    with pytest.raises(JiraTemplateError, match="rendered empty Jira text"):
        await tk._render_jira_text(
            "create", text=None, template="t", template_params=None, call_fields={}, project="NAV"
        )


@pytest.mark.asyncio
async def test_length_guard_truncates_with_marker(caplog) -> None:
    """Rendered Jira text is capped with the truncation marker inside the limit."""
    tk = _make(templates={"t.j2": "x" * (_MAX_JIRA_TEXT_CHARS + 1)})

    with caplog.at_level(logging.WARNING):
        out = await tk._render_jira_text(
            "comment", text=None, template="t", template_params=None, call_fields={}, project="NAV"
        )

    assert out is not None
    assert len(out) == _MAX_JIRA_TEXT_CHARS
    assert out.endswith(_TRUNCATION_MARKER)
    assert "truncating" in caplog.text
