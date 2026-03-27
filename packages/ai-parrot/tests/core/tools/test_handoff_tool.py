# -*- coding: utf-8 -*-
"""Tests for the HandoffTool."""

import pytest
from parrot.core.tools.handoff import HandoffTool
from parrot.core.exceptions import HumanInteractionInterrupt


def test_handoff_tool_raises_interrupt():
    """Test that the synchronous execution of the HandoffTool raises an interrupt."""
    tool = HandoffTool()
    prompt_msg = "Please provide your project ID."
    
    with pytest.raises(HumanInteractionInterrupt) as exc_info:
        tool._execute(prompt=prompt_msg)
    
    # Assert that the prompt is contained within the exception message/str
    assert prompt_msg in str(exc_info.value)
    # Also assert that the prompt attribute is set directly
    assert exc_info.value.prompt == prompt_msg


@pytest.mark.asyncio
async def test_handoff_tool_arun_raises_interrupt():
    """Test that the asynchronous execution of the HandoffTool raises an interrupt."""
    tool = HandoffTool()
    prompt_msg = "Please select the environment for deployment."
    
    with pytest.raises(HumanInteractionInterrupt) as exc_info:
        await tool._aexecute(prompt=prompt_msg)
    
    assert prompt_msg in str(exc_info.value)
    assert exc_info.value.prompt == prompt_msg

