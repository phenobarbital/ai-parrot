# Brainstorm: Telegram Wrapper — Rich Message Integration (Replies, Documents, Attachment Passthrough)

**Date**: 2026-04-23
**Author**: Jesus Lara
**Status**: exploration
**Recommended Option**: Option A

---

## Problem Statement

The Telegram integration wrapper (`TelegramAgentWrapper`) currently handles text messages well,
but several interactive Telegram features are either missing or broken:

1. **Reply context is lost**: When a user replies to a specific bot message (or their own message),
   the wrapper ignores `message.reply_to_message` entirely. The agent has no idea the user is
   referencing a previous exchange, losing critical conversational context.

2. **Attachments silently dropped**: The `handle_photo` handler downloads images and passes
   `attachments=[path]` to `agent.ask()`, but `base.py:ask()` accepts it in `**kwargs` and
   **never forwards it** to `llm_kwargs`. The attachment path only survives as text in the
   enriched caption (`[Attached image saved at: /tmp/...]`), but the structured `attachments`
   list is lost. Tools like JiraToolkit cannot access the file.

3. **Document handler is a stub**: `handle_document` (line 2552) acknowledges receipt but
   returns "not yet fully implemented." Documents (PDF, DOCX, CSV, etc.) are ignored.

**Who is affected**: End users interacting with AI-Parrot agents via Telegram — they cannot
reference previous messages, send documents, or reliably attach images to agent operations.

**Why now**: The JiraToolkit and other tools need file attachments for operations like
"add this image as a comment on ticket NAV-123." The wrapper already downloads files but
the pipeline drops them before they reach tools.

## Constraints & Requirements

- Private chats only (no group chat extensions)
- Reply context format: `"{current_message}, in reply to: {original_message}"` (truncated to 200 chars)
- Reply enrichment applies to ALL reply types (reply to bot message, reply to own message)
- Document handler: download + pass path as attachment (same pattern as photos). No text extraction.
- Attachment passthrough: verify `attachments` kwarg reaches the agent properly
- Store Telegram message IDs in `ConversationTurn.metadata` for reply correlation
- Add logging for attachment flow debugging
- No changes to `AbstractBot.ask()` signature — use existing `**kwargs` passthrough or enrich via question text

---

## Options Explored

### Option A: Enrich-at-Wrapper-Level (Text Injection + Metadata Storage)

Solve all three issues entirely within the Telegram wrapper layer, without modifying the
bot/agent core. Reply context is injected as structured XML into the question text (same
pattern as `_enrich_question`). Attachments are passed both as text references AND as
`**kwargs`. Message IDs are stored in `ConversationTurn.metadata`.

**How it works:**
- Reply context: Check `message.reply_to_message` in every handler. If present, prepend
  `<reply_context>` XML block to the question with the original message text (truncated 200 chars).
- Documents: Implement `handle_document` following the exact `handle_photo` pattern — download
  to temp, pass as `attachments`, enrich caption with file path.
- Attachments: Add `attachments` to `_invoke_agent` signature and forward to `agent.ask()`.
  Also embed path in question text as fallback since `base.py` may drop `**kwargs`.
- Message ID storage: After each `agent.ask()` response, store the Telegram `message_id` in
  `ConversationTurn.metadata['telegram_message_id']` for reply correlation lookups.

✅ **Pros:**
- Zero changes to bot/agent core — all changes in the wrapper
- Reply context uses the proven `_enrich_question` XML injection pattern
- Document handler follows the exact established `handle_photo` pattern
- Message ID storage uses existing `metadata` field on `ConversationTurn`
- Minimal blast radius — only `wrapper.py` and `_invoke_agent` change

❌ **Cons:**
- Attachment paths embedded in text is a workaround, not a first-class mechanism
- Reply correlation relies on scanning `metadata` across conversation turns (O(n) per lookup)
- If `base.py` drops `attachments` from `**kwargs`, tools still can't access files programmatically

📊 **Effort:** Low

📦 **Libraries / Tools:**
| Package | Purpose | Notes |
|---|---|---|
| `aiogram` 3.27.0 | Telegram Bot API (already in use) | `Message.reply_to_message` attribute |
| No new dependencies | — | — |

🔗 **Existing Code to Reuse:**
- `wrapper.py:handle_photo` (line 2476) — download + attachment pattern for documents
- `wrapper.py:_enrich_question` (line 902) — XML injection pattern for reply context
- `wrapper.py:_invoke_agent` (line 1114) — agent invocation entry point to add attachments
- `abstract.py:ConversationTurn.metadata` (line 20) — store message IDs

