"""Tests for JiraToolkitConfig + JiraToolkit.config_options (FEAT-593 TASK-3650)."""
from unittest.mock import AsyncMock, PropertyMock, patch

import pytest

from parrot_tools.jiratoolkit import JiraToolkit


def _make_toolkit() -> JiraToolkit:
    """A JiraToolkit with the underlying JIRA client mocked (no network)."""
    with patch("parrot_tools.jiratoolkit.JIRA"):
        return JiraToolkit(
            server_url="https://x.atlassian.net",
            auth_type="token_auth",
            token="pat",
        )


def test_schema_marks_secrets_and_options():
    schema = JiraToolkit.config_schema("jira")["schema"]
    props = schema["properties"]
    assert props["token"]["x-secret"] is True and props["password"]["x-secret"] is True
    assert props["default_project"]["x-options"] is True


@pytest.mark.asyncio
async def test_config_options_projects():
    kit = _make_toolkit()
    fake_interface = AsyncMock()
    fake_interface.list_projects = AsyncMock(return_value=[{"id": "1", "key": "TROC", "name": "Troc"}])
    # ``_read_interface`` is a read-only property on JiraToolkit, so it is
    # patched at the class level rather than assigned on the instance.
    with patch.object(JiraToolkit, "_read_interface", new_callable=PropertyMock) as mock_prop:
        mock_prop.return_value = fake_interface
        opts = await kit.config_options("default_project")
    assert opts[0].value == "TROC"
    assert opts[0].label == "TROC — Troc"


@pytest.mark.asyncio
async def test_other_param_not_implemented():
    kit = _make_toolkit()
    with pytest.raises(NotImplementedError):
        await kit.config_options("server_url")
