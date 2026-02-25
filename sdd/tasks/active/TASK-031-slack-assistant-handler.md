# TASK-031: Slack Agents & AI Apps Handler

**Feature**: Slack Wrapper Integration Enhancements
**Spec**: `sdd/specs/slack-wrapper-integration.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: L (4-8h)
**Depends-on**: TASK-026, TASK-027, TASK-030
**Assigned-to**: unassigned

---

## Context

> This task implements Slack's Agents & AI Apps feature for native assistant experience.
> Reference: Spec Section 8 (Slack Agents & AI Apps) and Section 3 (Module 8).

Slack's "Agents & AI Apps" feature provides a native AI assistant experience with split-view panel, suggested prompts, loading states, thread titles, and chat streaming.

---

## Scope

- Create `parrot/integrations/slack/assistant.py` module
- Implement `SlackAssistantHandler` class
- Handle `assistant_thread_started` event
- Handle `assistant_thread_context_changed` event
- Handle `message.im` in assistant threads
- Implement suggested prompts via `assistant.threads.setSuggestedPrompts`
- Implement thread titles via `assistant.threads.setTitle`
- Implement chat streaming via `slack-sdk chat_stream()`
- Integrate with wrapper event routing

**NOT in scope**:
- Custom assistant personas
- Multi-workspace support
- Analytics/telemetry

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `parrot/integrations/slack/assistant.py` | CREATE | Assistant handler module |
| `parrot/integrations/slack/wrapper.py` | MODIFY | Route assistant events |
| `parrot/integrations/slack/socket_handler.py` | MODIFY | Route assistant events |
| `tests/unit/test_slack_assistant.py` | CREATE | Unit tests |
| `parrot/integrations/slack/__init__.py` | MODIFY | Export handler |

---

## Implementation Notes

### Pattern to Follow
```python
# parrot/integrations/slack/assistant.py
"""
Slack Agents & AI Apps integration for AI-Parrot.

Implements the assistant container experience with split-view panel,
suggested prompts, loading states, thread titles, and streaming.

Ref: https://api.slack.com/docs/apps/ai
"""
import json
import asyncio
import logging
from typing import Any, Dict, List, Optional, TYPE_CHECKING
from aiohttp import ClientSession

from ..parser import parse_response
from ...models.outputs import OutputMode

if TYPE_CHECKING:
    from .wrapper import SlackAgentWrapper

logger = logging.getLogger("SlackAssistant")


