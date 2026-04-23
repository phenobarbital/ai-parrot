# Feature Specification: Telegram Wrapper — Rich Message Integration

**Feature ID**: FEAT-120
**Date**: 2026-04-23
**Author**: Jesus Lara
**Status**: approved
**Target version**: next
**Brainstorm**: `sdd/proposals/telegram-wrapper-audio-files-integration.brainstorm.md`

---

## 1. Motivation & Business Requirements

### Problem Statement

The Telegram integration wrapper (`TelegramAgentWrapper`) currently handles text messages well,
but several interactive Telegram features are either missing or broken:

1. **Reply context is lost**: When a user replies to a specific bot message (or their own message),
   the wrapper ignores `message.reply_to_message` entirely. The agent has no idea the user is
   referencing a previous exchange, losing critical conversational context.

2. **Attachments silently dropped**: The `handle_photo` handler downloads images and passes
   `attachments=[path]` to `agent.ask()`, but `base.py:ask()` accepts it in `**kwargs` and
   never forwards it to `llm_kwargs`. The attachment path only survives as text in the
   enriched caption (`[Attached image saved at: /tmp/...]`), but the structured `attachments`
   list is lost. Tools like JiraToolkit cannot access the file.

3. **Document handler is a stub**: `handle_document` (line 2552) acknowledges receipt but
   returns "not yet fully implemented." Documents (PDF, DOCX, CSV, etc.) are ignored.

End users interacting with AI-Parrot agents via Telegram cannot reference previous messages,
send documents, or reliably attach images to agent operations like "add this image as a
comment on Jira ticket NAV-123."

### Goals

- Enable reply context enrichment: when a user replies to any message, the agent sees the
  original message text alongside the new question
- Complete the document handler: download any file type and pass its path to the agent
- Improve attachment passthrough reliability with logging and text-based path injection
- Store Telegram message IDs in conversation turn metadata for reply correlation
- All changes scoped to the wrapper layer — no modifications to the bot/agent core

### Non-Goals (explicitly out of scope)

- Modifying `AbstractBot.ask()` signature or `base.py` `llm_kwargs` construction — this is a
  framework-wide change that belongs in a separate spec (see brainstorm Option B)
- Text extraction from documents (PDF-to-text, DOCX-to-text) — just download and pass the path
- Group chat support for photo/voice/document handlers — private chats only
- Tool-side attachment consumption (making JiraToolkit programmatically use `attachments` kwarg) —
  different scope; the wrapper's job is to make the path available in the question text

---

## 2. Architectural Design

### Overview

All three capabilities are implemented entirely within the Telegram wrapper layer using
**Option A: Enrich-at-Wrapper-Level** from the brainstorm. The approach leverages the
existing XML injection pattern (`_enrich_question`) and the `handle_photo` download pattern.

**Reply context**: A new helper method `_extract_reply_context(message)` checks
`message.reply_to_message` on every incoming message. If present, it extracts the original
message text (or caption for media messages), truncates to 200 characters, and wraps it in a
`<reply_context>` XML block that is prepended to the user's question before it reaches
`_enrich_question`.

**Document handler**: `handle_document` is completed following the exact `handle_photo`
pattern — download to temp file, build attachment paths, enrich caption with file path,
call `_invoke_agent`.

**Attachment passthrough**: `_invoke_agent` gains an optional `attachments` parameter that
is forwarded to `agent.ask()` via `**kwargs`. The file path is also embedded in the question
text as the primary mechanism (since `base.py` may drop `**kwargs` — documented limitation).

**Message ID tracking**: After each `agent.ask()` call, the wrapper retrieves the latest
conversation turn from memory and injects `telegram_message_id` and `telegram_bot_message_id`
into its `metadata` dict. For reply correlation, the wrapper also maintains a lightweight
per-chat `_message_id_cache` mapping `message_id → text_snippet` for the most recent messages.

### Component Diagram

```
Telegram User
     │
     ▼
┌─────────────────────────────────────────────────────┐
│  TelegramAgentWrapper                                │
│                                                      │
│  message.reply_to_message ──► _extract_reply_context │
│          │                         │                 │
│          ▼                         ▼                 │
│  handle_message ──────────► question + <reply_context>│
│  handle_photo   ──────────► question + [Attached...] │
│  handle_document ─────────► question + [Attached...] │
│  handle_voice   ──────────► transcribed + context    │
│          │                                           │
│          ▼                                           │
│  _invoke_agent(question, attachments=[...])           │
│          │                                           │
│          ▼                                           │
│  agent.ask(enriched_question, attachments=[...])     │
│          │                                           │
│          ▼                                           │
│  Store telegram_message_id in ConversationTurn.metadata│
│  Update _message_id_cache                             │
└─────────────────────────────────────────────────────┘
```

