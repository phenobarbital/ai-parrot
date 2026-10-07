"""FEAT-637 TASK-4116 — jira_list_templates."""

from pathlib import Path
from typing import Any
from unittest.mock import patch

import pytest

from parrot_tools.jiratoolkit import JiraToolkit


class _FakeJIRA:
    """Minimal JIRA replacement used during toolkit construction."""

    def __init__(self, *args: Any, **kwargs: Any) -> None:
        """Accept the constructor parameters passed by JiraToolkit."""


@pytest.fixture(autouse=True)
def _clean_env(monkeypatch: pytest.MonkeyPatch) -> None:
    """Prevent environment and navconfig from affecting template tests."""
    for var in ("JIRA_INSTANCE", "JIRA_AUTH_TYPE", "JIRA_TEMPLATES_DIR"):
        monkeypatch.delenv(var, raising=False)
    monkeypatch.setattr("parrot_tools.jiratoolkit.nav_config", None, raising=False)


def _make(**kwargs: Any) -> JiraToolkit:
    """Build a JiraToolkit without network credentials verification."""
    with patch("parrot_tools.jiratoolkit.JIRA", _FakeJIRA):
        return JiraToolkit(
            auth_type="token_auth",
            server_url="https://x.atlassian.net",
            token="t",
            verify_credentials=False,
            **kwargs,
        )


@pytest.mark.asyncio
async def test_list_templates_names_only(tmp_path: Path) -> None:
    """Return sorted logical Jinja template names, never paths or source text."""
    nav_dir = tmp_path / "nav"
    nav_dir.mkdir()
    (nav_dir / "bug.j2").write_text("filesystem template", encoding="utf-8")
    (tmp_path / "notes.txt").write_text("not a template", encoding="utf-8")
    tk = _make(templates_dir=tmp_path, templates={"_default.j2": "inline template"})

    result = await tk.jira_list_templates()

    assert result["templates"] == ["_default.j2", "nav/bug.j2"]
    assert str(tmp_path) not in result["templates"]
    assert "inline template" not in result["templates"]
    assert "filesystem template" not in result["templates"]


@pytest.mark.asyncio
async def test_list_templates_project_filter(tmp_path: Path) -> None:
    """Filter templates to the supplied lower-cased project prefix."""
    nav_dir = tmp_path / "nav"
    nav_dir.mkdir()
    (nav_dir / "bug.j2").write_text("filesystem template", encoding="utf-8")
    tk = _make(templates_dir=tmp_path, templates={"_default.j2": "inline template"})

    result = await tk.jira_list_templates(project="NAV")

    assert result["templates"] == ["nav/bug.j2"]


@pytest.mark.asyncio
async def test_list_templates_without_engine() -> None:
    """Return an empty list when no template loader is configured."""
    result = await _make().jira_list_templates()

    assert result["templates"] == []
    assert result["templates_dir"] is None


def test_list_templates_is_unrestricted_read() -> None:
    """Leave the template-listing method without a write permission requirement."""
    permissions = getattr(JiraToolkit.jira_list_templates, "_required_permissions", frozenset())

    assert permissions == frozenset()


def test_list_templates_registered_as_tool() -> None:
    """Register jira_list_templates through AbstractToolkit method discovery."""
    tk = _make()

    assert "jira_list_templates" in tk.list_tool_names()