---

### Option B: First-Class Attachments in Agent Core

Extend the `AbstractBot.ask()` signature to include an explicit `attachments: List[str]` parameter,
propagate it through `base.py` into `llm_kwargs`, and make the LLM client / tool manager aware
of available attachments. Reply context handled same as Option A.

**How it works:**
- Add `attachments: Optional[List[str]] = None` to `AbstractBot.ask()` and `base.py`'s ask method.
- Forward `attachments` into `llm_kwargs` so tools can access them.
- Store attachment references alongside the conversation turn.
- Document handler and reply context same as Option A.

✅ **Pros:**
- Attachments become a first-class concept across the entire framework
- Tools can programmatically access `attachments` via the LLM call context
- Other integrations (Slack, Teams, WhatsApp) benefit from the same mechanism
- Clean, no text-injection workaround needed for file paths

❌ **Cons:**
- Requires modifying `abstract.py`, `base.py`, and every `ask()` override (10+ files)
- Must update the LLM client layer to forward attachments to tool execution context
- Larger blast radius — could break existing agent implementations
- Scope creep: this is an architectural change, not a wrapper fix

📊 **Effort:** High

📦 **Libraries / Tools:**
| Package | Purpose | Notes |
|---|---|---|
| `aiogram` 3.27.0 | Telegram Bot API | Same as Option A |
| No new dependencies | — | — |

🔗 **Existing Code to Reuse:**
- `bots/abstract.py:ask()` (line 2914) — would need signature change
- `bots/base.py:ask()` (line 562) — would need `attachments` forwarding to `llm_kwargs`
- All existing `ask()` implementations across 10+ bot classes

---

### Option C: Middleware-Based Attachment Pipeline

Introduce an `AttachmentMiddleware` in the prompt pipeline that intercepts attachment references
and makes them available to tools via a request-scoped context object, without modifying `ask()`.

**How it works:**
- Create `AttachmentContext` (a context variable) that stores file paths for the current request.
- A prompt pipeline middleware extracts `[Attached ...]` markers from the question and populates
  the context.
- Tools access `AttachmentContext.get()` to retrieve files for the current request.
- Reply context and document handler same as Option A.

✅ **Pros:**
- No signature changes to `ask()`
- Tools can access attachments without text-parsing
- Uses existing prompt pipeline infrastructure
- Clean separation of concerns

❌ **Cons:**
- Adds complexity — a new abstraction layer for a narrow use case
- Context variables can be tricky with async concurrency (need careful scoping)
- Prompt pipeline middleware must parse text markers — fragile coupling
- Overengineered for 3 handlers in private chat scope

📊 **Effort:** Medium

📦 **Libraries / Tools:**
| Package | Purpose | Notes |
|---|---|---|
| `contextvars` | Request-scoped attachment context | Python stdlib |
| `aiogram` 3.27.0 | Telegram Bot API | Same as Option A |

🔗 **Existing Code to Reuse:**
- `wrapper.py:handle_photo` — still needed for download
- Prompt pipeline infrastructure (if it exists)

---

## Recommendation

**Option A** is recommended because:

- The scope is explicitly wrapper-side only. The user confirmed that whether tools can
  programmatically use attachments is a different scope. Option A solves all three stated
  problems without touching the agent core.
- The attachment path is already embedded in the enriched caption text, and this is how the
  LLM "sees" the file today. Making this more reliable and adding logging is the right
  incremental step.
- Option B (first-class attachments) is the correct long-term architecture but it's a framework-wide
  change that should be its own feature, not bundled with a Telegram wrapper fix.
- Option C adds unnecessary abstraction for a problem that's currently scoped to private Telegram chats.

**What we're trading off**: Option A leaves the `attachments` kwarg potentially dropped by
`base.py`. This is acceptable because (1) the path is in the question text as well, and
(2) a future "first-class attachments" feature (Option B) can be done as a separate spec.

---

## Feature Description

### User-Facing Behavior

**Replies:**
When a user long-presses a message in Telegram and replies to it, the agent sees enriched
context. Example:
- User replies to bot message "Created ticket NAV-123" with "Add Jesus as Watcher"
- Agent receives: `"Add Jesus as Watcher\n\n<reply_context>Created ticket NAV-123</reply_context>"`
- Agent understands the user is referencing ticket NAV-123 from the previous response

This works for replies to bot messages AND to the user's own messages.
Original message text is truncated to 200 characters max.

**Documents:**
When a user sends a PDF, DOCX, CSV, or any file:
- Bot shows a brief acknowledgment (e.g., "Processing document: report.pdf...")
- File is downloaded and its path is passed to the agent
- Agent caption defaults to the document's filename if no caption is provided
- Agent processes the request with the file path available in the question text

**Photo attachment logging:**
When a user sends a photo with a caption:
- Existing flow continues (download, pass to agent)
- New debug logging tracks the attachment path through the pipeline
- If `attachments` kwarg is dropped by `agent.ask()`, the path is still in the enriched text

### Internal Behavior

**Reply context flow:**
1. In `handle_message`, `handle_photo`, `handle_voice`, `handle_document`: check `message.reply_to_message`
2. If present, extract `reply_to_message.text` (or `reply_to_message.caption` for media)
3. Truncate to 200 chars
4. Prepend `<reply_context>{truncated_text}</reply_context>` to the user's question
5. Pass enriched question through normal `_enrich_question` → `_invoke_agent` flow

**Message ID storage flow:**
1. Before calling `agent.ask()`, record `message.message_id` as the "user message ID"
2. After `agent.ask()` returns and the response is sent via `message.answer()`, the returned
   `Message` object contains the bot's response `message_id`
3. Store both IDs in `ConversationTurn.metadata`:
   ```
   metadata['telegram_message_id'] = user_message_id
   metadata['telegram_bot_message_id'] = bot_response_message_id
   ```
4. For reply lookups: scan recent turns for matching `telegram_bot_message_id`

**Document handler flow:**
1. Auth + authorization checks (same as photo handler)
2. Extract `document.file_id`, `document.file_name`, `document.mime_type`
3. Download to temp file with original extension
4. Build attachment paths list
5. Enrich caption with file path and metadata
6. Call `_invoke_agent` with enriched question
7. Clean up temp file in `finally` block (unlike photos, documents don't need to persist)

**Attachment passthrough improvements:**
1. Add `attachments: Optional[List[str]]` parameter to `_invoke_agent`
2. Forward it to `agent.ask(..., attachments=attachments)`
3. Add `self.logger.debug()` calls at each stage of the attachment pipeline
4. Embed path in question text as primary mechanism (works regardless of `**kwargs` handling)

### Edge Cases & Error Handling

- **Reply to non-text message**: If user replies to a photo/voice/document, extract
  `caption` or `"[Voice message]"` / `"[Document: filename.pdf]"` as the reply context
- **Reply to deleted message**: `reply_to_message` may be `None` even though the user replied.
  aiogram returns `None` for deleted messages. Handle gracefully (no reply context added).
- **Very long original messages**: Truncate at 200 chars with "..." suffix
- **Document download failure**: Log error, send user-friendly message, don't crash
- **Large documents**: Telegram API limits file downloads to 20MB. Check `document.file_size`
  before downloading; reject with message if over limit.
- **Unknown MIME types**: Use the file extension from `document.file_name`; fall back to `.bin`
- **Concurrent messages**: `_agent_lock` already serializes per-wrapper; message ID storage
  must happen inside the lock scope to maintain ordering

---

## Capabilities

### New Capabilities
- `telegram-reply-context`: Extract and inject reply-to-message context into agent questions
- `telegram-document-handler`: Download and pass document attachments to agent
- `telegram-message-id-tracking`: Store Telegram message IDs in conversation turn metadata

### Modified Capabilities
- `telegram-photo-handler`: Add logging for attachment passthrough debugging
- `telegram-invoke-agent`: Extend `_invoke_agent` to accept and forward `attachments`

---

## Impact & Integration

| Affected Component | Impact Type | Notes |
|---|---|---|
| `integrations/telegram/wrapper.py` | modifies | Reply context, document handler, attachment logging, `_invoke_agent` signature |
| `memory/abstract.py` | extends (usage) | No schema change — uses existing `metadata` dict on `ConversationTurn` |
| `integrations/telegram/models.py` | extends | Optional: add `max_document_size_mb` config field |
| `bots/base.py` | no change | `attachments` passes through `**kwargs` (may be dropped — documented limitation) |

---

## Code Context

### User-Provided Code
None — feature described verbally.

### Verified Codebase References

#### Classes & Signatures
```python
# From packages/ai-parrot/src/parrot/integrations/telegram/wrapper.py:62
class TelegramAgentWrapper:
    # Handler registration at lines 148-305
    # _enrich_question at line 902 (static method)
    # _invoke_agent at line 1114
    # handle_message at line 1913
    # handle_photo at line 2476
    # handle_document at line 2552 (STUB)
    # handle_voice at line 2585

# From packages/ai-parrot/src/parrot/integrations/telegram/wrapper.py:1114
async def _invoke_agent(
    self,
    session: TelegramUserSession,
    question: str,
    *,
    memory: Any,
    output_mode: OutputMode = OutputMode.TELEGRAM,
    message: Optional[Message] = None,
) -> Any:
    # Calls agent.ask() at lines 1150 and 1166
    # Does NOT accept or forward 'attachments'

# From packages/ai-parrot/src/parrot/memory/abstract.py:10
@dataclass
class ConversationTurn:
    turn_id: str                                    # line 12
    user_id: str                                    # line 13
    user_message: str                               # line 14
    assistant_response: str                         # line 15
    metadata: Dict[str, Any] = field(default_factory=dict)  # line 20

# From packages/ai-parrot/src/parrot/bots/base.py:562
async def ask(
    self,
    question: str,
    ...
    **kwargs     # attachments lands here but is NEVER forwarded to llm_kwargs
) -> AIMessage:
    # llm_kwargs built at line 799 — only specific keys included
    # attachments silently dropped
```

#### Verified Imports
```python
# These imports are confirmed to work in wrapper.py:
from aiogram import Bot, Router, F                           # line 20
from aiogram.enums import ChatType                           # line 21
from aiogram.types import Message, ContentType               # line 22
from aiogram.filters import CommandStart, Command            # line 28
```

#### Key Attributes & Constants
- `message.reply_to_message` → `Optional[Message]` (aiogram v3 attribute, NOT used in wrapper)
- `message.reply_to_message.text` → `Optional[str]` (text of the replied-to message)
- `message.reply_to_message.caption` → `Optional[str]` (caption of replied-to media message)
- `message.document.file_id` → `str` (Telegram file ID for download)
- `message.document.file_name` → `Optional[str]` (original filename)
- `message.document.file_size` → `Optional[int]` (bytes)
- `message.document.mime_type` → `Optional[str]`
- `ConversationTurn.metadata` → `Dict[str, Any]` (abstract.py:20)
- `message.message_id` → `int` (unique per-chat message identifier)

### Does NOT Exist (Anti-Hallucination)
- ~~`TelegramAgentWrapper._reply_cache`~~ — no reply cache exists; must be built
- ~~`AbstractBot.ask(attachments=...)`~~ — not an explicit parameter; goes to `**kwargs` and is dropped
- ~~`ConversationTurn.telegram_message_id`~~ — not a field; must use `metadata` dict
- ~~`TelegramAgentWrapper.handle_reply`~~ — no dedicated reply handler; reply detection must be added to existing handlers
- ~~`base.py` forwarding of `attachments` to `llm_kwargs`~~ — does NOT happen (line 799-822)

---

## Parallelism Assessment

- **Internal parallelism**: Moderate. Reply context enrichment, document handler, and message ID tracking
  touch different parts of `wrapper.py` but share `_invoke_agent`. The document handler and reply context
  can be developed in sequence within one worktree (they share the same file and pattern).
- **Cross-feature independence**: No conflicts with in-flight specs. Changes are isolated to
  `wrapper.py` and don't touch bot core, LLM clients, or other integrations.
- **Recommended isolation**: `per-spec` (all tasks sequential in one worktree)
- **Rationale**: All three capabilities modify the same file (`wrapper.py`) and the message ID
  tracking is needed by reply context. Sequential execution in one worktree avoids merge conflicts.

---

## Open Questions

- [x] Should reply context include the replied-to message's sender name? — *Owner: Jesus*: No, just the message text truncated to 200 chars.
- [x] Should the document handler extract text from PDFs/DOCX? — *Owner: Jesus*: No, just download and pass path as attachment.
- [x] Should voice/photo handlers also get reply context? — *Owner: Jesus*: Yes, all handlers should check for reply context.
- [ ] Should there be a config toggle for reply context enrichment (e.g., `enable_reply_context: bool`)? — *Owner: Jesus*
- [ ] What should `handle_document` do for files > 20MB (Telegram API limit)? Reject with message or attempt partial download? — *Owner: Jesus*
- [ ] Should `_invoke_agent` log attachment paths at DEBUG or INFO level? — *Owner: Jesus*
