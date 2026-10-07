"""FEAT-637 TASK-4113 — template configuration and lazy engine."""

import logging
from pathlib import Path
from unittest.mock import patch

import pytest

from parrot_tools.jiratoolkit import JiraTemplateError, JiraTemplateNotFound, JiraToolkit


class _FakeJIRA:
    """Minimal JIRA replacement used during toolkit construction."""

    def __init__(self, *args, **kwargs) -> None:
        self.args = args
        self.kwargs = kwargs


@pytest.fixture(autouse=True)
def _clean_env(monkeypatch) -> None:
    """Prevent environment and navconfig from influencing template configuration."""
    for var in ("JIRA_INSTANCE", "JIRA_AUTH_TYPE", "JIRA_TEMPLATES_DIR", "JIRA_DEFAULT_PROJECT"):
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


def test_engine_is_lazy_and_none_without_config() -> None:
    """No configured template source leaves the engine absent."""
    tk = _make()

    assert tk._template_engine is None
    assert tk._get_template_engine() is None


def test_missing_templates_dir_warns_and_drops(caplog, tmp_path: Path) -> None:
    """A configured non-directory is ignored without breaking construction."""
    missing_dir = tmp_path / "missing"

    with caplog.at_level(logging.WARNING):
        tk = _make(templates_dir=missing_dir)

    assert tk.templates_dir is None
    assert "is not a directory; ignoring it" in caplog.text


def test_env_var_used_and_kwarg_wins_over_env(monkeypatch, tmp_path: Path) -> None:
    """The explicit templates directory wins over the environment setting."""
    env_dir = tmp_path / "from-env"
    kwarg_dir = tmp_path / "from-kwarg"
    env_dir.mkdir()
    kwarg_dir.mkdir()
    monkeypatch.setenv("JIRA_TEMPLATES_DIR", str(env_dir))

    assert _make().templates_dir == env_dir.resolve()
    assert _make(templates_dir=kwarg_dir).templates_dir == kwarg_dir.resolve()


@pytest.mark.asyncio
async def test_autoescape_disabled() -> None:
    """Jira wiki markup and HTML-like content render verbatim."""
    tk = _make(templates={"t.j2": "{code}{{ x }}{code} <b>"})
    engine = tk._get_template_engine()

    assert engine is not None
    assert await engine.render("t.j2", {"x": "<i>"}) == "{code}<i>{code} <b>"


@pytest.mark.asyncio
async def test_inline_templates_shadow_filesystem(tmp_path: Path) -> None:
    """Inline templates take precedence over a same-named filesystem file."""
    template_path = tmp_path / "t.j2"
    template_path.write_text("filesystem", encoding="utf-8")
    tk = _make(templates_dir=tmp_path, templates={"t.j2": "inline"})
    engine = tk._get_template_engine()

    assert engine is not None
    assert await engine.render("t.j2") == "inline"


def test_engine_cached() -> None:
    """Configured template engines are created only once."""
    tk = _make(templates={"t.j2": "inline"})

    assert tk._get_template_engine() is tk._get_template_engine()


def test_error_hierarchy() -> None:
    """Public template exceptions retain the prescribed inheritance."""
    assert issubclass(JiraTemplateNotFound, JiraTemplateError)
    assert issubclass(JiraTemplateError, ValueError)
