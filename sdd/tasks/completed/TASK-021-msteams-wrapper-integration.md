# TASK-021: MSTeamsAgentWrapper Voice Integration

**Feature**: MS Teams Voice Note Support
**Spec**: `sdd/specs/msteams-voice-support.spec.md`
**Status**: done
**Priority**: high
**Estimated effort**: L (4-8h)
**Depends-on**: TASK-020, TASK-022
**Assigned-to**: claude-session

---

## Context

This is the main integration task that adds voice note processing to `MSTeamsAgentWrapper`. When a user sends a voice note attachment in MS Teams, the wrapper will detect it, transcribe it, and process the transcribed text as the user's question.

Reference: Spec Section 3 "Module 6: MSTeamsAgentWrapper Integration"

---

## Scope

- Modify `MSTeamsAgentWrapper.on_message_activity()` to detect audio attachments
- Implement `_handle_voice_attachment()` method
- Download audio from MS Teams CDN using bot access token
- Use `VoiceTranscriber` to transcribe audio
- Show transcription to user (if configured) with 🎤 prefix
- Process transcribed text through normal agent flow
- Handle errors gracefully (show error card to user)
- Process only first audio attachment, warn if multiple
- Write integration tests with mocked attachments

**NOT in scope**:
- VoiceTranscriber implementation (TASK-020)
- Backend implementations (TASK-018, TASK-019)

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `parrot/integrations/msteams/wrapper.py` | MODIFY | Add voice attachment handling |
| `tests/integrations/msteams/test_voice_integration.py` | CREATE | Integration tests |

---

## Implementation Notes

### Pattern to Follow
```python
# In MSTeamsAgentWrapper class

# Add to __init__:
from .voice import VoiceTranscriber, VoiceTranscriberConfig

def __init__(self, ..., voice_config: Optional[VoiceTranscriberConfig] = None):
    # ... existing init ...

    # Voice transcription
    self._voice_config = voice_config or VoiceTranscriberConfig(enabled=False)
    self._voice_transcriber: Optional[VoiceTranscriber] = None
    if self._voice_config.enabled:
        self._voice_transcriber = VoiceTranscriber(self._voice_config)

# Modify on_message_activity:
async def on_message_activity(self, turn_context: TurnContext):
    """Handle incoming messages including voice notes."""

    # Check for audio attachments BEFORE text processing
    audio_attachment = self._find_audio_attachment(turn_context.activity)

    if audio_attachment and self._voice_config.enabled:
        await self._handle_voice_attachment(
            turn_context, audio_attachment
        )
        return

    # ... rest of existing text handling ...

# New helper methods:
AUDIO_CONTENT_TYPES = {
    "audio/ogg", "audio/mpeg", "audio/wav", "audio/x-wav",
    "audio/mp4", "audio/webm", "video/webm", "audio/m4a"
}

def _find_audio_attachment(self, activity) -> Optional[Attachment]:
    """Find first audio attachment in activity."""
    if not activity.attachments:
        return None

    for attachment in activity.attachments:
        content_type = attachment.content_type or ""
        if any(ct in content_type for ct in self.AUDIO_CONTENT_TYPES):
            return attachment

    return None

async def _handle_voice_attachment(
    self,
    turn_context: TurnContext,
    attachment: Attachment,
) -> None:
    """Process voice note attachment."""
    conversation_id = turn_context.activity.conversation.id

    # Check for multiple attachments
    audio_count = sum(
        1 for a in turn_context.activity.attachments
        if any(ct in (a.content_type or "") for ct in self.AUDIO_CONTENT_TYPES)
    )
    if audio_count > 1:
        self.logger.warning(f"Multiple audio attachments ({audio_count}), processing first only")

    # Send typing indicator
    await self.send_typing(turn_context)

    try:
        # Get bot access token for downloading
        token = await self._get_attachment_token(turn_context)

        # Transcribe
        result = await self._voice_transcriber.transcribe_url(
            url=attachment.content_url,
            auth_token=token,
        )

        transcribed_text = result.text.strip()

        if not transcribed_text:
            await self.send_text(
                "I couldn't understand the audio. Please try again or type your message.",
                turn_context
            )
            return

        # Show transcription to user
        if self._voice_config.show_transcription:
            await self.send_text(
                f"🎤 *\"{transcribed_text}\"*",
                turn_context
            )

        self.logger.info(
            f"Transcribed voice note ({result.duration_seconds:.1f}s): {transcribed_text[:50]}..."
        )

        # Process through normal flow
        await self._process_transcribed_message(
            turn_context,
            transcribed_text,
            conversation_id,
        )

    except ValueError as e:
        # Duration limit exceeded
        await self.send_text(
            f"Voice note too long. Please keep it under {self._voice_config.max_audio_duration_seconds} seconds.",
            turn_context
        )
    except Exception as e:
        self.logger.error(f"Voice transcription error: {e}", exc_info=True)
        await self.send_text(
            "Sorry, I couldn't process your voice note. Please try typing your message.",
            turn_context
        )

async def _get_attachment_token(self, turn_context: TurnContext) -> Optional[str]:
    """Get token for downloading attachments from MS Teams CDN."""
    # MS Teams attachments may need the bot's token
    # Try to get from connector client
    try:
        connector = turn_context.adapter.connector_client
        # Token may be in headers or need to be fetched
        # For now, return None - MS Teams public attachments may not need auth
        return None
    except Exception:
        return None

async def _process_transcribed_message(
    self,
    turn_context: TurnContext,
    text: str,
    conversation_id: str,
) -> None:
    """Process transcribed text through agent."""
    # Create dialog context
    dialog_context = await self.dialogs.create_context(turn_context)

    # Send typing indicator
    await self.send_typing(turn_context)

    # Process through form orchestrator (same as text messages)
    result = await self.form_orchestrator.process_message(
        message=text,
        conversation_id=conversation_id,
        context={
            "user_id": turn_context.activity.from_property.id,
            "session_id": conversation_id,
            "source": "voice_note",  # Mark source for analytics
        }
    )

    # Handle result (same as text flow)
    if result.has_error:
        await self.send_text(result.error, turn_context)
        return

    if result.needs_form:
        if result.context_message:
            await self.send_text(result.context_message, turn_context)
        await self._start_form_dialog(
            dialog_context, result.form, conversation_id, turn_context
        )
        return

    if result.raw_response is not None:
        parsed = self._parse_response(result.raw_response)
        await self._send_parsed_response(parsed, turn_context)
    elif result.response_text:
        await self.send_text(result.response_text, turn_context)
```