### Integration Points

| Existing Component | Integration Type | Notes |
|---|---|---|
| `TelegramAgentWrapper` (wrapper.py) | modifies | New helper methods, extended handlers, updated `_invoke_agent` |
| `ConversationTurn.metadata` (abstract.py) | uses (no schema change) | Stores `telegram_message_id` and `telegram_bot_message_id` in existing `Dict[str, Any]` |
| `TelegramAgentConfig` (models.py) | extends | Optional `max_document_size_mb` config field |
| `AbstractBot.ask(**kwargs)` (base.py) | passes through | `attachments` forwarded via `**kwargs`; may be dropped by `base.py` — path in text is primary |

### Data Models

No new Pydantic models. The feature uses existing structures:

```python
# ConversationTurn.metadata additions (convention, not schema)
metadata = {
    # Existing fields (set by base.py):
    'response_time': float,
    'model': str,
    'usage': dict,
    'finish_reason': str,
    # New fields (set by wrapper after ask()):
    'telegram_message_id': int,       # User's message ID
    'telegram_bot_message_id': int,   # Bot's response message ID
}
```

```python
# Per-chat message ID cache (wrapper instance attribute)
# Maps message_id → text snippet (max 200 chars) for reply lookups
_message_id_cache: Dict[int, Dict[int, str]]  # {chat_id: {message_id: text}}
```

### New Public Interfaces

No new public interfaces. All changes are internal to the wrapper.

New internal methods:

```python
# wrapper.py — new helper
def _extract_reply_context(self, message: Message) -> str:
    """Extract reply-to context from a Telegram message.

    Returns an XML-wrapped string of the original message text
    (truncated to 200 chars), or empty string if not a reply.
    """
    ...

# wrapper.py — new helper
def _cache_message_id(self, chat_id: int, message_id: int, text: str) -> None:
    """Store a message_id → text mapping in the per-chat cache."""
    ...

# wrapper.py — new helper
async def _store_telegram_metadata(
    self, memory: Any, user_id: str, session_id: str,
    user_message_id: int, bot_message_id: int,
) -> None:
    """Inject Telegram message IDs into the latest conversation turn metadata."""
    ...
```

---

## 3. Module Breakdown

### Module 1: Reply Context Extraction

- **Path**: `packages/ai-parrot/src/parrot/integrations/telegram/wrapper.py`
- **Responsibility**: Detect when an incoming message is a reply, extract the original message
  text (or caption/placeholder for media), truncate to 200 chars, and return a `<reply_context>`
  XML block. Applied in `handle_message`, `handle_photo`, `handle_voice`, and `handle_document`.
- **Depends on**: None (standalone helper)

### Module 2: Message ID Tracking

- **Path**: `packages/ai-parrot/src/parrot/integrations/telegram/wrapper.py`
- **Responsibility**: After each `agent.ask()` call and response send, store both the user's
  `message_id` and the bot's response `message_id` in `ConversationTurn.metadata`. Maintain
  a per-chat `_message_id_cache` for O(1) reply lookups by Module 1.
- **Depends on**: Module 1 (needs the cache for reply correlation)

### Module 3: Document Handler

- **Path**: `packages/ai-parrot/src/parrot/integrations/telegram/wrapper.py`
- **Responsibility**: Replace the stub `handle_document` with a full implementation: auth checks,
  size validation, download to temp file, enrich caption with file path, call `_invoke_agent`.
  Follow the exact `handle_photo` pattern.
- **Depends on**: Module 4 (needs `_invoke_agent` with `attachments` support)

### Module 4: Attachment Passthrough & Logging

- **Path**: `packages/ai-parrot/src/parrot/integrations/telegram/wrapper.py`
- **Responsibility**: Extend `_invoke_agent` to accept an optional `attachments` parameter and
  forward it to `agent.ask()`. Add `self.logger.debug()` calls at each stage of the attachment
  pipeline (download, path construction, agent call, response). Update `handle_photo` to use
  the improved `_invoke_agent` instead of calling `agent.ask()` directly.
- **Depends on**: None (foundational change)

### Module 5: Configuration Extension

- **Path**: `packages/ai-parrot/src/parrot/integrations/telegram/models.py`
- **Responsibility**: Add optional `max_document_size_mb: int = 20` config field to
  `TelegramAgentConfig` for document size limits.
