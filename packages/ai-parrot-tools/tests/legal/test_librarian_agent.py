"""Unit tests for LegalLibrarianAgent configuration (FEAT-449 TASK-2497)."""

from datetime import date
from unittest.mock import AsyncMock

from parrot_tools.legal.librarian.agent import (
    LIBRARIAN_SYSTEM_PROMPT,
    LegalLibrarianAgent,
)
from parrot_tools.legal.librarian.models import DraftAnswer


def test_agent_has_no_write_tools():
    agent = LegalLibrarianAgent()
    assert agent.agent_tools() == []


def test_agent_r2_invariant_in_class_docstring():
    assert "no encontré" in (LegalLibrarianAgent.__doc__ or "")


def test_agent_system_prompt_forbids_offsets_and_unlisted_keys():
    assert "payload_key" in LIBRARIAN_SYSTEM_PROMPT
    assert "offset" in LIBRARIAN_SYSTEM_PROMPT.lower()


def test_agent_low_temperature():
    assert LegalLibrarianAgent.temperature <= 0.2


def test_agent_uses_custom_system_prompt():
    agent = LegalLibrarianAgent()
    assert agent.system_prompt_template == LIBRARIAN_SYSTEM_PROMPT


async def test_draft_is_stateless_no_conversation_history():
    """draft() must never rely on/persist conversation history — R1 (stateless turns)."""
    agent = LegalLibrarianAgent()
    canned = DraftAnswer(reading_order=[], conflicts=[], reading_guide=[], not_found=[])
    response = type("Resp", (), {"structured_output": canned})()
    agent.ask = AsyncMock(return_value=response)

    result = await agent.draft("### payload_key: a:0\n...", "query", date(2024, 1, 1))

    assert result is canned
    _, kwargs = agent.ask.call_args
    assert kwargs["use_conversation_history"] is False
    assert kwargs["structured_output"] is DraftAnswer