### Key Constraints
- Check for audio BEFORE text processing in `on_message_activity`
- Only process first audio attachment
- Show transcription with 🎤 prefix before response
- Mark source as "voice_note" in context for analytics
- Handle errors gracefully — never leave user without feedback
- Clean up resources on wrapper shutdown

### References in Codebase
- `parrot/integrations/msteams/wrapper.py` — existing implementation
- `parrot/integrations/msteams/models.py` — `MSTeamsAgentConfig`

---

## Acceptance Criteria

- [ ] Audio attachments detected in `on_message_activity`
- [ ] Voice notes are transcribed using `VoiceTranscriber`
- [ ] Transcription shown to user with 🎤 prefix (if enabled)
- [ ] Transcribed text processed through normal agent flow
- [ ] Only first audio attachment processed, warning logged for multiple
- [ ] Duration limit errors show friendly message
- [ ] Transcription errors show fallback message
- [ ] `voice_note` source marker in context
- [ ] All tests pass: `pytest tests/integrations/msteams/test_voice_integration.py -v`
- [ ] No regressions in existing text message handling

---

## Test Specification

```python
# tests/integrations/msteams/test_voice_integration.py
import pytest
from unittest.mock import AsyncMock, MagicMock, patch
from botbuilder.schema import Activity, Attachment, ChannelAccount, ConversationAccount
from parrot.integrations.msteams.wrapper import MSTeamsAgentWrapper
from parrot.integrations.msteams.voice.models import (
    VoiceTranscriberConfig,
    TranscriptionResult,
)


@pytest.fixture
def mock_agent():
    agent = MagicMock()
    agent.ask = AsyncMock(return_value=MagicMock(output="Test response"))
    return agent


@pytest.fixture
def voice_config():
    return VoiceTranscriberConfig(
        enabled=True,
        show_transcription=True,
        max_audio_duration_seconds=60,
    )


@pytest.fixture
def audio_activity():
    """Activity with voice note attachment."""
    return Activity(
        type="message",
        text="",
        from_property=ChannelAccount(id="user123"),
        conversation=ConversationAccount(id="conv123"),
        attachments=[
            Attachment(
                content_type="audio/ogg",
                content_url="https://teams.microsoft.com/files/voice.ogg",
                name="voice_note.ogg",
            )
        ],
    )


class TestVoiceIntegration:
    def test_find_audio_attachment(self, mock_agent, voice_config):
        """Finds audio attachment in activity."""
        wrapper = MSTeamsAgentWrapper(
            agent=mock_agent,
            config=MagicMock(),
            app=MagicMock(),
            voice_config=voice_config,
        )

        activity = MagicMock()
        activity.attachments = [
            MagicMock(content_type="audio/ogg", content_url="http://..."),
        ]

        result = wrapper._find_audio_attachment(activity)
        assert result is not None
        assert result.content_type == "audio/ogg"

    def test_ignores_non_audio_attachment(self, mock_agent, voice_config):
        """Ignores non-audio attachments."""
        wrapper = MSTeamsAgentWrapper(
            agent=mock_agent,
            config=MagicMock(),
            app=MagicMock(),
            voice_config=voice_config,
        )

        activity = MagicMock()
        activity.attachments = [
            MagicMock(content_type="image/png", content_url="http://..."),
        ]

        result = wrapper._find_audio_attachment(activity)
        assert result is None

    @pytest.mark.asyncio
    async def test_handle_voice_shows_transcription(
        self, mock_agent, voice_config
    ):
        """Shows transcription with emoji prefix."""
        wrapper = MSTeamsAgentWrapper(
            agent=mock_agent,
            config=MagicMock(),
            app=MagicMock(),
            voice_config=voice_config,
        )
        wrapper.send_text = AsyncMock()
        wrapper.send_typing = AsyncMock()
        wrapper._voice_transcriber = MagicMock()
        wrapper._voice_transcriber.transcribe_url = AsyncMock(
            return_value=TranscriptionResult(
                text="Hello world",
                language="en",
                duration_seconds=3.0,
                processing_time_ms=500,
            )
        )
        wrapper._process_transcribed_message = AsyncMock()

        turn_context = MagicMock()
        turn_context.activity.attachments = [
            MagicMock(content_type="audio/ogg")
        ]
        turn_context.activity.conversation.id = "conv123"

        attachment = MagicMock()
        attachment.content_url = "http://test.com/audio.ogg"

        await wrapper._handle_voice_attachment(turn_context, attachment)

        # Check transcription was shown
        wrapper.send_text.assert_any_call(
            '🎤 *"Hello world"*',
            turn_context
        )

    @pytest.mark.asyncio
    async def test_voice_disabled_ignores_audio(self, mock_agent, audio_activity):
        """When voice disabled, audio attachments are ignored."""
        disabled_config = VoiceTranscriberConfig(enabled=False)

        wrapper = MSTeamsAgentWrapper(
            agent=mock_agent,
            config=MagicMock(),
            app=MagicMock(),
            voice_config=disabled_config,
        )

        # Should not have transcriber
        assert wrapper._voice_transcriber is None
```

