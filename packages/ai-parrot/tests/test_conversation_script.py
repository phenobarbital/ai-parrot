"""Tests for GoogleGeneration.create_conversation_script().

Covers the interviewer/interviewee validation relaxation added for
single-narrator (monologue) podcast scripts: the two-role requirement only
applies to the auto-generated two-person template, not when the caller
supplies its own system_instruction.
"""
from unittest.mock import AsyncMock, MagicMock, patch
import pytest
from parrot.clients.google.generation import GoogleGeneration
from parrot.models.google import ConversationalScriptConfig, FictionalSpeaker


@pytest.fixture
def mock_generation():
    gg = GoogleGeneration()
    gg.client = MagicMock()
    gg.logger = MagicMock()
    gg.temperature = 0.7
    gg.max_tokens = None
    gg._ensure_client = AsyncMock()
    mock_response = MagicMock()
    mock_response.text = "Generated script text"
    gg.client.models.generate_content = MagicMock(return_value=mock_response)
    return gg


def _patch_ai_message_factory():
    return patch(
        "parrot.clients.google.generation.AIMessageFactory.from_gemini",
        return_value=MagicMock(),
    )


@pytest.mark.asyncio
async def test_single_speaker_with_custom_instruction_skips_role_validation(mock_generation):
    """A lone 'interviewer' speaker + a custom system_instruction must NOT raise,
    and the custom instruction must be used verbatim (not the two-person template).
    """
    narrator = FictionalSpeaker(
        name="Alex", role="interviewer", characteristic="upbeat", gender="female"
    )
    config = ConversationalScriptConfig(
        report_text="Store feedback summary.",
        speakers=[narrator],
        context="store briefing",
        system_instruction="Custom monologue instructions.",
    )

    with _patch_ai_message_factory():
        await mock_generation.create_conversation_script(
            report_data=config, use_structured_output=False
        )

    _, kwargs = mock_generation.client.models.generate_content.call_args
    assert kwargs["config"].system_instruction == "Custom monologue instructions."


@pytest.mark.asyncio
async def test_single_speaker_without_custom_instruction_still_raises(mock_generation):
    """Without a caller-supplied system_instruction, the default two-person
    template still requires both an interviewer and an interviewee.
    """
    narrator = FictionalSpeaker(
        name="Alex", role="interviewer", characteristic="upbeat", gender="female"
    )
    config = ConversationalScriptConfig(
        report_text="Store feedback summary.",
        speakers=[narrator],
        context="store briefing",
    )

    with pytest.raises(ValueError, match="interviewer and one interviewee"):
        await mock_generation.create_conversation_script(
            report_data=config, use_structured_output=False
        )


@pytest.mark.asyncio
async def test_two_speakers_without_custom_instruction_uses_default_template(mock_generation):
    """Backward compatibility: two properly-roled speakers with no custom
    system_instruction still builds the default conversational template.
    """
    interviewer = FictionalSpeaker(
        name="Alex", role="interviewer", characteristic="curious", gender="male"
    )
    interviewee = FictionalSpeaker(
        name="Jordan", role="interviewee", characteristic="warm", gender="female"
    )
    config = ConversationalScriptConfig(
        report_text="Store feedback summary.",
        speakers=[interviewer, interviewee],
        context="store briefing",
    )

    with _patch_ai_message_factory():
        await mock_generation.create_conversation_script(
            report_data=config, use_structured_output=False
        )

    _, kwargs = mock_generation.client.models.generate_content.call_args
    system_instruction = kwargs["config"].system_instruction
    assert "Alex" in system_instruction and "Jordan" in system_instruction