- **Depends on**: None

---

## 4. Test Specification

### Unit Tests

| Test | Module | Description |
|---|---|---|
| `test_extract_reply_context_text_message` | 1 | Reply to text message → returns `<reply_context>text</reply_context>` |
| `test_extract_reply_context_caption` | 1 | Reply to photo with caption → returns caption in XML |
| `test_extract_reply_context_voice` | 1 | Reply to voice message → returns `[Voice message]` placeholder |
| `test_extract_reply_context_document` | 1 | Reply to document → returns `[Document: filename.pdf]` placeholder |
| `test_extract_reply_context_truncation` | 1 | Original message > 200 chars → truncated with `...` |
| `test_extract_reply_context_no_reply` | 1 | Not a reply → returns empty string |
| `test_extract_reply_context_deleted_message` | 1 | `reply_to_message` is None → returns empty string |
| `test_cache_message_id_stores` | 2 | Message ID and text stored in cache |
| `test_cache_message_id_eviction` | 2 | Cache evicts oldest entries when over limit |
| `test_store_telegram_metadata` | 2 | Both message IDs appear in ConversationTurn.metadata |
| `test_handle_document_downloads` | 3 | Document is downloaded and path passed to agent |
| `test_handle_document_size_limit` | 3 | Document > max size → user-friendly rejection |
| `test_handle_document_no_filename` | 3 | Document without filename → uses fallback extension |
| `test_handle_document_auth_required` | 3 | Unauthorized user → rejection message |
| `test_invoke_agent_forwards_attachments` | 4 | `attachments` kwarg reaches `agent.ask()` |
| `test_invoke_agent_logs_attachment_paths` | 4 | Debug log entries include attachment file paths |
| `test_handle_photo_uses_invoke_agent` | 4 | Photo handler calls `_invoke_agent` with attachments |

### Integration Tests

| Test | Description |
|---|---|
| `test_reply_to_bot_message_enriched` | Send text reply to bot response → agent receives `<reply_context>` enriched question |
| `test_photo_with_reply_context` | Reply to bot message with a photo → agent receives both reply context and attachment |
| `test_document_end_to_end` | Send a document → wrapper downloads, enriches, agent processes |
| `test_message_id_round_trip` | Send message → response → reply → verify reply correlates to original via metadata |

### Test Data / Fixtures

```python
@pytest.fixture
def mock_reply_message():
    """Aiogram Message mock with reply_to_message set."""
    reply_msg = MagicMock(spec=Message)
    reply_msg.text = "Created ticket NAV-123"
    reply_msg.caption = None
    reply_msg.voice = None
    reply_msg.document = None
    reply_msg.message_id = 100
    return reply_msg

@pytest.fixture
def mock_document_message():
    """Aiogram Message mock with document attachment."""
    doc = MagicMock()
    doc.file_id = "AgACAgIAAxkBAAI..."
    doc.file_name = "report.pdf"
    doc.file_size = 1024 * 500  # 500 KB
    doc.mime_type = "application/pdf"
    msg = MagicMock(spec=Message)
    msg.document = doc
    msg.caption = "Add this to the ticket"
    msg.chat.id = 12345
    msg.message_id = 200
    msg.reply_to_message = None
    return msg
```

---

## 5. Acceptance Criteria

- [ ] Reply context: replying to any message (text, photo, voice, document) enriches the question with `<reply_context>` XML containing the original text truncated to 200 chars
- [ ] Reply context: works for replies to bot messages AND user's own messages
- [ ] Reply context: gracefully handles deleted/unavailable replied-to messages (no crash, no context added)
- [ ] Reply context: replying to a media message without text uses a descriptive placeholder (`[Voice message]`, `[Document: filename.pdf]`)
- [ ] Document handler: downloads files to temp directory and passes path to agent via enriched question text
- [ ] Document handler: rejects files exceeding `max_document_size_mb` config (default 20MB) with user-friendly message
- [ ] Document handler: uses original file extension from `document.file_name`; falls back to `.bin` for unknown types
- [ ] Attachment passthrough: `_invoke_agent` accepts and forwards `attachments` kwarg to `agent.ask()`
- [ ] Attachment passthrough: `handle_photo` uses `_invoke_agent` instead of calling `agent.ask()` directly
- [ ] Attachment passthrough: debug logging at each stage of the pipeline (download, path, agent call)
- [ ] Message ID tracking: `telegram_message_id` (user) and `telegram_bot_message_id` (bot response) stored in `ConversationTurn.metadata`
- [ ] Message ID tracking: per-chat `_message_id_cache` maintained for reply lookups
- [ ] Private chats only — no group handler changes
- [ ] No changes to `AbstractBot.ask()` signature or `base.py` internals
- [ ] No breaking changes to existing text/photo/voice handler behavior
- [ ] All unit tests pass
- [ ] All integration tests pass