class SlackAssistantHandler:
    """Handles Slack's Agents & AI Apps events."""

    def __init__(self, wrapper: 'SlackAgentWrapper'):
        self.wrapper = wrapper
        self.config = wrapper.config
        self._thread_contexts: Dict[str, Dict[str, Any]] = {}

    @property
    def _headers(self) -> dict:
        return {
            "Authorization": f"Bearer {self.config.bot_token}",
            "Content-Type": "application/json; charset=utf-8",
        }

    # === Event Handlers ===

    async def handle_thread_started(self, event: dict, payload: dict) -> None:
        """Handle assistant_thread_started — user opens assistant container."""
        assistant_thread = event.get("assistant_thread", {})
        channel = assistant_thread.get("channel_id")
        thread_ts = assistant_thread.get("thread_ts")
        context = assistant_thread.get("context", {})

        if not channel or not thread_ts:
            return

        self._thread_contexts[thread_ts] = context

        # Welcome message
        welcome = self.config.welcome_message or "Hi! How can I help you today?"
        await self._post_message(channel, welcome, thread_ts=thread_ts)

        # Suggested prompts
        prompts = self.config.suggested_prompts or [
            {"title": "Summarize this channel", "message": "Summarize the recent discussion"},
            {"title": "Help me draft a message", "message": "Help me draft a professional message about"},
            {"title": "Explain a concept", "message": "Can you explain the following concept:"},
        ]
        await self._set_suggested_prompts(channel, thread_ts, prompts)

    async def handle_context_changed(self, event: dict) -> None:
        """Handle assistant_thread_context_changed — user switched channels."""
        assistant_thread = event.get("assistant_thread", {})
        thread_ts = assistant_thread.get("thread_ts")
        context = assistant_thread.get("context", {})
        if thread_ts:
            self._thread_contexts[thread_ts] = context

    async def handle_user_message(self, event: dict) -> None:
        """Handle message.im in an assistant thread."""
        channel = event.get("channel")
        thread_ts = event.get("thread_ts") or event.get("ts")
        text = (event.get("text") or "").strip()
        user = event.get("user") or "unknown"
        team = event.get("team")

        if not channel or not text:
            return

        session_id = f"assistant:{channel}:{user}"

        # 1. Set thread title (auto-generated from first message)
        title = text[:100] + ("..." if len(text) > 100 else "")
        await self._set_title(channel, thread_ts, title)

        # 2. Set loading status
        await self._set_status(
            channel, thread_ts,
            status="is thinking...",
            loading_messages=[
                "Analyzing your question...",
                "Consulting the knowledge base...",
                "Preparing a thoughtful response...",
            ],
        )

        # 3. Process with agent
        memory = self.wrapper._get_or_create_memory(session_id)
        try:
            if hasattr(self.wrapper.agent, 'ask_stream') and team:
                await self._stream_response(
                    channel=channel, thread_ts=thread_ts, text=text,
                    user=user, team=team, memory=memory, session_id=session_id,
                )
            else:
                response = await self.wrapper.agent.ask(
                    text, memory=memory, output_mode=OutputMode.SLACK,
                    session_id=session_id, user_id=user,
                )
                parsed = parse_response(response)
                blocks = self.wrapper._build_blocks(parsed)

                from .interactive import build_feedback_blocks
                blocks.extend(build_feedback_blocks())

                await self._post_message(
                    channel, parsed.text or "Done.",
                    blocks=blocks, thread_ts=thread_ts,
                )
        except Exception as exc:
            logger.error("Assistant response error: %s", exc, exc_info=True)
            await self._clear_status(channel, thread_ts)
            await self._post_message(
                channel, "Sorry, I encountered an error. Please try again.",
                thread_ts=thread_ts,
            )

    async def _stream_response(
        self, channel: str, thread_ts: str, text: str,
        user: str, team: str, memory, session_id: str,
    ) -> None:
        """Stream response using Slack's chat_stream API."""
        from slack_sdk.web.async_client import AsyncWebClient
        client = AsyncWebClient(token=self.config.bot_token)

        streamer = client.chat_stream(
            channel=channel,
            thread_ts=thread_ts,
            recipient_team_id=team,
            recipient_user_id=user,
        )

        try:
            async for chunk in self.wrapper.agent.ask_stream(
                text, memory=memory, output_mode=OutputMode.SLACK,
                session_id=session_id, user_id=user,
            ):
                content = getattr(chunk, 'content', chunk) if not isinstance(chunk, str) else chunk
                if content:
                    streamer.append(markdown_text=content)

            from .interactive import build_feedback_blocks
            streamer.stop(blocks=build_feedback_blocks())

        except Exception as exc:
            logger.error("Streaming error: %s", exc, exc_info=True)
            try:
                streamer.stop(markdown_text="\n\n:warning: An error occurred during generation.")
            except Exception:
                pass

    # === Slack API helpers ===

    async def _set_status(
        self, channel: str, thread_ts: str,
        status: str, loading_messages: list[str] | None = None
    ) -> None:
        """Set assistant loading status."""
        payload = {"channel_id": channel, "thread_ts": thread_ts, "status": status}
        if loading_messages:
            payload["loading_messages"] = loading_messages

        async with ClientSession() as session:
            async with session.post(
                "https://slack.com/api/assistant.threads.setStatus",
                headers=self._headers,
                data=json.dumps(payload),
            ) as resp:
                data = await resp.json()
                if not data.get("ok"):
                    logger.warning("setStatus failed: %s", data.get("error"))

    async def _clear_status(self, channel: str, thread_ts: str) -> None:
        """Clear assistant status."""
        await self._set_status(channel, thread_ts, status="")

    async def _set_title(self, channel: str, thread_ts: str, title: str) -> None:
        """Set assistant thread title."""
        async with ClientSession() as session:
            await session.post(
                "https://slack.com/api/assistant.threads.setTitle",
                headers=self._headers,
                data=json.dumps({
                    "channel_id": channel,
                    "thread_ts": thread_ts,
                    "title": title
                }),
            )

    async def _set_suggested_prompts(
        self, channel: str, thread_ts: str, prompts: list[dict]
    ) -> None:
        """Set suggested prompts for assistant thread."""
        async with ClientSession() as session:
            await session.post(
                "https://slack.com/api/assistant.threads.setSuggestedPrompts",
                headers=self._headers,
                data=json.dumps({
                    "channel_id": channel,
                    "thread_ts": thread_ts,
                    "prompts": prompts
                }),
            )

    async def _post_message(
        self, channel: str, text: str,
        blocks: list[dict] | None = None, thread_ts: str | None = None
    ) -> None:
        """Post message to channel/thread."""
        payload = {"channel": channel, "text": text}
        if blocks:
            payload["blocks"] = blocks
        if thread_ts:
            payload["thread_ts"] = thread_ts

        async with ClientSession() as session:
            await session.post(
                "https://slack.com/api/chat.postMessage",
                headers=self._headers,
                data=json.dumps(payload),
            )
```

### Integration in wrapper._handle_events()
```python
async def _handle_events(self, request: web.Request) -> web.Response:
    # ... existing verification, dedup, parsing ...

    event = payload.get("event", {})
    event_type = event.get("type")

    # Assistant-specific events
    if event_type == "assistant_thread_started" and self.config.enable_assistant:
        asyncio.create_task(self._assistant_handler.handle_thread_started(event, payload))
        return web.json_response({"ok": True})

    if event_type == "assistant_thread_context_changed" and self.config.enable_assistant:
        asyncio.create_task(self._assistant_handler.handle_context_changed(event))
        return web.json_response({"ok": True})

    # message.im in assistant context
    if (event_type == "message" and event.get("channel_type") == "im"
            and self.config.enable_assistant):
        if event.get("subtype") == "bot_message":
            return web.json_response({"ok": True})
        asyncio.create_task(self._assistant_handler.handle_user_message(event))
        return web.json_response({"ok": True})

    # ... existing regular event handling ...
