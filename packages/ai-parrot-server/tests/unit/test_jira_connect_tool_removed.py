"""FEAT-777 M6: the FEAT-083 hot-swap placeholder is gone."""

import importlib

import pytest

from parrot.handlers.agent import AgentTalk


def test_jira_connect_tool_removed() -> None:
    """The module is not importable and AgentTalk no longer bootstraps it."""
    with pytest.raises(ModuleNotFoundError):
        importlib.import_module("parrot.tools.jira_connect_tool")
    assert not hasattr(AgentTalk, "_bootstrap_jira_oauth_session")