---

## 6. Codebase Contract

### Verified Imports

```python
# Confirmed in wrapper.py:
from aiogram import Bot, Router, F                           # line 20
from aiogram.enums import ChatType                           # line 21
from aiogram.types import (                                  # line 22
    Message, ContentType, FSInputFile, BotCommand,
    ReplyKeyboardRemove, CallbackQuery,
    InlineKeyboardMarkup, InlineKeyboardButton,
)
from aiogram.filters import CommandStart, Command            # line 28
import tempfile                                              # stdlib
from pathlib import Path                                     # stdlib
```

### Existing Class Signatures

```python
# packages/ai-parrot/src/parrot/integrations/telegram/wrapper.py:62
class TelegramAgentWrapper:
    agent: 'AbstractBot'                                     # line 89
    bot: Bot                                                 # line 90
    config: TelegramAgentConfig                              # line 91
    router: Router                                           # line 97
    conversations: Dict[int, 'ConversationMemory']           # line 98
    logger: logging.Logger                                   # line 99
    _user_sessions: Dict[int, TelegramUserSession]           # line 104
    _agent_lock: asyncio.Lock                                # line 107

    # Key methods:
    @staticmethod
    def _enrich_question(question: str, session: TelegramUserSession) -> str:  # line 902
        ...
    async def _invoke_agent(                                 # line 1114
        self, session: TelegramUserSession, question: str, *,
        memory: Any, output_mode: OutputMode = OutputMode.TELEGRAM,
        message: Optional[Message] = None,
    ) -> Any:
        ...
    async def handle_message(self, message: Message) -> None:     # line 1913
        ...
    async def handle_photo(self, message: Message) -> None:       # line 2476
        ...
    async def handle_document(self, message: Message) -> None:    # line 2552 (STUB)
        ...
    async def handle_voice(self, message: Message) -> None:       # line 2585
        ...

# packages/ai-parrot/src/parrot/memory/abstract.py:10
@dataclass
class ConversationTurn:
    turn_id: str                                              # line 12
    user_id: str                                              # line 13
    user_message: str                                         # line 14
    assistant_response: str                                   # line 15
    context_used: Optional[str] = None                        # line 17
    tools_used: List[str] = field(default_factory=list)       # line 18
    timestamp: datetime = field(default_factory=datetime.now) # line 19
    metadata: Dict[str, Any] = field(default_factory=dict)    # line 20

# packages/ai-parrot/src/parrot/bots/base.py:562
class BaseChatbot:
    async def ask(self, question: str, ..., **kwargs) -> AIMessage:
        # llm_kwargs constructed at line 799 — ONLY specific keys forwarded
        # attachments in **kwargs is SILENTLY DROPPED
        # ConversationTurn saved at line 826 with metadata from LLM response only
        ...
```

### Integration Points

| New Code | Connects To | Via | Verified At |
|---|---|---|---|
| `_extract_reply_context()` | `message.reply_to_message` | aiogram Message attribute | aiogram v3 API |
| `_invoke_agent(attachments=)` | `agent.ask(**kwargs)` | keyword argument passthrough | `wrapper.py:1150`, `wrapper.py:1166` |
| `_store_telegram_metadata()` | `memory.get_history()` → `turn.metadata` | dict mutation on latest turn | `abstract.py:20`, `base.py:826` |
| `handle_document()` | `bot.get_file()` / `bot.download_file()` | aiogram Bot methods | `wrapper.py:2500-2506` (photo handler pattern) |

### Does NOT Exist (Anti-Hallucination)

- ~~`TelegramAgentWrapper._reply_cache`~~ — no reply cache exists; must be created as `_message_id_cache`
- ~~`AbstractBot.ask(attachments=...)`~~ — not an explicit parameter; goes to `**kwargs` and is dropped by `base.py:799-822`
- ~~`ConversationTurn.telegram_message_id`~~ — not a dataclass field; must use `metadata` dict
- ~~`TelegramAgentWrapper.handle_reply`~~ — no dedicated reply handler exists; reply detection is added to existing handlers
- ~~`base.py` forwarding of `attachments` to `llm_kwargs`~~ — does NOT happen; the attachment path in question text is the primary mechanism
- ~~`memory.update_last_turn()`~~ — no such method; must retrieve history and mutate the last turn's metadata in-place
- ~~`TelegramAgentConfig.enable_reply_context`~~ — does not exist yet; may be added as part of this spec