```

### Key Constraints
- Requires `assistant:write` OAuth scope
- Requires Slack paid plan (Pro, Business+, Enterprise Grid)
- `chat_stream()` requires `slack-sdk >= 3.40.0`
- Thread contexts stored in memory (not persistent)

### References in Codebase
- Slack AI Apps docs: https://api.slack.com/docs/apps/ai
- Bolt Python: https://docs.slack.dev/tools/bolt-python/concepts/ai-apps/
- SDK streaming: https://docs.slack.dev/tools/python-slack-sdk/reference/web/chat_stream.html

---

## Acceptance Criteria

- [ ] `assistant_thread_started` sends welcome + suggested prompts
- [ ] `assistant_thread_context_changed` updates context
- [ ] `message.im` sets title, status, processes, responds
- [ ] Loading messages rotate in Slack UI
- [ ] Streaming works when agent supports `ask_stream`
- [ ] Feedback buttons appended to responses
- [ ] Wrapper routes events when `enable_assistant=True`
- [ ] All tests pass: `pytest tests/unit/test_slack_assistant.py -v`

---

## Test Specification

```python
# tests/unit/test_slack_assistant.py
import pytest
import json
from unittest.mock import AsyncMock, MagicMock, patch
from parrot.integrations.slack.assistant import SlackAssistantHandler


@pytest.fixture
def mock_wrapper():
    wrapper = MagicMock()
    wrapper.config.bot_token = "xoxb-test"
    wrapper.config.welcome_message = "Hello!"
    wrapper.config.suggested_prompts = [{"title": "Help", "message": "Help me"}]
    wrapper._get_or_create_memory = MagicMock(return_value=MagicMock())
    wrapper._build_blocks = MagicMock(return_value=[])
    wrapper.agent.ask = AsyncMock(return_value="Response text")
    return wrapper


class TestSlackAssistantHandler:
    @pytest.mark.asyncio
    async def test_thread_started_sends_welcome(self, mock_wrapper):
        """Thread started sends welcome message and prompts."""
        handler = SlackAssistantHandler(mock_wrapper)

        with patch('aiohttp.ClientSession') as MockSession:
            mock_session = AsyncMock()
            MockSession.return_value.__aenter__.return_value = mock_session

            event = {
                "assistant_thread": {
                    "channel_id": "C123",
                    "thread_ts": "123.456",
                    "context": {},
                }
            }

            await handler.handle_thread_started(event, {})

            # Should make 2 calls: postMessage + setSuggestedPrompts
            assert mock_session.post.call_count == 2

    @pytest.mark.asyncio
    async def test_context_changed_updates_context(self, mock_wrapper):
        """Context changed updates stored context."""
        handler = SlackAssistantHandler(mock_wrapper)

        event = {
            "assistant_thread": {
                "thread_ts": "123.456",
                "context": {"channel_id": "C789"},
            }
        }

        await handler.handle_context_changed(event)

        assert handler._thread_contexts["123.456"]["channel_id"] == "C789"

    @pytest.mark.asyncio
    async def test_user_message_sets_status_and_responds(self, mock_wrapper):
        """User message sets loading status and sends response."""
        handler = SlackAssistantHandler(mock_wrapper)

        with patch('aiohttp.ClientSession') as MockSession:
            mock_session = AsyncMock()
            MockSession.return_value.__aenter__.return_value = mock_session
            mock_session.post.return_value.__aenter__.return_value.json = AsyncMock(
                return_value={"ok": True}
            )

            event = {
                "channel": "D123",
                "thread_ts": "123.456",
                "text": "Hello assistant",
                "user": "U456",
            }

            await handler.handle_user_message(event)

            # Should call: setTitle, setStatus, agent.ask, postMessage
            assert mock_session.post.call_count >= 3
            mock_wrapper.agent.ask.assert_called_once()

    @pytest.mark.asyncio
    async def test_empty_text_ignored(self, mock_wrapper):
        """Empty message text is ignored."""
        handler = SlackAssistantHandler(mock_wrapper)

        event = {
            "channel": "D123",
            "text": "",
            "user": "U456",
        }

        await handler.handle_user_message(event)

        mock_wrapper.agent.ask.assert_not_called()
```

---

## Agent Instructions

When you pick up this task:

1. **Read the spec** at the path listed above for full context
2. **Check dependencies** — verify TASK-026, TASK-027, TASK-030 are in `tasks/completed/`
3. **Update status** in `tasks/.index.json` → `"in-progress"` with your session ID
4. **Implement** following the scope and notes above
5. **Verify** all acceptance criteria are met
6. **Move this file** to `tasks/completed/TASK-031-slack-assistant-handler.md`
7. **Update index** → `"done"`
8. **Fill in the Completion Note** below

---

## Completion Note

*(Agent fills this in when done)*

**Completed by**:
**Date**:
**Notes**:

**Deviations from spec**:
