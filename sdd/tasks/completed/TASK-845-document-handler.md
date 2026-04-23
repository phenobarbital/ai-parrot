# TASK-845: Complete document handler implementation

**Feature**: FEAT-120 — Telegram Wrapper Rich Message Integration
**Spec**: `sdd/specs/telegram-wrapper-audio-files-integration.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: M (2-4h)
**Depends-on**: TASK-841, TASK-842, TASK-843, TASK-844
**Assigned-to**: unassigned

---

## Context

Spec Module 3. The current `handle_document` (line 2552) is a stub that acknowledges
receipt but does nothing. This task replaces it with a full implementation following the
exact `handle_photo` pattern: auth checks, size validation, download to temp file,
enrich caption with file path, call `_invoke_agent` with attachments. It also integrates
reply context (from TASK-844) and message ID tracking (from TASK-843).

---

## Scope

- Replace stub `handle_document` with full implementation:
  - Auth check: `_is_authorized()` + `_check_authentication()`
  - Size validation: reject if `document.file_size > config.max_document_size_mb * 1024 * 1024`
    (handle `file_size` being `None` — attempt download with error handling)
  - Download: `bot.get_file()` → `bot.download_file()` → temp file
  - File naming: use original extension from `document.file_name`; fall back to `.bin`
  - Enrich caption: `f"{caption}\n\n[Attached document saved at: {tmp_path}]"`
  - Reply context: prepend `_extract_reply_context(message)` to enriched caption
  - Call `_invoke_agent` with `attachments=[str(tmp_path)]`
  - Cache message IDs and store metadata after response
  - Typing indicator during processing
  - Error handling: try/except with user-friendly error message
- Write unit tests for download, size rejection, auth, missing filename

**NOT in scope**: Text extraction from documents (PDF-to-text etc.), group chat support

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot/src/parrot/integrations/telegram/wrapper.py` | MODIFY | Replace `handle_document` stub |
| `tests/unit/test_telegram_document_handler_feat120.py` | CREATE | Unit tests |

---

## Codebase Contract (Anti-Hallucination)

### Verified Imports
```python
# packages/ai-parrot/src/parrot/integrations/telegram/wrapper.py
from aiogram.types import Message, ContentType          # line 22
from aiogram.enums import ChatAction                    # used in handle_photo
import tempfile                                         # stdlib
from pathlib import Path                                # stdlib
```

### Existing Signatures to Use
```python
# packages/ai-parrot/src/parrot/integrations/telegram/wrapper.py:2552
async def handle_document(self, message: Message) -> None:
    """Handle document messages."""
    # CURRENT STUB — to be replaced entirely

# Pattern to follow — handle_photo (wrapper.py:2476):
async def handle_photo(self, message: Message) -> None:
    chat_id = message.chat.id
    # 1. _is_authorized(chat_id)                        # line 2485
    # 2. _check_authentication(message)                 # line 2489
    # 3. photo = message.photo[-1]                      # line 2493
    # 4. bot.send_chat_action(chat_id, ChatAction.TYPING)  # line 2496
    # 5. file = await self.bot.get_file(photo.file_id)  # line 2500
    # 6. tmp = tempfile.NamedTemporaryFile(...)          # line 2502
    # 7. await self.bot.download_file(file.file_path, tmp)  # line 2505
    # 8. enriched_caption = f"{caption}\n\n[Attached...]"  # line 2516
    # 9. with telegram_chat_scope: agent call            # line 2521
    # 10. self._parse_response / self._send_parsed_response  # line 2541-2542

# From TASK-842 (after implementation):
async def _invoke_agent(
    self, session, question, *, memory, output_mode, message=None,
    attachments=None,
) -> Any:

# From TASK-843 (after implementation):
def _cache_message_id(self, chat_id: int, message_id: int, text: str) -> None:
async def _store_telegram_metadata(
    self, memory, user_id, session_id, user_message_id, bot_message_id,
) -> None:

# From TASK-844 (after implementation):
def _extract_reply_context(self, message: Message) -> str:

# From TASK-841 (after implementation):
# TelegramAgentConfig.max_document_size_mb: int = 20

# wrapper.py:880
def _get_or_create_memory(self, chat_id: int) -> 'ConversationMemory':
# wrapper.py:874
def _is_authorized(self, chat_id: int) -> bool:
# wrapper.py:1199
async def _check_authentication(self, message: Message) -> bool:
# wrapper.py:1904
async def _typing_indicator(self, chat_id: int) -> None:

# aiogram Document attributes:
# message.document.file_id: str
# message.document.file_name: Optional[str]
# message.document.file_size: Optional[int]  — may be None for some file types
# message.document.mime_type: Optional[str]
```

### Does NOT Exist
- ~~Full `handle_document` implementation~~ — currently a stub; this task replaces it
- ~~`TelegramAgentWrapper._download_document()`~~ — no such helper; download inline like `handle_photo`
- ~~`document.file_path`~~ — Document objects don't have `file_path`; must use `bot.get_file(file_id)` first
- ~~Auto temp file cleanup~~ — temp files are NOT deleted (same as photo handler pattern)

---

## Implementation Notes

### Pattern to Follow

Follow `handle_photo` exactly, adapted for documents:

```python
async def handle_document(self, message: Message) -> None:
    """Handle document messages — download and pass to agent."""
    chat_id = message.chat.id

    if not self._is_authorized(chat_id):
        await message.answer("⛔ You are not authorized to use this bot.")
        return

    if not await self._check_authentication(message):
        return

    document = message.document
    caption = message.caption or f"Process this document: {document.file_name or 'unnamed'}"

    # Size validation
    max_bytes = self.config.max_document_size_mb * 1024 * 1024
    if document.file_size is not None and document.file_size > max_bytes:
        await message.answer(
            f"📄 Document too large ({document.file_size / (1024*1024):.1f} MB). "
            f"Maximum is {self.config.max_document_size_mb} MB."
        )
        return

    # Start typing indicator
    typing_task = asyncio.create_task(self._typing_indicator(chat_id))

    try:
        # Download document
        file = await self.bot.get_file(document.file_id)
        # Determine extension
        if document.file_name:
            ext = Path(document.file_name).suffix or '.bin'
        else:
            ext = '.bin'
        tmp = tempfile.NamedTemporaryFile(
            suffix=ext, prefix='tg_doc_', delete=False
        )
        await self.bot.download_file(file.file_path, tmp)
        tmp.close()
        tmp_path = Path(tmp.name)

        self.logger.debug("Chat %d: Document downloaded to %s", chat_id, tmp_path)

        attachment_paths = [str(tmp_path)]

        memory = self._get_or_create_memory(chat_id)
        session = self._get_user_session(message)

        # Reply context
        reply_ctx = self._extract_reply_context(message)
        enriched_caption = f"{caption}\n\n[Attached document saved at: {tmp_path}]"
        if reply_ctx:
            enriched_caption = reply_ctx + enriched_caption

        # Cache user message ID
        self._cache_message_id(chat_id, message.message_id, caption[:200])

        with telegram_chat_scope(chat_id):
            response = await self._invoke_agent(
                session,
                enriched_caption,
                memory=memory,
                output_mode=OutputMode.TELEGRAM,
                message=message,
                attachments=attachment_paths,
            )

        parsed = self._parse_response(response)
        typing_task.cancel()
        sent = await self._send_parsed_response(message, parsed)

        # Cache bot response and store metadata
        bot_msg_id = sent.message_id if sent else 0
        self._cache_message_id(chat_id, bot_msg_id, str(parsed)[:200])
        await self._store_telegram_metadata(
            memory, session.user_id, session.session_id,
            message.message_id, bot_msg_id,
        )

    except Exception as e:
        self.logger.error("Error processing document: %s", e, exc_info=True)
        await message.answer("❌ Sorry, I couldn't process that document.")
    finally:
        typing_task.cancel()
```

### Key Constraints
- Telegram API has 20MB download limit — pre-check `document.file_size` when available
- `document.file_size` can be `None` — in that case, attempt the download and let the
  `bot.get_file()` call raise if too large
- Temp file is NOT deleted (consistent with photo handler pattern — tools may need the path)
- `typing_task.cancel()` in both success path and `finally` block
- Use `document.file_name` extension, NOT `file.file_path` extension (the Telegram CDN
  may rename files)

### References in Codebase
- `wrapper.py:2476-2550` — `handle_photo` (exact pattern to follow)
- `wrapper.py:2585-2684` — `handle_voice` (typing indicator + finally pattern)
- `wrapper.py:1904` — `_typing_indicator`

---

## Acceptance Criteria

- [ ] Documents are downloaded to temp files with correct extension
- [ ] Caption enriched with file path: `[Attached document saved at: /tmp/...]`
- [ ] Reply context prepended when message is a reply
- [ ] Size validation: files > `max_document_size_mb` rejected with user-friendly message
- [ ] Files without `file_name` use `.bin` extension
- [ ] Auth checks: unauthorized → rejection, unauthenticated → auth flow
- [ ] `_invoke_agent` called with `attachments=[path]`
- [ ] Message IDs cached and metadata stored after response
- [ ] Typing indicator shown during processing
- [ ] Errors caught and user-friendly message sent
- [ ] Temp file NOT deleted (consistent with photo handler)
- [ ] All unit tests pass: `pytest tests/unit/test_telegram_document_handler_feat120.py -v`

---

## Test Specification

```python
# tests/unit/test_telegram_document_handler_feat120.py
import pytest
from unittest.mock import AsyncMock, MagicMock, patch


class TestHandleDocument:
    async def test_downloads_document(self):
        """Document downloaded to temp file and path passed to agent."""

    async def test_size_limit_rejection(self):
        """Document exceeding max size → user-friendly rejection message."""

    async def test_size_none_attempts_download(self):
        """Document with file_size=None → download attempted anyway."""

    async def test_no_filename_uses_bin(self):
        """Document without file_name → .bin extension used."""

    async def test_preserves_file_extension(self):
        """Document with file_name='report.pdf' → .pdf extension preserved."""

    async def test_auth_required(self):
        """Unauthorized user → rejection message, no download."""

    async def test_reply_context_included(self):
        """Reply to bot message → reply context prepended to caption."""

    async def test_enriched_caption_format(self):
        """Caption includes [Attached document saved at: path]."""

    async def test_invoke_agent_called_with_attachments(self):
        """_invoke_agent receives attachments=[path]."""

    async def test_message_ids_cached(self):
        """User and bot message IDs cached after response."""

    async def test_error_handling(self):
        """Download error → user-friendly message, no crash."""

    async def test_typing_indicator_shown(self):
        """Typing indicator active during processing."""
```

---

## Agent Instructions

When you pick up this task:

1. **Read the spec** at the path listed above for full context
2. **Check dependencies** — TASK-841, TASK-842, TASK-843, TASK-844 must all be done
3. **Verify the Codebase Contract** — confirm `_invoke_agent` has `attachments` param (TASK-842), `_extract_reply_context` exists (TASK-844), `_cache_message_id` exists (TASK-843), `config.max_document_size_mb` exists (TASK-841)
4. **Update status** in `tasks/.index.json` → `"in-progress"` with your session ID
5. **Implement** following the scope, codebase contract, and notes above
6. **Verify** all acceptance criteria are met
7. **Move this file** to `tasks/completed/TASK-845-document-handler.md`
8. **Update index** → `"done"`
9. **Fill in the Completion Note** below

---

## Completion Note

**Completed by**: sdd-worker (Claude Sonnet)
**Date**: 2026-04-23
**Notes**: Replaced stub `handle_document` with full implementation following `handle_photo` pattern exactly. Auth check, size validation (with None file_size graceful fallback), download to temp file with original extension (`.bin` fallback), caption enrichment, reply context prepend, `_invoke_agent` call with attachments, message ID caching, metadata storage, typing indicator, and error handling all implemented. All 12 unit tests pass.

**Deviations from spec**: none
