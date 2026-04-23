# TASK-844: Reply context extraction and handler integration

**Feature**: FEAT-120 — Telegram Wrapper Rich Message Integration
**Spec**: `sdd/specs/telegram-wrapper-audio-files-integration.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: M (2-4h)
**Depends-on**: TASK-843
**Assigned-to**: unassigned

---

## Context

Spec Module 1. When a user replies to a specific bot message (or their own previous
message), the wrapper currently ignores `message.reply_to_message` entirely. This task
adds `_extract_reply_context()` which builds a `<reply_context>` XML block from the
replied-to message and prepends it to the user's question before it reaches
`_enrich_question`. All four handlers (message, photo, voice, document) gain reply
context support.

---

## Scope

- Implement `_extract_reply_context(self, message: Message) -> str` helper:
  - If `message.reply_to_message` is `None` or the config has `enable_reply_context=False`, return `""`
  - Extract original message text (or caption for photo/media, `[Voice message]` for voice,
    `[Document: filename]` for document)
  - Truncate to 200 characters with `...` suffix if exceeded
  - Wrap in `<reply_context>original text</reply_context>` XML block
  - Look up `_message_id_cache` first for O(1) retrieval; fall back to `reply_to_message.text`
- Update `handle_message`: prepend reply context to `user_text` before passing to `_invoke_agent`
- Update `handle_photo`: prepend reply context to `enriched_caption`
- Update `handle_voice`: prepend reply context to transcribed text before processing
- Add message ID caching calls to `handle_photo` and `handle_voice`
  (TASK-843 only adds it to `handle_message`)
- Write comprehensive unit tests for all reply context scenarios

**NOT in scope**: Document handler (TASK-845 — it will include reply context itself),
core `_enrich_question` changes

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot/src/parrot/integrations/telegram/wrapper.py` | MODIFY | Add `_extract_reply_context`, update handlers |
| `tests/unit/test_telegram_reply_context_feat120.py` | CREATE | Unit tests |

---

## Codebase Contract (Anti-Hallucination)

### Verified Imports
```python
# packages/ai-parrot/src/parrot/integrations/telegram/wrapper.py
from aiogram.types import Message                     # line 22
```

### Existing Signatures to Use
```python
# packages/ai-parrot/src/parrot/integrations/telegram/wrapper.py:62
class TelegramAgentWrapper:
    config: TelegramAgentConfig                        # line 91
    logger: logging.Logger                             # line 99
    _message_id_cache: Dict[int, Dict[int, str]]       # added by TASK-843

    # wrapper.py:901
    @staticmethod
    def _enrich_question(question: str, session: TelegramUserSession) -> str:
        # Wraps user identity in <user_context> XML — reply context should
        # be prepended BEFORE this call so it appears before <user_context>

    # wrapper.py:1114 (after TASK-842)
    async def _invoke_agent(
        self, session, question, *, memory, output_mode, message=None,
        attachments=None,
    ) -> Any:

    # wrapper.py:1913
    async def handle_message(self, message: Message) -> None:
        # line 1932: user_text = message.text
        # line 1997-2004: response = await self._invoke_agent(session, user_text, ...)

    # wrapper.py:2476
    async def handle_photo(self, message: Message) -> None:
        # line 2494: caption = message.caption or "Describe this image"
        # line 2516-2518: enriched_caption = f"{caption}\n\n[Attached image ...]"
        # line 2521-2539: with telegram_chat_scope: agent call

    # wrapper.py:2585
    async def handle_voice(self, message: Message) -> None:
        # Transcribes voice → text, then processes via agent

# aiogram Message attributes (from aiogram v3 API):
# message.reply_to_message: Optional[Message]  — the message being replied to
# message.reply_to_message.text: Optional[str]
# message.reply_to_message.caption: Optional[str]
# message.reply_to_message.voice: Optional[Voice]
# message.reply_to_message.document: Optional[Document]
# message.reply_to_message.document.file_name: Optional[str]
# message.reply_to_message.message_id: int
```

### Does NOT Exist
- ~~`TelegramAgentWrapper._extract_reply_context`~~ — does not exist yet; this task creates it
- ~~`TelegramAgentWrapper.handle_reply`~~ — no dedicated reply handler; detection is added to existing handlers
- ~~`_enrich_question` handling reply context~~ — `_enrich_question` only handles `<user_context>`; reply context is prepended before calling it
- ~~`TelegramAgentConfig.reply_context_max_length`~~ — no such field; hardcoded 200 chars per spec

---

## Implementation Notes

### Pattern to Follow

