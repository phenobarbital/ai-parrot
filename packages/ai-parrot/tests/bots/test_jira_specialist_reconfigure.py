"""FEAT-721 — JiraSpecialist.post_configure() is re-entrant."""

from unittest.mock import MagicMock

import pytest

from parrot.bots.jira_specialist import JiraSpecialist
from parrot.tools.manager import ToolManager
from parrot_tools.jiratoolkit import JiraToolkit


async def test_jira_specialist_post_configure_twice_adopts(monkeypatch: pytest.MonkeyPatch) -> None:
    """Adopt the original Jira and Reminder toolkits on repeat configuration."""
    monkeypatch.delenv("JIRA_AUTH_TYPE", raising=False)
    toolkit = JiraToolkit(verify_credentials=False)
    configure_jira = MagicMock(side_effect=[toolkit])
    agent = JiraSpecialist.__new__(JiraSpecialist)
    agent.logger = MagicMock()
    agent.tool_manager = ToolManager(include_search_tool=False)
    agent.tools = []
    agent._llm = None
    agent.app = {"scheduler_manager": MagicMock()}
    monkeypatch.setattr(agent, "_configure_jira", configure_jira)

    await agent.post_configure()
    first_reminder_names = [name for name in agent.tool_manager.list_tools() if name.startswith("reminder_")]
    await agent.post_configure()

    reminder_names = [name for name in agent.tool_manager.list_tools() if name.startswith("reminder_")]
    tool_names = [tool.name for tool in agent.tools]
    assert configure_jira.call_count == 1
    assert reminder_names == first_reminder_names
    assert len(tool_names) == len(set(tool_names))
    assert agent.jira_toolkit is agent.tool_manager.find_registered_toolkit(type(agent.jira_toolkit))
    agent.logger.error.assert_not_called()
