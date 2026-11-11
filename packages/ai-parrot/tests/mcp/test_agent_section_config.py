"""FEAT-877 Module 2 — agent-section naming and recognition."""

from __future__ import annotations

import pytest

from parrot.mcp.toolkit_config import (
    AGENT_SECTION_PREFIX,
    AGENT_TOOLKIT_CLASS_PATH,
    MCPToolkitsConfig,
    ToolkitSection,
    agent_section_name,
    is_agent_section,
)


@pytest.mark.parametrize(
    ("name", "expected"),
    [
        ("Finance Bot", "agent-finance-bot"),
        ("finance", "agent-finance"),
        ("  __Finance__Bot!!  ", "agent-finance-bot"),
        ("HR.Assistant-v2", "agent-hr-assistant-v2"),
    ],
)
def test_agent_section_name_slug(name: str, expected: str) -> None:
    assert agent_section_name(name) == expected
    assert agent_section_name(name).startswith(AGENT_SECTION_PREFIX)


@pytest.mark.parametrize("name", ["", "   ", "!!!", "ñ"])
def test_agent_section_name_empty_slug_raises(name: str) -> None:
    with pytest.raises(ValueError, match="has no slug characters"):
        agent_section_name(name)


def test_is_agent_section() -> None:
    agent_section = ToolkitSection(**{"class": AGENT_TOOLKIT_CLASS_PATH, "kwargs": {}})
    packaged_section = ToolkitSection(**{"class": "parrot_tools.example.ExampleToolkit", "kwargs": {}})
    named_agent_config = MCPToolkitsConfig(toolkits={"agent-x": packaged_section})

    assert is_agent_section(agent_section) is True
    assert is_agent_section(packaged_section) is False
    assert is_agent_section(named_agent_config.toolkits["agent-x"]) is False