---

## 7. Implementation Notes & Constraints

### Patterns to Follow

- **XML enrichment pattern**: Follow `_enrich_question` (line 902) — structured XML blocks appended to question text. The `<reply_context>` block should be prepended BEFORE `_enrich_question` adds `<user_context>`.
- **File download pattern**: Follow `handle_photo` (line 2476) — `bot.get_file()` → `bot.download_file()` → temp file → path as string.
- **Auth/authz pattern**: Every handler starts with `_is_authorized()` + `_check_authentication()` — document handler must follow this exactly.
- **Typing indicator pattern**: Long-running handlers use `asyncio.create_task(self._typing_indicator(chat_id))` with cancel in `finally`.
- **Error handling pattern**: Wrap in `try/except`, log with `self.logger.error(..., exc_info=True)`, send user-friendly `message.answer()`.
- **Logging**: Use `self.logger` (already `logging.getLogger(f"TelegramWrapper.{config.name}")`). Attachment flow logging at DEBUG level.

### Known Risks / Gotchas

- **`base.py` drops `attachments`**: The `attachments` kwarg passed to `agent.ask()` via `**kwargs` is silently dropped when `llm_kwargs` is built at `base.py:799`. The file path in the enriched question text is the primary mechanism for now. This is a documented limitation — a future "first-class attachments" spec can fix this properly.
- **Conversation turn metadata mutation**: After `agent.ask()`, the wrapper retrieves the latest turn from memory and mutates its `metadata` dict in-place. This works for `InMemoryConversation` (same object reference) but may not persist for Redis-backed memory. The message ID cache (`_message_id_cache`) provides a fallback.
- **Reply to deleted message**: `message.reply_to_message` is `None` when the original was deleted. The code must handle this gracefully (treat as non-reply).
- **Telegram 20MB download limit**: `bot.get_file()` fails for files > 20MB. Pre-check `document.file_size` (may be `None` for some file types — fallback to attempting download with error handling).
- **Temp file cleanup**: Document handler should clean up temp files in `finally` block. Photo handler intentionally does NOT clean up (agent tools may need the file later). Document handler follows the same no-cleanup pattern for consistency.
- **`_agent_lock` scope**: Message ID storage must happen inside the lock scope in singleton mode to maintain turn ordering.
- **Cache memory growth**: `_message_id_cache` must have a per-chat limit (e.g., last 100 messages) to avoid unbounded memory growth.

### External Dependencies

| Package | Version | Reason |
|---|---|---|
| `aiogram` | `>=3.27.0` | Already in use. `Message.reply_to_message`, `ContentType.DOCUMENT` |
| No new dependencies | — | All functionality built on existing aiogram + stdlib |

---

## 8. Open Questions

- [x] Should reply context include the replied-to message's sender name? — *Resolved in brainstorm*: No, just the message text truncated to 200 chars.
- [x] Should the document handler extract text from PDFs/DOCX? — *Resolved in brainstorm*: No, just download and pass path as attachment.
- [x] Should voice/photo handlers also get reply context? — *Resolved in brainstorm*: Yes, all handlers should check for reply context.
- [x] Should there be a config toggle for reply context enrichment (e.g., `enable_reply_context: bool`)? — *Owner: Jesus*: Yes
- [x] What should `handle_document` do for files > 20MB (Telegram API limit)? Reject with message or attempt partial download? — *Owner: Jesus*: reject message
- [x] Should `_invoke_agent` log attachment paths at DEBUG or INFO level? — *Owner: Jesus*: at DEBUG level

---

## Worktree Strategy

- **Isolation**: `per-spec` — all tasks run sequentially in one worktree
- **Rationale**: All five modules modify the same file (`wrapper.py`). Message ID tracking
  (Module 2) is needed by reply context (Module 1). Sequential execution avoids merge conflicts.
- **Cross-feature dependencies**: None. Changes are isolated to the wrapper layer.
- **Recommended execution order**: Module 5 (config) → Module 4 (attachments) → Module 2 (message IDs) → Module 1 (replies) → Module 3 (documents)

---

## Revision History

| Version | Date | Author | Change |
|---|---|---|---|
| 0.1 | 2026-04-23 | Jesus Lara | Initial draft from brainstorm |