---

## Agent Instructions

When you pick up this task:

1. **Read the spec** at `sdd/specs/msteams-voice-support.spec.md`
2. **Check dependencies** — TASK-020 and TASK-022 must be completed
3. **Read existing wrapper** at `parrot/integrations/msteams/wrapper.py`
4. **Update status** in `sdd/tasks/.index.json` → `"in-progress"`
5. **Implement** following the scope above
6. **Run existing tests** to ensure no regressions
7. **Verify** all acceptance criteria are met
8. **Move this file** to `sdd/tasks/completed/TASK-021-msteams-wrapper-integration.md`
9. **Update index** → `"done"`
10. **Fill in the Completion Note** below

---

## Completion Note

**Completed by**: claude-session
**Date**: 2026-02-24
**Notes**:
- Added voice transcription support to `MSTeamsAgentWrapper`
- Added `voice_config: VoiceTranscriberConfig` parameter to `__init__`
- Added `AUDIO_CONTENT_TYPES` constant for supported audio formats
- Implemented `_find_audio_attachment()` to detect audio attachments
- Implemented `_handle_voice_attachment()` for full voice processing pipeline:
  - Downloads audio from MS Teams CDN (with optional auth token)
  - Transcribes using VoiceTranscriber
  - Shows transcription with 🎤 prefix (if configured)
  - Processes transcribed text through normal agent flow
  - Handles errors gracefully with user-friendly messages
- Implemented `_get_attachment_token()` for CDN authentication
- Implemented `_process_transcribed_message()` with `source: "voice_note"` for analytics
- Added `close_voice_transcriber()` for resource cleanup
- Modified `on_message_activity()` to check for audio BEFORE text processing
- Logs warning when multiple audio attachments present (only first processed)
- Created 17 comprehensive integration tests in `test_voice_integration.py`
- All 142 MS Teams tests pass (no regressions)

**Deviations from spec**: none