Reply context extraction helper:
```python
def _extract_reply_context(self, message: Message) -> str:
    if not self.config.enable_reply_context:
        return ""
    reply = message.reply_to_message
    if reply is None:
        return ""

    # Try cache first for fast lookup
    chat_id = message.chat.id
    reply_id = reply.message_id
    cached = self._message_id_cache.get(chat_id, {}).get(reply_id)
    if cached:
        original_text = cached
    elif reply.text:
        original_text = reply.text
    elif reply.caption:
        original_text = reply.caption
    elif reply.voice:
        original_text = "[Voice message]"
    elif reply.document:
        fname = reply.document.file_name or "unknown"
        original_text = f"[Document: {fname}]"
    else:
        original_text = "[Media message]"

    # Truncate
    if len(original_text) > 200:
        original_text = original_text[:197] + "..."

    return f"<reply_context>{original_text}</reply_context>\n"
```

Integration in `handle_message`:
```python
# After user_text = message.text
reply_ctx = self._extract_reply_context(message)
if reply_ctx:
    user_text = reply_ctx + user_text
```

### Key Constraints
- Reply context XML block is prepended BEFORE `_enrich_question` so it appears before `<user_context>`
- `_extract_reply_context` is synchronous (no I/O) — just reads message attributes and cache
- Must handle `reply_to_message` being `None` (deleted message) gracefully
- Must handle media messages without text (voice, document, photo without caption)
- The `enable_reply_context` config field is created by TASK-841

### References in Codebase
- `wrapper.py:902-916` — `_enrich_question` XML pattern to follow
- `wrapper.py:1913-2039` — `handle_message` flow
- `wrapper.py:2476-2550` — `handle_photo` flow
- `wrapper.py:2585-2684` — `handle_voice` flow

---

## Acceptance Criteria

- [ ] `_extract_reply_context` returns `<reply_context>text</reply_context>\n` for text replies
- [ ] Returns caption text for photo/media replies with captions
- [ ] Returns `[Voice message]` for voice message replies
- [ ] Returns `[Document: filename.pdf]` for document replies
- [ ] Truncates to 200 chars with `...` suffix
- [ ] Returns empty string when not a reply
- [ ] Returns empty string when `enable_reply_context` is `False`
- [ ] Returns empty string when `reply_to_message` is `None` (deleted message)
- [ ] Uses `_message_id_cache` for fast lookup, falls back to message attributes
- [ ] `handle_message` prepends reply context to user text
- [ ] `handle_photo` prepends reply context to enriched caption
- [ ] `handle_voice` prepends reply context to transcribed text
- [ ] `handle_photo` and `handle_voice` cache message IDs
- [ ] All unit tests pass: `pytest tests/unit/test_telegram_reply_context_feat120.py -v`

---

## Test Specification

```python
# tests/unit/test_telegram_reply_context_feat120.py
import pytest
from unittest.mock import MagicMock


class TestExtractReplyContext:
    def test_text_message_reply(self):
        """Reply to text → returns <reply_context>text</reply_context>."""

    def test_caption_reply(self):
        """Reply to photo with caption → returns caption in XML."""

    def test_voice_reply(self):
        """Reply to voice → returns [Voice message] placeholder."""

    def test_document_reply(self):
        """Reply to document → returns [Document: filename.pdf] placeholder."""

    def test_truncation(self):
        """Original > 200 chars → truncated with '...'."""

    def test_no_reply(self):
        """Not a reply → returns empty string."""

    def test_deleted_message(self):
        """reply_to_message is None → returns empty string."""

    def test_config_disabled(self):
        """enable_reply_context=False → returns empty string."""

    def test_cache_hit(self):
        """Cached text used instead of message attributes."""

    def test_media_no_text(self):
        """Media message without text/caption → [Media message]."""


class TestHandlerReplyIntegration:
    async def test_handle_message_with_reply(self):
        """Reply context prepended to user text in handle_message."""

    async def test_handle_photo_with_reply(self):
        """Reply context prepended to enriched caption in handle_photo."""

    async def test_handle_voice_with_reply(self):
        """Reply context prepended to transcribed text in handle_voice."""
```

---

## Agent Instructions

When you pick up this task:

1. **Read the spec** at the path listed above for full context
2. **Check dependencies** — TASK-841 (config fields) and TASK-843 (message ID cache) must be done
3. **Verify the Codebase Contract** — confirm `handle_message`, `handle_photo`, `handle_voice` flows, `_message_id_cache` attribute from TASK-843
4. **Update status** in `tasks/.index.json` → `"in-progress"` with your session ID
5. **Implement** following the scope, codebase contract, and notes above
6. **Verify** all acceptance criteria are met
7. **Move this file** to `tasks/completed/TASK-844-reply-context-extraction.md`
8. **Update index** → `"done"`
9. **Fill in the Completion Note** below

---

## Completion Note

**Completed by**: sdd-worker (Claude Sonnet)
**Date**: 2026-04-23
**Notes**: Implemented `_extract_reply_context` with all message type handling (text, caption, voice, document, media fallback), 200-char truncation, cache lookup, and config toggle. Updated `handle_message`, `handle_photo`, and `handle_voice` to prepend reply context. Also added message ID caching + metadata storage to `handle_photo` and `handle_voice` (per TASK-844 scope: "Add message ID caching calls to handle_photo and handle_voice"). All 14 unit tests pass.

**Deviations from spec**: none
