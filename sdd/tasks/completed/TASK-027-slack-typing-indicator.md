# TASK-027: Slack Typing Indicator

**Feature**: Slack Wrapper Integration Enhancements
**Spec**: `sdd/specs/slack-wrapper-integration.spec.md`
**Status**: done
**Priority**: medium
**Estimated effort**: S (< 2h)
**Depends-on**: TASK-026
**Assigned-to**: claude-session

---

## Context

> This task adds visual feedback while the agent processes requests.
> Reference: Spec Section 5 (Typing Indicator) and Section 3 (Module 4).

Users currently see no feedback while waiting for agent responses. This task adds ephemeral "thinking" messages and optional assistant status indicators (for Agents & AI Apps).

---

## Scope

- Add `_send_typing_indicator()` method for ephemeral messages
- Add `_set_assistant_status()` method for Agents & AI Apps
- Integrate typing indicator into `_answer()` method
- Support configurable loading messages

**NOT in scope**:
- Full Agents & AI Apps handler (TASK-029)
- Interactive components (TASK-028)

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `parrot/integrations/slack/wrapper.py` | MODIFY | Add typing indicator methods |
| `tests/unit/test_slack_wrapper.py` | MODIFY | Add typing indicator tests |

---

## Implementation Notes

### Pattern to Follow
```python
async def _send_typing_indicator(
    self, channel: str, user: str, thread_ts: str | None = None,
) -> str | None:
    """Send ephemeral 'thinking' message visible only to the user."""
    payload = {
        "channel": channel,
        "user": user,
        "text": ":hourglass_flowing_sand: Thinking...",
    }
    if thread_ts:
        payload["thread_ts"] = thread_ts

    headers = {
        "Authorization": f"Bearer {self.config.bot_token}",
        "Content-Type": "application/json; charset=utf-8",
    }
    async with ClientSession() as session:
        async with session.post(
            "https://slack.com/api/chat.postEphemeral",
            headers=headers,
            data=json.dumps(payload),
        ) as resp:
            data = await resp.json()
            return data.get("message_ts")


async def _set_assistant_status(
    self, channel: str, thread_ts: str,
    status: str = "is thinking...",
    loading_messages: list[str] | None = None,
) -> None:
    """
    Set assistant status in Slack AI container.
    Requires Agents & AI Apps feature and assistant:write scope.
    """
    payload = {
        "channel_id": channel,
        "thread_ts": thread_ts,
        "status": status,
    }
    if loading_messages:
        payload["loading_messages"] = loading_messages

    headers = {
        "Authorization": f"Bearer {self.config.bot_token}",
        "Content-Type": "application/json; charset=utf-8",
    }
    async with ClientSession() as session:
        async with session.post(
            "https://slack.com/api/assistant.threads.setStatus",
            headers=headers,
            data=json.dumps(payload),
        ) as resp:
            data = await resp.json()
            if not data.get("ok"):
                self.logger.warning("Failed to set assistant status: %s", data.get("error"))


# In _answer():
async def _answer(self, channel, user, text, thread_ts, session_id, files=None):
    memory = self._get_or_create_memory(session_id)

    # Send typing indicator
    if self.config.enable_assistant and thread_ts:
        await self._set_assistant_status(
            channel, thread_ts,
            status="is thinking...",
            loading_messages=[
                "Analyzing your question...",
                "Consulting the knowledge base...",
                "Preparing a response...",
            ],
        )
    else:
        await self._send_typing_indicator(channel, user, thread_ts)

    # ... rest of processing
```

### Key Constraints
- Ephemeral messages are only visible to the target user
- Assistant status requires `assistant:write` scope
- Loading messages rotate in the Slack UI
- Don't block on typing indicator errors

### References in Codebase
- `parrot/integrations/msteams/wrapper.py` — `send_typing()` pattern
- Slack API: https://api.slack.com/methods/chat.postEphemeral

---

## Acceptance Criteria

- [x] Ephemeral "Thinking..." message sent to user
- [x] Message appears in correct thread if `thread_ts` provided
- [x] Assistant status set when `enable_assistant=True`
- [x] Typing indicator errors don't break response flow
- [x] All tests pass: `pytest tests/unit/test_slack_wrapper.py -v` (24 tests)

---

## Test Specification

```python
# tests/unit/test_slack_wrapper.py (additions)

class TestSlackTypingIndicator:
    @pytest.mark.asyncio
    async def test_sends_ephemeral_message(self, wrapper):
        """Typing indicator sends ephemeral message."""
        with patch('aiohttp.ClientSession.post') as mock_post:
            mock_post.return_value.__aenter__.return_value.json = AsyncMock(
                return_value={"ok": True, "message_ts": "123.456"}
            )

            result = await wrapper._send_typing_indicator("C123", "U456", "789.012")

            assert result == "123.456"
            call_data = json.loads(mock_post.call_args[1]['data'])
            assert call_data["user"] == "U456"
            assert "Thinking" in call_data["text"]

    @pytest.mark.asyncio
    async def test_assistant_status_with_loading_messages(self, wrapper):
        """Assistant status includes rotating messages."""
        wrapper.config.enable_assistant = True

        with patch('aiohttp.ClientSession.post') as mock_post:
            mock_post.return_value.__aenter__.return_value.json = AsyncMock(
                return_value={"ok": True}
            )

            await wrapper._set_assistant_status(
                "C123", "789.012",
                loading_messages=["Processing...", "Almost done..."]
            )

            call_data = json.loads(mock_post.call_args[1]['data'])
            assert "loading_messages" in call_data
            assert len(call_data["loading_messages"]) == 2
```

---

## Agent Instructions

When you pick up this task:

1. **Read the spec** at the path listed above for full context
2. **Check dependencies** — verify TASK-024 is in `tasks/completed/`
3. **Update status** in `tasks/.index.json` → `"in-progress"` with your session ID
4. **Implement** following the scope and notes above
5. **Verify** all acceptance criteria are met
6. **Move this file** to `tasks/completed/TASK-027-slack-typing-indicator.md`
7. **Update index** → `"done"`
8. **Fill in the Completion Note** below

---

## Completion Note

**Completed by**: claude-session
**Date**: 2026-02-24
**Notes**:
- Added `_send_typing_indicator()` method that sends ephemeral "Thinking..." message via `chat.postEphemeral`
- Added `_set_assistant_status()` method for Agents & AI Apps with configurable loading messages
- Added `_clear_assistant_status()` helper method to clear the assistant status
- Integrated typing indicator into `_answer()` method:
  - Uses assistant status when `enable_assistant=True` and thread_ts is present
  - Falls back to ephemeral message for regular mode
- All typing indicator errors are caught and logged without breaking response flow
- Added 8 new tests in `TestSlackTypingIndicator` class (total 24 tests)

**Deviations from spec**:
- Added `_clear_assistant_status()` method not in original spec but useful for cleanup
- Used `logger.debug` instead of `logger.warning` for typing indicator failures (less noisy)
